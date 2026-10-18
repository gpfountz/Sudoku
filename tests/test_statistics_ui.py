# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native Statistics menu, filter actions, layout, refresh, and theme coverage."""

import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import pytest

from sudoku.app import AppController
from sudoku.catalog import load_catalog
from sudoku.history import HistoryStore
from sudoku.model import Game, Preferences
from sudoku.statistics_ui import COLUMNS, StatisticsWindow
from sudoku.storage import SaveError, Store
from sudoku.theme import theme_for_name
from sudoku.theme_names import THEME_NAMES

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1",
    reason="Native windows require a macOS WindowServer session; set RUN_NATIVE_LAYOUT_TESTS=1",
)


def test_statistics_menu_opens_reuses_and_refreshes_window(tmp_path: Path, game: Game) -> None:
    """Invoke the installed menu action and retain its filter across closing and reopening."""
    application: Any = AK.NSApplication.sharedApplication()
    previous_menu: Any = application.mainMenu()
    previous_windows_menu: Any = application.windowsMenu()
    controller: Any = AppController.alloc().init()
    controller.preferences = Preferences()
    controller.theme = theme_for_name("Default")
    controller.window = AK.NSWindow.alloc().init()
    controller.store = Store(tmp_path)
    controller.store.load_game(load_catalog())
    controller.history = HistoryStore(tmp_path / "history.sqlite3")
    controller.statistics_window = None
    try:
        controller.build_menu()
        menu: Any = application.mainMenu().itemWithTitle_("Game").submenu()
        item: Any = menu.itemWithTitle_("Statistics…")
        assert item is not None and item.target() is controller
        assert application.sendAction_to_from_(item.action(), item.target(), item)
        statistics: StatisticsWindow = controller.statistics_window
        assert statistics.source.rows[-1].games_played == 0
        statistics.include_imported.performClick_(None)
        statistics.window.close()
        controller.history.record_outcome(game, "Completed", "2026-10-15T12:00:00+00:00")
        assert application.sendAction_to_from_(item.action(), item.target(), item)
        assert controller.statistics_window is statistics
        assert statistics.source.rows[-1].games_played == 1
        assert statistics.include_imported.state() == AK.NSControlStateValueOn
    finally:
        if controller.statistics_window is not None:
            controller.statistics_window.window.close()
        controller.window.close()
        application.setMainMenu_(previous_menu)
        application.setWindowsMenu_(previous_windows_menu)


@pytest.mark.parametrize("scroller_style", [AK.NSScrollerStyleOverlay, AK.NSScrollerStyleLegacy])
def test_statistics_layout_filter_refresh_and_error_recovery(
    tmp_path: Path, game: Game, scroller_style: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep all nine columns and seven rows visible and update every filter action."""
    AK.NSApplication.sharedApplication()
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    assert store.players is not None
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    history.record_outcome(game, "Completed", "2026-10-15T12:00:00+00:00")
    imported: Game = Game(replace(game.puzzle, identifier="IMP-000001"))
    history.record_outcome(imported, "Abandoned", "2026-10-15T12:00:00+00:00")
    statistics: StatisticsWindow = StatisticsWindow(history, store.players)
    try:
        statistics.show()
        scroll: Any = statistics.table.enclosingScrollView()
        scroll.setScrollerStyle_(scroller_style)
        for width, height in [(1040, 450), (1260, 650), (1040, 450)]:
            statistics.window.setContentSize_((width, height))
            statistics.window.contentView().layoutSubtreeIfNeeded()
            scroll.tile()
            assert statistics.table.numberOfColumns() == 9
            assert statistics.table.numberOfRows() == 7
            assert not scroll.hasHorizontalScroller()
            assert AK.NSMaxX(statistics.table.rectOfColumn_(8)) <= (
                scroll.contentView().bounds().size.width
            )
            assert AK.NSMaxY(statistics.table.rectOfRow_(6)) <= (
                statistics.table.visibleRect().origin.y + statistics.table.visibleRect().size.height
            )
            assert not AK.NSIntersectsRect(
                statistics.status_label.frame(), statistics.include_imported.frame()
            )
            for index, (key, title, _) in enumerate(COLUMNS):
                column: Any = statistics.table.tableColumns()[index]
                assert str(column.identifier()) == key
                assert column.headerCell().stringValue() == title
                cell: Any = statistics.source.tableView_viewForTableColumn_row_(
                    statistics.table, column, 6
                )
                label: Any = cell.textField()
                assert label.stringValue()
                assert AK.NSMidY(label.frame()) == pytest.approx(statistics.table.rowHeight() / 2)
                assert label.intrinsicContentSize().width <= label.frame().size.width
        assert statistics.source.rows[-1].games_played == 1
        remaining: int = statistics.source.rows[-1].remaining_games
        statistics.include_imported.performClick_(None)
        assert statistics.source.rows[-1].games_played == 2
        assert statistics.source.rows[-1].remaining_games == remaining
        later: Game = Game(game.puzzle)
        history.record_outcome(later, "Restarted", "2026-10-15T12:00:00+00:00")
        statistics.refresh_button.performClick_(None)
        assert statistics.source.rows[-1].games_played == 3
        with monkeypatch.context() as patch:
            patch.setattr(
                store.players, "remaining_games", Mock(side_effect=SaveError("Unreadable"))
            )
            statistics.include_imported.performClick_(None)
            assert statistics.source.rows == []
            assert statistics.status_label.stringValue() == "Unreadable"
        statistics.refresh_button.performClick_(None)
        assert statistics.source.rows[-1].games_played == 2
    finally:
        statistics.window.close()


@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_statistics_follows_every_theme(tmp_path: Path, game: Game, appearance: str) -> None:
    """Render real rows and headers in each palette while preserving the import choice."""
    AK.NSApplication.sharedApplication()
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    assert store.players is not None
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    history.record_outcome(game, "Completed", "2026-10-15T12:00:00+00:00")
    statistics: StatisticsWindow = StatisticsWindow(history, store.players)
    try:
        statistics.show()
        statistics.include_imported.performClick_(None)
        for name in THEME_NAMES:
            theme: Any = theme_for_name(name)
            statistics.apply_theme(theme, AK.NSAppearance.appearanceNamed_(appearance))
            assert statistics.include_imported.state() == AK.NSControlStateValueOn
            assert statistics.table.backgroundColor().isEqual_(theme.controls.background)
            assert statistics.status_label.textColor().isEqual_(theme.secondary_text)
            assert statistics.table.headerView().theme is theme
            row: Any = statistics.table.rowViewAtRow_makeIfNecessary_(6, True)
            assert row.theme is theme
            for view in (statistics.window.contentView(), statistics.table.headerView(), row):
                bitmap: Any = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
                view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
                assert bitmap.pixelsWide() > 0 and bitmap.pixelsHigh() > 0
            for column in statistics.table.tableColumns():
                font: Any = column.headerCell().font()
                assert font.pointSize() == 13
                assert AK.NSFontManager.sharedFontManager().traitsOfFont_(font) & AK.NSBoldFontMask
            cell: Any = statistics.table.viewAtColumn_row_makeIfNecessary_(0, 6, True)
            assert cell.textField().textColor().isEqual_(theme.text)
    finally:
        statistics.window.close()
