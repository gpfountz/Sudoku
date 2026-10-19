# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Import validation, immutable storage, replay, and compensated replacement behavior."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.run_import_preview import preview_directory
from sudoku.catalog import Catalog
from sudoku.engine import solve
from sudoku.history import HistoryStore
from sudoku.import_session import replace_attempt
from sudoku.model import LEVELS, Game, Puzzle
from sudoku.puzzle_import import ValidatedImport, parse_grid, validate_import
from sudoku.storage import SaveError, Store, game_data

ROWS: tuple[str, ...] = (
    "530070000",
    "600195000",
    "098000060",
    "800060003",
    "400803001",
    "700020006",
    "060000280",
    "000419005",
    "000080079",
)


@pytest.fixture
def validated() -> ValidatedImport:
    """Provide a known, uniquely solvable printed Sudoku."""
    return validate_import(parse_grid("\n".join(ROWS)))


def test_parse_text_preserves_blanks_and_rows() -> None:
    """Accept both specified clipboard representations without scraping surrounding text."""
    assert parse_grid("\n".join(ROWS)) == parse_grid("".join(ROWS).replace("0", "."))
    for invalid in ("", "123", "x" * 81, "９" * 81, "Puzzle: " + "".join(ROWS)):
        with pytest.raises(ValueError):
            parse_grid(invalid)


def test_validation_rejects_conflicts_and_multiple_solutions() -> None:
    """Do not allow incomplete or contradictory extraction to become playable."""
    with pytest.raises(ValueError, match="repeat"):
        validate_import((1, 1) + (0,) * 79)
    values: list[int] = list(parse_grid("".join(ROWS)))
    values[0] = 1
    with pytest.raises(ValueError, match="no solution"):
        validate_import(tuple(values))
    ambiguous: tuple[int, ...] = tuple(
        value if value not in (1, 2) else 0 for value in solve(parse_grid("".join(ROWS)))[0]
    )
    with pytest.raises(ValueError, match="Multiple"):
        validate_import(ambiguous)


def test_validation_can_be_bounded() -> None:
    """Bound solver time without changing the existing default solve behavior."""
    with pytest.raises(TimeoutError):
        validate_import(parse_grid("".join(ROWS)), timeout=0)


def test_import_identity_progress_and_replay(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
) -> None:
    """Reuse immutable identity while retaining independent progress and fresh attempts."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    first: Game = store.imported.start(validated, "Hard")
    store.activate_replay(first)
    assert first.puzzle.identifier == "IMP-000001"
    assert first.puzzle.rating is None
    empty: int = next(i for i, clue in enumerate(first.puzzle.givens) if not clue)
    first.mark(empty, 7)
    first.paint_color(empty)
    first.elapsed = 47
    store.save_game(first)
    restored: Game | None = Store(tmp_path).load_game(isolated_catalog)
    assert restored is not None
    assert restored.attempt_id == first.attempt_id
    assert restored.snapshot() == first.snapshot()
    assert restored.undo_stack == first.undo_stack
    assert restored.elapsed == 47
    replay: Game = store.start_replay(first.puzzle.identifier)
    assert replay.puzzle == first.puzzle
    assert replay.attempt_id != first.attempt_id
    assert replay.elapsed == 0
    assert not replay.undo_stack
    assert replay.values == list(first.puzzle.givens)
    duplicate: Game = store.imported.start(validated, "Extreme")
    assert duplicate.puzzle.identifier == first.puzzle.identifier
    assert duplicate.puzzle.givens == first.puzzle.givens
    assert duplicate.puzzle.solution == first.puzzle.solution
    assert duplicate.puzzle.level == "Extreme"
    saved: Puzzle | None = Store(tmp_path).imported.find_givens(validated.givens)
    assert saved is not None
    assert saved.level == "Extreme"
    old_attempt: Game = store.imported.load(first.puzzle.identifier, first.attempt_id)
    assert old_attempt.snapshot() == first.snapshot()
    assert old_attempt.elapsed == 47
    assert old_attempt.undo_stack == first.undo_stack
    assert duplicate.attempt_id != replay.attempt_id
    with sqlite3.connect(tmp_path / "imported.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM puzzles").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM attempts").fetchone()[0] == 3


@pytest.mark.parametrize("level", LEVELS)
def test_change_import_level_preserves_progress_and_history(
    tmp_path: Path, isolated_catalog: Catalog, validated: ValidatedImport, level: str
) -> None:
    """Retain the same attempt, all progress, prior History, and the new level after relaunch."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    previous: Game = store.imported.start(validated, "Hard")
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    history.record_outcome(previous, "Restarted", "2026-10-19T18:00:00+00:00")
    game: Game = store.start_replay(previous.puzzle.identifier)
    empty: int = next(index for index, value in enumerate(game.values) if not value)
    game.mark(empty, 5)
    game.paint_color(empty)
    game.set_value(empty, game.puzzle.solution[empty])
    game.undo()
    game.elapsed = 91
    game.paused = True
    game.viewed_hint_stages.add("a" * 64)
    before: dict[str, object] = game_data(game)
    puzzle: Puzzle = game.puzzle
    store.imported.change_level(game, level)
    assert game_data(game) == before
    assert game.puzzle.level == level
    assert game.puzzle.identifier == puzzle.identifier
    assert game.puzzle.givens == puzzle.givens
    assert game.puzzle.solution == puzzle.solution
    assert game.puzzle.rating is None
    restored: Game | None = Store(tmp_path).load_game(isolated_catalog)
    assert restored is not None
    assert restored.puzzle == game.puzzle
    assert game_data(restored) == before
    assert history.count() == 1
    assert history.page(0)[0].level == "Hard"
    replay: Game = store.start_replay(puzzle.identifier)
    assert replay.puzzle.level == level
    assert replay.attempt_id != game.attempt_id


def test_failed_import_level_change_rolls_back_metadata_and_progress(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll back the level update if saving current progress fails in the same transaction."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    game: Game = store.imported.start(validated, "Hard")
    puzzle: Puzzle = game.puzzle
    monkeypatch.setattr(
        store.imported, "write_attempt", Mock(side_effect=sqlite3.OperationalError("Disk full"))
    )
    with pytest.raises(SaveError, match="Disk full"):
        store.imported.change_level(game, "Expert")
    assert game.puzzle is puzzle
    assert store.imported.load(puzzle.identifier, game.attempt_id).puzzle == puzzle


def test_import_level_change_rejects_catalog_puzzles_and_invalid_levels(
    tmp_path: Path, isolated_catalog: Catalog, validated: ValidatedImport
) -> None:
    """Keep catalog definitions fixed and reject unsupported imported difficulty labels."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    builtin: Game = store.start_game("Easy")
    with pytest.raises(ValueError, match="imported puzzle"):
        store.imported.change_level(builtin, "Expert")
    game: Game = store.imported.start(validated, "Hard")
    with pytest.raises(ValueError, match="difficulty"):
        store.imported.change_level(game, "Unknown")
    assert store.imported.find(game.puzzle.identifier) == game.puzzle


def test_import_level_survives_failed_pointer_refresh(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume committed import metadata even when refreshing the cached pointer level fails."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    game: Game = store.imported.start(validated, "Hard")
    store.activate_replay(game)
    store.imported.change_level(game, "Expert")
    assert store.players is not None
    monkeypatch.setattr(
        store.players, "write_replay_index", Mock(side_effect=SaveError("Disk full"))
    )
    with pytest.raises(SaveError, match="Disk full"):
        store.save_game(game)
    restored: Game | None = Store(tmp_path).load_game(isolated_catalog)
    assert restored is not None
    assert restored.puzzle.level == "Expert"
    assert restored.attempt_id == game.attempt_id


def test_save_import_refreshes_pointer_level(
    tmp_path: Path, isolated_catalog: Catalog, validated: ValidatedImport
) -> None:
    """Keep the small active pointer consistent with a successfully relabeled import."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    game: Game = store.imported.start(validated, "Hard")
    store.activate_replay(game)
    store.imported.change_level(game, "Expert")
    store.save_game(game)
    assert store.players is not None
    index: dict[str, object] | None = store.players.read_index()
    assert index is not None
    assert isinstance(index["active"], dict)
    assert index["active"]["level"] == "Expert"


@pytest.mark.parametrize("daily_date", [None, "2026-10-03"])
def test_replacement_abandons_displayed_attempt_and_clears_daily_pointer(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
    daily_date: str | None,
) -> None:
    """Record the displayed predecessor, not an unrelated regular game in the background."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    previous: Game = store.start_game("Easy")
    if daily_date:
        previous = store.start_daily_game(daily_date, "Medium")
        store.save_active_daily_date(daily_date)
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    new: Game = replace_attempt(
        store, history, previous, daily_date, lambda: store.imported.start(validated, "Hard")
    )
    record = history.page(0)[0]
    assert record.attempt_id == previous.attempt_id
    assert record.daily_date == daily_date
    assert record.status == "Abandoned"
    assert store.load_active_daily_date() is None
    restored: Game | None = store.load_game(isolated_catalog)
    assert restored is not None
    assert restored.attempt_id == new.attempt_id


@pytest.mark.parametrize("failed_step", ["history", "pointer"])
def test_failed_replacement_preserves_history_and_active_game(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
    failed_step: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll back staged imports and false abandonment when publication fails."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    previous: Game = store.start_game("Easy")
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    if failed_step == "history":
        monkeypatch.setattr(
            history, "record_outcome", Mock(side_effect=SaveError("History failed"))
        )
    else:
        monkeypatch.setattr(store, "activate_replay", Mock(side_effect=SaveError("Pointer failed")))
    with pytest.raises(SaveError):
        replace_attempt(
            store, history, previous, None, lambda: store.imported.start(validated, "Hard")
        )
    assert history.count() == 0
    restored: Game | None = store.load_game(isolated_catalog)
    assert restored is not None
    assert restored.attempt_id == previous.attempt_id
    with sqlite3.connect(tmp_path / "imported.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM puzzles").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


def test_completed_predecessor_keeps_completed_history(
    tmp_path: Path,
    isolated_catalog: Catalog,
    validated: ValidatedImport,
) -> None:
    """Do not relabel a completed attempt when an import starts."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    previous: Game = store.start_game("Easy")
    previous.values = list(previous.puzzle.solution)
    previous.solved_at = "2026-10-03T12:00:00+00:00"
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    history.record_completion(previous)
    replace_attempt(store, history, previous, None, lambda: store.imported.start(validated, "Hard"))
    assert history.count() == 1
    assert history.page(0)[0].status == "Completed"


def test_preview_data_is_separate_from_production() -> None:
    """Keep manual preview data within the feature worktree, outside production support files."""
    assert preview_directory().parts[-2:] == (".preview-data", "puzzle-import")
    assert "Application Support" not in str(preview_directory())
