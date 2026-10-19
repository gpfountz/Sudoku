# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify real application transitions between imported, regular, and daily games."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import pytest

from sudoku.app import AppController
from sudoku.catalog import Catalog
from sudoku.history import HistoryStore
from sudoku.model import LEVELS, Game, Preferences, Puzzle
from sudoku.puzzle_import import ValidatedImport, validate_import
from sudoku.storage import SaveError, Store, game_data, game_from_data


@pytest.mark.parametrize("level", ["Expert", "Hard", "Unknown"])
def test_change_import_level_keeps_current_attempt(controller: Any, level: str) -> None:
    """Save an inline choice without restarting play, opening a dialog, or ending History."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    game: Game = controller.game
    game.elapsed = 123
    game.mark(next(index for index, value in enumerate(game.values) if not value), 5)
    before: dict[str, Any] = game_data(game)
    prior_count: int = controller.history.count()
    picker: Mock = Mock()
    picker.titleOfSelectedItem.return_value = level
    controller.refresh = Mock()
    controller.changeImportedLevel_(picker)
    expected: str = "Expert" if level == "Expert" else "Hard"
    assert controller.game is game is controller.regular_game
    assert game.puzzle.level == expected
    assert game_data(game) == before
    assert controller.history.count() == prior_count
    assert controller.store.imported.find(game.puzzle.identifier).level == expected
    controller.alert.assert_not_called()
    if level == "Expert":
        controller.window.makeFirstResponder_.assert_called_with(controller.board)
    else:
        picker.selectItemWithTitle_.assert_called_once_with("Hard")
        controller.refresh.assert_not_called()


def test_change_import_level_handles_save_failure(
    controller: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave the current level and attempt untouched when storage rejects the change."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    puzzle: Puzzle = controller.game.puzzle
    picker: Mock = Mock()
    picker.titleOfSelectedItem.return_value = "Expert"
    monkeypatch.setattr(
        controller.store.imported, "change_level", Mock(side_effect=SaveError("Disk full"))
    )
    controller.changeImportedLevel_(picker)
    assert controller.game.puzzle is puzzle
    picker.selectItemWithTitle_.assert_called_once_with("Hard")
    controller.alert.assert_called_once_with("Cannot change imported puzzle level", "Disk full")


@pytest.mark.parametrize("source", ["regular", "matched_import", "daily", "completed_import"])
def test_change_import_level_is_limited_to_unfinished_unmatched_imports(
    controller: Any, source: str
) -> None:
    """Reject direct actions on built-in matches, normal puzzles, daily games, and ended imports."""
    if source == "matched_import":
        puzzle: Puzzle = controller.catalog["Hard"][0]
        assert controller.play_import(validate_import(puzzle.givens), "Expert")
    elif source == "daily":
        controller.game = controller.store.start_daily_game(controller.current_day, "Medium")
        controller.active_daily_date = controller.current_day
    elif source == "completed_import":
        assert controller.play_import(import_puzzle(controller), "Hard")
        controller.game.values = list(controller.game.puzzle.solution)
    puzzle = controller.game.puzzle
    picker: Mock = Mock()
    controller.changeImportedLevel_(picker)
    picker.titleOfSelectedItem.assert_not_called()
    assert controller.game.puzzle is puzzle


@pytest.fixture
def controller(tmp_path: Path, isolated_catalog: Catalog) -> Any:
    """Use real storage with mocked presentation, independently of the player's data."""
    app: Any = AppController.alloc().init()
    app.store = Store(tmp_path)
    app.store.load_game(isolated_catalog)
    app.history = HistoryStore(tmp_path / "history.sqlite3")
    app.catalog = isolated_catalog
    app.regular_game = app.store.start_game("Easy")
    app.game = app.regular_game
    app.preferences = Preferences(daily_enabled=True)
    app.active_daily_date = None
    app.daily_games = {}
    app.current_day = "2026-10-03"
    app.update_current_day = Mock()
    app.board = Mock()
    app.window = Mock()
    app.changed = Mock()
    app.alert = Mock()
    app.save_problem = ""
    return app


def import_puzzle(controller: Any) -> ValidatedImport:
    """Select valid reviewed clues different from the controller's current puzzle."""
    givens: list[int] = list(controller.catalog["Hard"][0].givens)
    empty: int = givens.index(0)
    givens[empty] = controller.catalog["Hard"][0].solution[empty]
    return validate_import(tuple(givens))


@pytest.mark.parametrize("source", ["regular", "daily", "imported"])
def test_play_import_abandons_displayed_game(controller: Any, source: str) -> None:
    """Record exactly the displayed attempt and restore the newly imported game on launch."""
    validated: ValidatedImport = import_puzzle(controller)
    if source == "daily":
        controller.game = controller.store.start_daily_game(controller.current_day, "Medium")
        controller.active_daily_date = controller.current_day
    elif source == "imported":
        assert controller.play_import(validated, "Hard")
    previous: Game = controller.game
    prior_count: int = controller.history.count()
    assert controller.play_import(validated, "Expert")
    assert controller.game is controller.regular_game
    assert controller.game.puzzle.identifier.startswith("IMP-")
    assert controller.game.attempt_id != previous.attempt_id
    assert controller.active_daily_date is None
    assert controller.history.count() == prior_count + 1
    assert any(
        record.attempt_id == previous.attempt_id and record.status == "Abandoned"
        for record in controller.history.page(0)
    )
    restored: Game | None = Store(controller.store.directory).load_game(controller.catalog)
    assert restored is not None
    assert restored.attempt_id == controller.game.attempt_id


def test_import_failure_keeps_current_game(
    controller: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave both current state and History untouched when saving reviewed clues fails."""
    validated: ValidatedImport = import_puzzle(controller)
    previous: Game = controller.game
    monkeypatch.setattr(
        controller.store.imported, "start", Mock(side_effect=SaveError("Disk full"))
    )
    assert not controller.play_import(validated, "Hard")
    assert controller.game is previous
    assert controller.history.count() == 0
    controller.alert.assert_called_once()


def test_imported_history_replay_starts_fresh_attempt(controller: Any) -> None:
    """Reuse saved identity while recording the attempt being replaced as Abandoned."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    previous: Game = controller.game
    empty: int = next(i for i, value in enumerate(previous.values) if not value)
    previous.mark(empty, 5)
    previous.elapsed = 67
    controller.replay_puzzle(previous.puzzle.identifier)
    assert controller.game.puzzle == previous.puzzle
    assert controller.game.attempt_id != previous.attempt_id
    assert controller.game.elapsed == 0
    assert not any(controller.game.notes)
    assert controller.history.count() == 2


def test_new_regular_game_ends_import(controller: Any) -> None:
    """Abandon an unfinished import when New Game starts a catalog puzzle."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    previous: Game = controller.game
    dialog: Any = Mock()
    dialog.runModal.return_value = AK.NSAlertFirstButtonReturn
    dialog.accessoryView.return_value.titleOfSelectedItem.return_value = "Medium"
    controller.build_new_game_dialog = Mock(return_value=dialog)
    controller.newGame_(None)
    assert not controller.game.puzzle.identifier.startswith("IMP-")
    assert any(
        record.attempt_id == previous.attempt_id and record.status == "Abandoned"
        for record in controller.history.page(0)
    )


def test_daily_game_ends_import(controller: Any) -> None:
    """Do not resume the abandoned imported attempt when returning from a daily game."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    previous: Game = controller.game
    controller.dailyGames_(None)
    assert controller.active_daily_date == controller.current_day
    assert controller.regular_game.attempt_id != previous.attempt_id
    assert any(
        record.attempt_id == previous.attempt_id and record.status == "Abandoned"
        for record in controller.history.page(0)
    )


def test_restart_import_has_new_persisted_attempt(controller: Any) -> None:
    """Keep immutable clues and ID while recording Restarted and publishing a fresh attempt."""
    assert controller.play_import(import_puzzle(controller), "Hard")
    previous: Game = controller.game
    controller.alert.return_value = 1
    controller.restart_(None)
    assert controller.game.puzzle == previous.puzzle
    assert controller.game.attempt_id != previous.attempt_id
    assert any(
        record.attempt_id == previous.attempt_id and record.status == "Restarted"
        for record in controller.history.page(0)
    )
    assert controller.store.load_game(controller.catalog).attempt_id == controller.game.attempt_id


def test_abandoned_daily_reopens_as_a_new_attempt(controller: Any) -> None:
    """Keep the Abandoned outcome immutable when today's puzzle is opened again."""
    controller.dailyGames_(None)
    previous: Game = controller.game
    assert controller.play_import(import_puzzle(controller), "Hard")
    controller.dailyGames_(None)
    assert controller.game.puzzle == previous.puzzle
    assert controller.game.attempt_id != previous.attempt_id
    assert any(
        record.attempt_id == previous.attempt_id and record.status == "Abandoned"
        for record in controller.history.page(0)
    )


@pytest.mark.parametrize("level", LEVELS)
def test_matching_import_uses_builtin_identity_and_history(controller: Any, level: str) -> None:
    """Use catalog metadata, persist progress, and record completion under the built-in ID."""
    puzzle: Puzzle = controller.catalog[level][-1]
    assert controller.play_import(validate_import(puzzle.givens), "Master")
    game: Game = controller.game
    assert game.puzzle == puzzle
    assert not controller.store.imported.path.exists()
    game.elapsed = 123
    controller.store.save_game(game)
    restored: Game | None = Store(controller.store.directory).load_game(controller.catalog)
    assert restored is not None
    assert restored.puzzle == puzzle
    assert restored.attempt_id == game.attempt_id
    assert restored.elapsed == 123
    game.values = list(puzzle.solution)
    game.solved_at = "2026-10-15T12:00:00+00:00"
    controller.store.save_game(game)
    controller.history.record_completion(game)
    completed = next(row for row in controller.history.page(0) if row.attempt_id == game.attempt_id)
    assert completed.puzzle_id == puzzle.identifier
    assert completed.level == puzzle.level
    assert completed.daily_date is None
    assert completed.status == "Completed"
    assert controller.store.players.has_played(puzzle)


def test_matching_import_preserves_previous_progress(controller: Any) -> None:
    """Start a separate attempt when the same built-in puzzle is already in progress."""
    previous: Game = controller.game
    empty: int = previous.values.index(0)
    previous.mark(empty, 5)
    previous.elapsed = 82
    controller.store.save_game(previous)
    assert controller.play_import(validate_import(previous.puzzle.givens), "Extreme")
    assert controller.game.puzzle == previous.puzzle
    assert controller.game.attempt_id != previous.attempt_id
    assert controller.game.elapsed == 0
    assert not any(controller.game.notes)
    with controller.store.players.transaction(previous.puzzle.level) as connection:
        state: str = connection.execute(
            "SELECT state FROM games WHERE id=?", (previous.puzzle.identifier,)
        ).fetchone()[0]
    saved: Game = game_from_data(json.loads(state), previous.puzzle)
    assert saved.elapsed == 82
    assert saved.notes[empty] == {5}


def test_matching_import_save_failure_keeps_current_game(
    controller: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave the displayed game and History unchanged when staging a built-in attempt fails."""
    previous: Game = controller.game
    monkeypatch.setattr(controller.store, "start_replay", Mock(side_effect=SaveError("Disk full")))
    assert not controller.play_import(
        validate_import(controller.catalog["Extreme"][0].givens), "Medium"
    )
    assert controller.game is previous
    assert controller.history.count() == 0
    controller.alert.assert_called_once()


@pytest.mark.parametrize("failed_step", ["history", "pointer"])
def test_matching_import_publication_failure_does_not_mark_played(
    controller: Any, monkeypatch: pytest.MonkeyPatch, failed_step: str
) -> None:
    """Roll back the staged built-in attempt and its predecessor's false abandonment."""
    puzzle: Puzzle = controller.catalog["Extreme"][0]
    previous: Game = controller.game
    if failed_step == "history":
        monkeypatch.setattr(
            controller.history, "record_outcome", Mock(side_effect=SaveError("History failed"))
        )
    else:
        monkeypatch.setattr(
            controller.store, "activate_replay", Mock(side_effect=SaveError("Pointer failed"))
        )
    assert not controller.play_import(validate_import(puzzle.givens), "Medium")
    assert controller.game is previous
    assert controller.history.count() == 0
    assert not controller.store.players.has_played(puzzle)
    assert controller.store.load_game(controller.catalog).attempt_id == previous.attempt_id
