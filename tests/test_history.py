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
from sudoku.celebration import celebration_level
from sudoku.hint_types import Hint
from sudoku.history import SCHEMA, HistoryStore, hint_stage_key
from sudoku.model import LEVELS, Game, Preferences
from sudoku.storage import Store, game_data, game_from_data


def test_completion_awards_and_saves_rank_once(game: Game) -> None:
    """Save the first rank before presenting it and suppress a repeat after undo."""
    game.values = list(game.puzzle.solution)
    game.elapsed = 430
    game.incorrect_entries.add((1, 3))
    controller: Any = SimpleNamespace(
        game=game,
        completion_shown=False,
        clear_hint=Mock(),
        save=Mock(),
        refresh=Mock(),
        show_completion=Mock(),
    )
    AppController.changed(controller)
    assert game.completion_rank == "Great"
    assert game.solved_at is not None
    assert game_from_data(game_data(game), game.puzzle).completion_rank == "Great"
    controller.show_completion.assert_called_once_with()
    game.values[1] = 0
    AppController.changed(controller)
    game.values[1] = game.puzzle.solution[1]
    AppController.changed(controller)
    controller.show_completion.assert_called_once_with()


@pytest.mark.parametrize(
    ("mistakes", "hints", "revealed", "automatic", "rank"),
    (
        (0, 0, False, False, "Excellent"),
        (2, 1, False, False, "Great"),
        (0, 2, False, False, "Good"),
        (3, 0, False, False, "Good"),
        (0, 0, True, False, "Good"),
        (0, 0, False, True, "Good"),
    ),
)
def test_ranking_boundaries(
    game: Game, mistakes: int, hints: int, revealed: bool, automatic: bool, rank: str
) -> None:
    """Count logical hints and distinct errors and limit answer-assisted solves."""
    game.incorrect_entries = {(index, 9) for index in range(1, mistakes + 1)}
    game.viewed_hints = {str(index) * 64 for index in range(hints)}
    game.viewed_hint_stages = {"a" * 64, "b" * 64, "c" * 64}
    game.revealed_cells = {1} if revealed else set()
    game.auto_completed_cells = {2} if automatic else set()
    restored: Game = game_from_data(game_data(game), game.puzzle)
    assert restored.rank_for_completion() == rank


def test_old_save_and_celebration_range(game: Game) -> None:
    """Keep older attempts unranked and cover every intensity with the same three ranks."""
    payload: dict[str, Any] = game_data(game)
    del payload["viewed_hints"]
    assert game_from_data(payload, game.puzzle).rank_for_completion() is None
    assert [celebration_level(level, None) for level in LEVELS] == list(range(1, 7))
    assert {
        celebration_level(level, rank)
        for level in LEVELS
        for rank in ("Good", "Great", "Excellent")
    } == set(range(1, 11))


@pytest.mark.parametrize(
    ("mode", "enabled", "digit", "buzz"),
    (
        ("Off", True, 1, False),
        ("Rule Conflicts", True, 1, True),
        ("Rule Conflicts", True, 3, False),
        ("Against Solution", True, 3, True),
        ("Against Solution", True, 2, False),
        ("Against Solution", False, 3, False),
    ),
)
def test_wrong_answer_sound_follows_visible_errors(
    game: Game, mode: str, enabled: bool, digit: int, buzz: bool
) -> None:
    """Play only for a changed answer that the active error mode exposes."""
    controller: Any = SimpleNamespace(
        game=game,
        preferences=Preferences(error_check=mode, game_sounds=enabled),
        play_game_sound=Mock(),
    )
    assert AppController.enter_answer(controller, 1, digit)
    assert not AppController.enter_answer(controller, 1, digit)
    if buzz:
        controller.play_game_sound.assert_called_once_with("incorrect")
    else:
        controller.play_game_sound.assert_not_called()


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
    later.values = list(later.puzzle.solution)
    later.solved_at = second
    later.completion_rank = "Excellent"
    history.record_completion(later)
    history.record_completion(later)
    assert history.count() == 2
    assert history.page(0, 1)[0].completion_rank == "Excellent"


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
        connection.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS completion_ranks")[0])
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
    entry = next(entry for entry in history.page(0) if entry.attempt_id == game.attempt_id)
    assert entry.completion_rank is None


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
