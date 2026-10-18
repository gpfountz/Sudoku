# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Idle timer updates must preserve state changes without redrawing an unchanged game."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sudoku.app import AppController
from sudoku.model import Game, Preferences


@pytest.mark.parametrize(
    ("paused", "active", "minimized", "elapsed"),
    [
        (False, True, False, 1.0),
        (True, True, False, 0.0),
        (False, False, False, 0.0),
        (False, True, True, 0.0),
    ],
)
def test_idle_tick_avoids_full_refresh(
    game: Game,
    monkeypatch: pytest.MonkeyPatch,
    paused: bool,
    active: bool,
    minimized: bool,
    elapsed: float,
) -> None:
    """Count foreground play without redrawing during normal or suspended idle ticks."""
    game.paused = paused
    controller: Any = make_controller(game, monkeypatch, active, minimized)
    AppController.tick_(controller, None)
    assert game.elapsed == elapsed
    controller.refresh.assert_not_called()
    controller.refresh_timer.assert_called_once()
    controller.save.assert_called_once()
    controller.update_current_day.assert_called_once()


def make_controller(
    game: Game,
    monkeypatch: pytest.MonkeyPatch,
    active: bool = True,
    minimized: bool = False,
) -> Any:
    """Provide a timer controller with deterministic time and native window state."""
    monkeypatch.setattr("sudoku.app.time.monotonic", lambda: 20.0)
    application: Mock = Mock()
    application.isActive.return_value = active
    monkeypatch.setattr(
        "sudoku.app.AK",
        SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda: application)),
    )
    window: Mock = Mock()
    window.isMiniaturized.return_value = minimized
    state: SimpleNamespace = SimpleNamespace(
        game=game,
        window=window,
        last_tick=19.0,
        last_save=0.0,
        save_problem="",
        save=Mock(),
        update_current_day=Mock(return_value=False),
        refresh=Mock(),
        refresh_timer=Mock(),
    )
    controller: Any = AppController.alloc().init()
    for name, value in vars(state).items():
        setattr(controller, name, value)
    return controller


@pytest.mark.parametrize("reason", ["new_day", "save_failed", "save_recovered"])
def test_tick_refreshes_changed_status(
    game: Game,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    """Keep a new day and save failure or recovery visible on idle ticks."""
    controller: Any = make_controller(game, monkeypatch)
    controller.update_current_day.return_value = reason == "new_day"
    controller.save_problem = "Disk full" if reason == "save_recovered" else ""

    def save() -> None:
        """Simulate a save result without writing user data."""
        controller.save_problem = "Disk full" if reason == "save_failed" else ""

    controller.save.side_effect = save
    AppController.tick_(controller, None)
    controller.refresh.assert_called_once()
    controller.refresh_timer.assert_not_called()


@pytest.mark.parametrize(
    ("elapsed", "previous", "visible", "expected"),
    [
        (61.0, "01:00", True, "01:01"),
        (3661.0, "00:00", True, "1:01:01"),
        (61.9, "01:01", True, None),
        (61.0, "01:00", False, None),
    ],
)
def test_timer_changes_only_when_needed(
    game: Game,
    elapsed: float,
    previous: str,
    visible: bool,
    expected: str | None,
) -> None:
    """Avoid native text mutations for unchanged seconds or a hidden timer."""
    game.elapsed = elapsed
    label: Mock = Mock()
    label.stringValue.return_value = previous
    controller: Any = SimpleNamespace(
        game=game,
        preferences=Preferences(show_timer=visible),
        controls={"timer": label},
    )
    AppController.refresh_timer(controller)
    if expected is None:
        label.setStringValue_.assert_not_called()
    else:
        label.setStringValue_.assert_called_once_with(expected)
