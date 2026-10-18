# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native Statistics table with an optional imported-attempt filter."""

from collections.abc import Callable
from typing import Any

import AppKit as AK
from Foundation import NSObject

from sudoku.controls import apply_action_theme, apply_native_accent, button_title
from sudoku.history import HistoryStore
from sudoku.history_ui import HistoryHeaderView, HistoryRowView, format_elapsed
from sudoku.player import PlayerStore
from sudoku.statistics import StatisticsRow, load_statistics
from sudoku.storage import SaveError
from sudoku.theme import DEFAULT_THEME, Theme

COLUMNS: tuple[tuple[str, str, float], ...] = (
    ("level", "Level", 90),
    ("games_played", "Games played", 100),
    ("elapsed_seconds", "Avg time", 92),
    ("hints", "Avg hints", 86),
    ("reveals", "Avg reveals", 96),
    ("incorrect", "Avg incorrect", 104),
    ("restarts", "Avg restarts", 104),
    ("abandons", "Avg abandons", 110),
    ("remaining_games", "Games remaining", 148),
)


def statistic_text(row: StatisticsRow, key: str) -> str:
    """Format counts, average durations, and decimal averages for one table cell."""
    if key == "level":
        return row.level
    value: int | float = getattr(row, key)
    if key in ("games_played", "remaining_games"):
        return f"{value:,}"
    average: float | None = row.average(value)
    if average is None:
        return "—"
    if key == "elapsed_seconds":
        return format_elapsed(round(average))
    return f"{average:.2f}"


class StatisticsDataSource(NSObject):
    """Serve seven summary rows and forward refresh and filter actions."""

    rows: list[StatisticsRow]
    reload_statistics: Callable[[], None]
    theme: Theme = DEFAULT_THEME

    def numberOfRowsInTableView_(self, table: Any) -> int:
        """Return the small summary size without reading individual history records."""
        return len(self.rows)

    def tableView_viewForTableColumn_row_(self, table: Any, column: Any, index: int) -> Any:
        """Align numbers to the right and distinguish the total using bold type."""
        row: StatisticsRow = self.rows[index]
        key: str = str(column.identifier())
        label: Any = AK.NSTextField.labelWithString_(statistic_text(row, key))
        label.setFont_(
            AK.NSFont.boldSystemFontOfSize_(12)
            if row.level == "Total"
            else AK.NSFont.systemFontOfSize_(12)
        )
        label.setTextColor_(self.theme.text)
        label.setAlignment_(AK.NSTextAlignmentLeft if key == "level" else AK.NSTextAlignmentRight)
        cell: Any = AK.NSTableCellView.alloc().initWithFrame_(
            AK.NSMakeRect(0, 0, column.width(), table.rowHeight())
        )
        height: float = label.intrinsicContentSize().height
        label.setFrame_(
            AK.NSMakeRect(6, (table.rowHeight() - height) / 2, column.width() - 12, height)
        )
        label.setAutoresizingMask_(AK.NSViewWidthSizable)
        cell.setTextField_(label)
        cell.addSubview_(label)
        return cell

    def tableView_rowViewForRow_(self, table: Any, row: int) -> Any:
        """Use the same rounded themed row surfaces as the History window."""
        view: Any = HistoryRowView.alloc().initWithFrame_(AK.NSZeroRect)
        view.row_index = row
        view.theme = self.theme
        return view

    def refreshStatistics_(self, sender: Any) -> None:
        """Reload summaries after a filter change or explicit Refresh click."""
        self.reload_statistics()


class StatisticsWindow:
    """Own a resizable per-level table, import filter, and explanatory captions."""

    def __init__(self, history: HistoryStore, players: PlayerStore) -> None:
        """Build the native summary window without loading its data until shown."""
        self.history: HistoryStore = history
        self.players: PlayerStore = players
        self.theme: Theme = DEFAULT_THEME
        self.window: Any = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 1040, 450),
            AK.NSWindowStyleMaskTitled
            | AK.NSWindowStyleMaskClosable
            | AK.NSWindowStyleMaskResizable,
            AK.NSBackingStoreBuffered,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setContentMinSize_((1040, 450))
        self.window.setTitle_("Statistics")
        self.window.center()
        content: Any = self.window.contentView()
        self.source: Any = StatisticsDataSource.alloc().init()
        self.source.rows = []
        self.source.reload_statistics = self.refresh
        self.status_label: Any = self.label("", AK.NSMakeRect(18, 409, 600, 20), top=True)
        self.include_imported: Any = AK.NSButton.checkboxWithTitle_target_action_(
            "Include imported games", self.source, "refreshStatistics:"
        )
        self.include_imported.setState_(AK.NSControlStateValueOff)
        self.include_imported.setFrame_(AK.NSMakeRect(680, 403, 220, 28))
        self.include_imported.setAutoresizingMask_(AK.NSViewMinXMargin | AK.NSViewMinYMargin)
        content.addSubview_(self.include_imported)
        self.refresh_button: Any = AK.NSButton.buttonWithTitle_target_action_(
            "Refresh", self.source, "refreshStatistics:"
        )
        self.refresh_button.setFrame_(AK.NSMakeRect(910, 402, 112, 30))
        self.refresh_button.setAutoresizingMask_(AK.NSViewMinXMargin | AK.NSViewMinYMargin)
        content.addSubview_(self.refresh_button)
        self.table: Any = self.build_table()
        self.description_label: Any = self.label(
            "Games played counts completed, restarted, and abandoned attempts. "
            "Averages use all included ended attempts; unfinished attempts are excluded.",
            AK.NSMakeRect(18, 62, 1004, 36),
        )
        self.description_label.setLineBreakMode_(AK.NSLineBreakByWordWrapping)
        self.description_label.cell().setWraps_(True)
        self.description_label.cell().setUsesSingleLineMode_(False)
        self.remaining_label: Any = self.label(
            "Avg restarts / abandons are fractions of attempts. "
            "Games remaining counts unused puzzles in the shared regular / daily rotation.",
            AK.NSMakeRect(18, 18, 1004, 36),
        )
        self.remaining_label.setLineBreakMode_(AK.NSLineBreakByWordWrapping)
        self.remaining_label.cell().setWraps_(True)
        self.remaining_label.cell().setUsesSingleLineMode_(False)

    def label(self, text: str, frame: Any, *, top: bool = False) -> Any:
        """Add a caption that follows its edge as the summary window resizes."""
        label: Any = AK.NSTextField.labelWithString_(text)
        label.setFont_(AK.NSFont.systemFontOfSize_(12))
        label.setFrame_(frame)
        label.setAutoresizingMask_(
            AK.NSViewWidthSizable | (AK.NSViewMinYMargin if top else AK.NSViewMaxYMargin)
        )
        self.window.contentView().addSubview_(label)
        return label

    def build_table(self) -> Any:
        """Show every requested column without horizontal scrolling at minimum size."""
        table: Any = AK.NSTableView.alloc().initWithFrame_(AK.NSZeroRect)
        table.setFocusRingType_(AK.NSFocusRingTypeNone)
        table.setRowHeight_(34)
        table.setStyle_(AK.NSTableViewStyleInset)
        table.setIntercellSpacing_((2, 2))
        table.setSelectionHighlightStyle_(AK.NSTableViewSelectionHighlightStyleNone)
        table.setAllowsColumnReordering_(False)
        table.setColumnAutoresizingStyle_(AK.NSTableViewLastColumnOnlyAutoresizingStyle)
        header: Any = HistoryHeaderView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 1004, 24))
        header.uses_native_header = False
        table.setHeaderView_(header)
        for key, title, width in COLUMNS:
            column: Any = AK.NSTableColumn.alloc().initWithIdentifier_(key)
            column.headerCell().setStringValue_(title)
            column.headerCell().setFont_(AK.NSFont.boldSystemFontOfSize_(13))
            column.headerCell().setAlignment_(
                AK.NSTextAlignmentLeft if key == "level" else AK.NSTextAlignmentRight
            )
            column.setWidth_(width)
            column.setMinWidth_(width)
            column.setMaxWidth_(float("inf") if key == "remaining_games" else width)
            column.setResizingMask_(AK.NSTableColumnAutoresizingMask)
            table.addTableColumn_(column)
        table.setDataSource_(self.source)
        table.setDelegate_(self.source)
        scroll: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSMakeRect(18, 104, 1004, 286))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setAutoresizingMask_(AK.NSViewWidthSizable | AK.NSViewHeightSizable)
        scroll.setDocumentView_(table)
        self.window.contentView().addSubview_(scroll)
        return table

    def apply_theme(self, theme: Theme, appearance: Any = None) -> None:
        """Refresh the window palette while retaining the selected import filter."""
        self.theme = theme
        self.window.setAppearance_(appearance)
        self.window.setBackgroundColor_(
            theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        self.source.theme = theme
        self.table.headerView().theme = theme
        self.table.setBackgroundColor_(theme.controls.background)
        self.table.enclosingScrollView().setBackgroundColor_(theme.controls.background)
        for label in (self.status_label, self.description_label, self.remaining_label):
            label.setTextColor_(theme.secondary_text)
        self.include_imported.setAttributedTitle_(button_title(self.include_imported, theme.text))
        apply_native_accent(self.include_imported, theme)
        apply_action_theme(self.refresh_button, theme)
        apply_native_accent(self.refresh_button, theme)
        self.table.reloadData()
        self.table.headerView().setNeedsDisplay_(True)

    def refresh(self) -> None:
        """Requery summaries and availability, showing storage errors without stale rows."""
        include_imported: bool = self.include_imported.state() == AK.NSControlStateValueOn
        try:
            self.source.rows = load_statistics(
                self.history, self.players, include_imported=include_imported
            )
        except SaveError as error:
            self.source.rows = []
            self.status_label.setStringValue_(str(error))
        else:
            count: int = self.source.rows[-1].games_played
            scope: str = "including" if include_imported else "excluding"
            self.status_label.setStringValue_(
                f"{count:,} recorded attempts · {scope} imported games"
            )
        self.table.reloadData()

    def show(self) -> None:
        """Refresh current measurements whenever the Statistics menu is opened."""
        self.refresh()
        self.window.makeKeyAndOrderFront_(None)
