# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify durable full-screen mode and native launch/close notification handling."""

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import pytest

from sudoku.app import AppController
from sudoku.model import Preferences
from sudoku.storage import Store


@pytest.fixture
def window_controller() -> Any:
    """Use a real Objective-C controller with isolated window and persistence doubles."""
    controller: Any = AppController.alloc().init()
    controller.preferences = Preferences()
    controller.window = Mock()
    controller.window.styleMask.return_value = AK.NSWindowStyleMaskTitled
    controller.window.isVisible.return_value = True
    controller.board = Mock()
    controller.save = Mock()
    controller.alert = Mock(return_value=0)
    controller.save_problem = ""
    controller.startup_failed = False
    return controller


def window_notification(window: Any) -> Mock:
    """Supply a notification identifying the window whose mode changed."""
    notification: Mock = Mock()
    notification.object.return_value = window
    return notification


@pytest.mark.parametrize("value", [True, False, None, "true", 1])
def test_saved_window_mode_is_strictly_boolean(tmp_path: Path, value: Any) -> None:
    """Accept valid saved modes and default old or malformed settings to normal windows."""
    assert not Preferences.from_dict({}).window_full_screen
    prefs: Preferences = Preferences.from_dict({"window_full_screen": value})
    assert prefs.window_full_screen is (value if type(value) is bool else False)
    store: Store = Store(tmp_path)
    store.save_preferences(prefs)
    assert Store(tmp_path).load_preferences().window_full_screen is prefs.window_full_screen


def test_full_screen_entry_and_deliberate_exit_are_saved(window_controller: Any) -> None:
    """Persist completed main-window transitions without reacting to auxiliary windows."""
    controller: Any = window_controller
    controller.windowDidEnterFullScreen_(window_notification(Mock()))
    controller.save.assert_not_called()
    controller.windowDidEnterFullScreen_(window_notification(controller.window))
    assert controller.preferences.window_full_screen
    controller.save.assert_called_once()
    controller.windowDidEnterFullScreen_(window_notification(controller.window))
    controller.save.assert_called_once()
    controller.windowDidExitFullScreen_(window_notification(Mock()))
    assert controller.preferences.window_full_screen
    controller.windowDidExitFullScreen_(window_notification(controller.window))
    assert not controller.preferences.window_full_screen
    assert controller.save.call_count == 2


def test_full_screen_close_survives_shutdown_exit_and_final_save(window_controller: Any) -> None:
    """A native close must preserve full-screen intent even after macOS clears the style."""
    controller: Any = window_controller
    controller.window.styleMask.return_value |= AK.NSWindowStyleMaskFullScreen
    assert controller.windowShouldClose_(controller.window)
    assert controller.preferences.window_full_screen and controller.main_window_closing
    controller.window.styleMask.return_value = AK.NSWindowStyleMaskTitled
    controller.windowDidExitFullScreen_(window_notification(controller.window))
    assert controller.applicationShouldTerminate_(Mock()) == AK.NSTerminateNow
    controller.applicationWillTerminate_(None)
    assert controller.preferences.window_full_screen


def test_command_q_captures_mode_and_ignores_shutdown_exit(window_controller: Any) -> None:
    """Save the live mode before an accepted quit can exit full screen."""
    controller: Any = window_controller
    controller.window.styleMask.return_value |= AK.NSWindowStyleMaskFullScreen
    assert controller.applicationShouldTerminate_(Mock()) == AK.NSTerminateNow
    assert controller.main_window_closing and controller.preferences.window_full_screen
    controller.window.styleMask.return_value = AK.NSWindowStyleMaskTitled
    controller.windowDidExitFullScreen_(window_notification(controller.window))
    controller.applicationWillTerminate_(None)
    assert controller.preferences.window_full_screen


def test_cancelled_quit_keeps_tracking_window_changes(window_controller: Any) -> None:
    """Declining to quit after a save failure must allow subsequent manual mode changes."""
    controller: Any = window_controller
    controller.window.styleMask.return_value |= AK.NSWindowStyleMaskFullScreen
    controller.save_problem = "Cannot save"
    assert controller.applicationShouldTerminate_(Mock()) == AK.NSTerminateCancel
    assert not controller.main_window_closing
    controller.windowDidExitFullScreen_(window_notification(controller.window))
    assert not controller.preferences.window_full_screen


@pytest.mark.parametrize("blocked", ["normal", "already_full", "closed", "hidden", "failed_start"])
def test_full_screen_restore_respects_current_window_state(
    window_controller: Any, blocked: str
) -> None:
    """Toggle only a visible, normal main window with a saved full-screen preference."""
    controller: Any = window_controller
    controller.preferences.window_full_screen = True
    if blocked == "already_full":
        controller.window.styleMask.return_value |= AK.NSWindowStyleMaskFullScreen
    elif blocked == "closed":
        controller.main_window_closing = True
    elif blocked == "hidden":
        controller.window.isVisible.return_value = False
    elif blocked == "failed_start":
        controller.startup_failed = True
    else:
        controller.preferences.window_full_screen = False
    controller.restoreFullScreen_(None)
    controller.window.toggleFullScreen_.assert_not_called()


def test_full_screen_restore_and_failure_fallback(window_controller: Any) -> None:
    """Request native full screen and persist normal mode if that request fails."""
    controller: Any = window_controller
    controller.preferences.window_full_screen = True
    controller.restoreFullScreen_(None)
    controller.window.toggleFullScreen_.assert_called_once_with(None)
    controller.windowDidFailToEnterFullScreen_(Mock())
    assert controller.preferences.window_full_screen
    controller.windowDidFailToEnterFullScreen_(controller.window)
    assert not controller.preferences.window_full_screen


def test_auxiliary_window_close_does_not_freeze_main_mode(window_controller: Any) -> None:
    """Closing Settings or History must not change game-window restoration behavior."""
    controller: Any = window_controller
    assert controller.windowShouldClose_(Mock())
    assert not controller.main_window_closing
    controller.save.assert_not_called()
