# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""History identity, durable outcomes, paging, and exact-puzzle replays."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sudoku.app import AppController
from sudoku.catalog import Catalog, load_catalog
from sudoku.hint_types import Hint
from sudoku.history import SCHEMA, HistoryStore, hint_stage_key
from sudoku.model import Game
from sudoku.storage import Store, game_data, game_from_data


def test_completion_popup_starts_with_level_and_keeps_counts(game: Game) -> None:
    """Keep date and puzzle ID in history without cluttering the completion alert."""
    game.values = list(game.puzzle.solution)
    game.elapsed = 430
    game.incorrect_entries.add((1, 3))
    controller: Any = SimpleNamespace(
        game=game,
        completion_shown=False,
        clear_hint=Mock(),
        save=Mock(),
        refresh=Mock(),
        alert=Mock(),
    )
    AppController.changed(controller)
    title, message = controller.alert.call_args.args
    assert title == "Puzzle complete"
    assert message == "Level: Easy\nTime: 7:10\nHints: 0  ·  Reveals: 0\nIncorrect answers: 1"
    assert game.solved_at is not None


def test_repeated_mistake_is_one_distinct_cell_and_digit(game: Game) -> None:
    """Undo and reentry keep prior errors while another wrong digit counts separately."""
    index: int = 1
    first_wrong: int = next(d for d in range(1, 10) if d != game.puzzle.solution[index])
    second_wrong: int = next(
        d for d in range(1, 10) if d not in (first_wrong, game.puzzle.solution[index])
    )
    assert game.set_value(index, first_wrong)
    assert game.undo()
    assert game.set_value(index, first_wrong)
    assert game.set_value(index, second_wrong)
    assert game.incorrect_entries == {(index, first_wrong), (index, second_wrong)}
    restored: Game = game_from_data(game_data(game), game.puzzle)
    assert restored.incorrect_entries == game.incorrect_entries
    assert restored.attempt_id == game.attempt_id


def test_hint_stage_identity_changes_with_board_and_stage(game: Game) -> None:
    """The same stage on one board is free; a new board or stage counts again."""
    hint: Hint = Hint("Single", "Look here", "Place a digit", (1,), ((1, 2),))
    first: str = hint_stage_key(game, hint, 1)
    assert hint_stage_key(game, hint, 1) == first
    assert hint_stage_key(game, hint, 2) != first
    game.mark(2, 3)
    assert hint_stage_key(game, hint, 1) != first


def test_outcomes_are_idempotent_and_paged_newest_first(tmp_path: Path, game: Game) -> None:
    """A retry adds no duplicate, and a page reads only its requested rows."""
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    game.elapsed = 99.5
    game.viewed_hint_stages.add("a" * 64)
    game.revealed_cells.add(2)
    game.incorrect_entries.add((1, 3))
    first: str = datetime(2026, 9, 24, tzinfo=UTC).isoformat()
    second: str = datetime(2026, 9, 25, tzinfo=UTC).isoformat()
    assert history.record_outcome(game, "Restarted", first)
    assert not history.record_outcome(game, "Restarted", first)
    later: Game = Game(game.puzzle)
    assert history.record_outcome(later, "Abandoned", second)
    assert history.count() == 2
    assert [row.status for row in history.page(0, 1)] == ["Abandoned"]
    older = history.page(1, 1)[0]
    assert older.status == "Restarted"
    assert (older.elapsed_seconds, older.hint_count, older.reveal_count, older.incorrect_count) == (
        99.5,
        1,
        1,
        1,
    )
    assert history.page(2, 1) == []
    history.remove_outcome(later.attempt_id)
    assert history.count() == 1


@pytest.mark.parametrize("new_database_exists", [False, True])
def test_former_database_is_moved_or_merged(
    tmp_path: Path, game: Game, new_database_exists: bool
) -> None:
    """Preserve recorded attempts when the database filename changes."""
    new_path: Path = tmp_path / "history.sqlite3"
    if new_database_exists:
        current: Game = Game(game.puzzle)
        HistoryStore(new_path).record_outcome(current, "Abandoned", "2026-09-26T12:00:00+00:00")
    old_path: Path = tmp_path / "statistics.sqlite3"
    with sqlite3.connect(old_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO game_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                game.attempt_id,
                "2026-09-25T12:00:00+00:00",
                "Completed",
                game.puzzle.identifier,
                game.puzzle.level,
                120.0,
                1,
                0,
                0,
                None,
            ),
        )
    history: HistoryStore = HistoryStore(new_path)
    history.ensure_ready()
    assert history.count() == (2 if new_database_exists else 1)
    assert new_path.exists() and not old_path.exists()
    assert any(entry.attempt_id == game.attempt_id for entry in history.page(0))


def test_replay_is_separate_regular_attempt_on_exact_puzzle(tmp_path: Path) -> None:
    """Replay preserves the old regular state and does not consume a rotation slot."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    assert store.load_game(catalog) is None
    original: Game = store.start_game("Easy")
    original.elapsed = 43
    store.save_game(original)
    assert store.players is not None
    with store.players.transaction("Easy") as connection:
        before: int = connection.execute("SELECT remaining FROM rotation").fetchone()[0]
    replay: Game = store.start_replay(original.puzzle.identifier)
    assert replay.puzzle.identifier == original.puzzle.identifier
    assert replay.attempt_id != original.attempt_id
    replay.elapsed = 12
    store.save_game(replay)
    restored: Game | None = Store(tmp_path).load_game(catalog)
    assert restored is not None
    assert restored.attempt_id == replay.attempt_id and restored.elapsed == 12
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT remaining FROM rotation").fetchone()[0] == before
        assert connection.execute("SELECT count(*) FROM replays").fetchone()[0] == 1
        old_state: str = connection.execute(
            "SELECT state FROM games WHERE id=?", (original.puzzle.identifier,)
        ).fetchone()[0]
    assert game_from_data(json.loads(old_state), original.puzzle).elapsed == 43


def test_existing_player_database_adds_replay_table(tmp_path: Path) -> None:
    """A version-one player DB migrates without changing existing games."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    original: Game = store.start_game("Easy")
    path: Path = tmp_path / "players" / "easy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE replays")
        connection.execute("PRAGMA user_version=1")
    replay: Game = store.start_replay(original.puzzle.identifier)
    assert replay.puzzle.identifier == original.puzzle.identifier
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM games").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM replays").fetchone()[0] == 1
