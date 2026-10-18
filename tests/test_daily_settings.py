# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Daily preference controls and old publisher data isolation."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from sudoku.app import AppController
from sudoku.catalog import load_catalog
from sudoku.model import Preferences
from sudoku.storage import Store


def test_daily_enable_has_no_publisher_consent() -> None:
    """Local daily games become available without a network permission dialog."""
    preferences: Preferences = Preferences()
    controller: Any = SimpleNamespace(
        preferences=preferences,
        board=Mock(),
        settings_controls={"daily_enabled": Mock()},
        returnRegular_=Mock(),
        update_daily_settings_visibility=Mock(),
        save=Mock(),
        build_menu=Mock(),
        layout=Mock(),
        refresh=Mock(),
    )
    AppController.set_daily_enabled(controller, True)
    assert preferences.daily_enabled
    controller.settings_controls["daily_enabled"].setState_.assert_called_once_with(1)
    controller.save.assert_called_once()


def test_old_download_files_are_not_used(tmp_path: Path) -> None:
    """The catalog daily system ignores the retired download directories."""
    store: Store = Store(tmp_path)
    store.write("daily-puzzles/2026-09-25.json", {"source": "retired"})
    store.write("daily-games/2026-09-25.json", {"state": "retired"})
    store.write("daily-index.json", {"active_date": "2026-09-25"})
    assert store.load_daily_game("2026-09-25", load_catalog()) is None
    assert store.load_active_daily_date() is None
