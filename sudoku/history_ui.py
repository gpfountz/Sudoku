# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native, page-backed table for completed and ended Sudoku attempts."""

from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any

import AppKit as AK
import objc
from Foundation import NSDictionary, NSNotificationCenter, NSObject, NSString

from sudoku.controls import apply_action_theme, apply_native_accent
from sudoku.history import GameHistoryEntry, HistoryStore
from sudoku.storage import SaveError
from sudoku.theme import DEFAULT_THEME, Theme

PAGE_SIZE: int = 64
REPLAY_AREA_WIDTH: float = 118
REPLAY_BUTTON_WIDTH: float = 82
REPLAY_BUTTON_HEIGHT: float = 25
REPLAY_BUTTON_GAP: float = 11
COLUMNS: tuple[tuple[str, str, float], ...] = (
    ("ended_at", "Date & time", 160),
    ("puzzle_id", "Puzzle ID", 120),
    ("level", "Level", 65),
    ("elapsed_seconds", "Time", 63),
    ("hint_count", "Hints", 43),
    ("reveal_count", "Reveals", 55),
    ("incorrect_count", "Incorrect", 65),
    ("status", "Status", 77),
)


def format_elapsed(seconds: float) -> str:
    """Format a saved elapsed duration without losing hours."""
    total: int = int(seconds)
    hours: int = total // 3600
    minutes: int = total % 3600 // 60
    remainder: int = total % 60
    return f"{hours}:{minutes:02}:{remainder:02}" if hours else f"{minutes}:{remainder:02}"


def format_ended_at(timestamp: str | None) -> str:
    """Show an attempt's UTC end time in the Mac's local time zone."""
    if timestamp is None:
        return "Unknown"
    return datetime.fromisoformat(timestamp).astimezone().strftime("%b %d, %Y  %I:%M %p")


class HistoryRowView(AK.NSTableRowView):
    """Keep alternating fills and selection rounded within the data table."""

    row_index: int
    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def background_path(self) -> Any:
        """Inset the rounded row ends to match the native History list."""
        return AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AK.NSInsetRect(self.bounds(), 12, 0), 8, 8
        )

    def drawBackgroundInRect_(self, dirty_rect: Any) -> None:
        """Paint alternating system colors without extending into Replay actions."""
        self.theme.controls.background.setFill()
        AK.NSRectFill(self.bounds())
        if self.theme is DEFAULT_THEME:
            AK.NSColor.alternatingContentBackgroundColors()[self.row_index % 2].setFill()
        else:
            self.theme.board.peer_fill.base.colorWithAlphaComponent_(
                0.08 if self.row_index % 2 else 0
            ).setFill()
        self.background_path().fill()

    def drawSelectionInRect_(self, dirty_rect: Any) -> None:
        """Respect native active and inactive selection colors and rounded ends."""
        color: Any = (
            AK.NSColor.selectedContentBackgroundColor()
            if self.isEmphasized()
            else AK.NSColor.unemphasizedSelectedContentBackgroundColor()
        )
        if self.theme is not DEFAULT_THEME:
            color = self.theme.accent
        color.setFill()
        self.background_path().fill()


class HistoryHeaderView(AK.NSTableHeaderView):
    """End the native header divider after Status, before the Replay strip."""

    theme: Theme = DEFAULT_THEME
    uses_native_header: bool = True

    def drawRect_(self, dirty_rect: Any) -> None:
        """Clip native header painting to the width of the data table."""
        AK.NSGraphicsContext.saveGraphicsState()
        AK.NSRectClip(
            AK.NSMakeRect(0, 0, self.tableView().frame().size.width, self.bounds().size.height)
        )
        if self.theme is DEFAULT_THEME and self.uses_native_header:
            objc.super(HistoryHeaderView, self).drawRect_(dirty_rect)
        else:
            self.theme.controls.background.setFill()
            AK.NSRectFill(self.bounds())
            for index, column in enumerate(self.tableView().tableColumns()):
                paragraph: Any = AK.NSMutableParagraphStyle.alloc().init()
                paragraph.setAlignment_(column.headerCell().alignment())
                attributes: Any = NSDictionary.dictionaryWithDictionary_(
                    {
                        AK.NSFontAttributeName: column.headerCell().font(),
                        AK.NSForegroundColorAttributeName: self.theme.text,
                        AK.NSParagraphStyleAttributeName: paragraph,
                    }
                )
                title: Any = NSString.stringWithString_(column.headerCell().stringValue())
                title.drawInRect_withAttributes_(
                    AK.NSInsetRect(self.headerRectOfColumn_(index), 4, 3), attributes
                )
        self.theme.controls.border.setFill()
        AK.NSBezierPath.fillRect_(
            AK.NSMakeRect(0, self.bounds().size.height - 1, self.bounds().size.width, 1)
        )
        AK.NSGraphicsContext.restoreGraphicsState()


class HistoryDataSource(NSObject):
    """Serve visible AppKit rows from a small bounded page cache."""

    store: HistoryStore
    replay: Callable[[str], None]
    row_count: int
    pages: OrderedDict[int, list[GameHistoryEntry]]
    status_label: Any
    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def record_for_row(self, row: int) -> GameHistoryEntry | None:
        """Fetch at most one 64-row page and retain at most three pages."""
        if not 0 <= row < self.row_count:
            return None
        start: int = row // PAGE_SIZE * PAGE_SIZE
        if start not in self.pages:
            self.pages[start] = self.store.page(start, PAGE_SIZE)
            if len(self.pages) > 3:
                self.pages.popitem(last=False)
        else:
            self.pages.move_to_end(start)
        offset: int = row - start
        return self.pages[start][offset] if offset < len(self.pages[start]) else None

    def numberOfRowsInTableView_(self, table: Any) -> int:
        """Give AppKit the row count without reading their contents."""
        return self.row_count

    @objc.python_method
    def text_color(self, table: Any, row: int) -> Any:
        """Use contrasting selection ink for custom themes and native ink for Default."""
        if self.theme is not DEFAULT_THEME and table.isRowSelected_(row):
            return self.theme.controls.selected_text
        return self.theme.text

    def tableView_viewForTableColumn_row_(self, table: Any, column: Any, row: int) -> Any:
        """Construct one visible native text cell."""
        key: str = str(column.identifier())
        try:
            record: GameHistoryEntry | None = self.record_for_row(row)
        except SaveError as error:
            self.status_label.setStringValue_(str(error))
            record = None
        value: str = self.value_for_column(record, key)
        label: Any = AK.NSTextField.labelWithString_(value)
        label.setFont_(AK.NSFont.systemFontOfSize_(12))
        label.setLineBreakMode_(AK.NSLineBreakByTruncatingTail)
        label.setTextColor_(self.text_color(table, row))
        text_height: float = label.intrinsicContentSize().height
        cell: Any = AK.NSTableCellView.alloc().initWithFrame_(
            AK.NSMakeRect(0, 0, column.width(), table.rowHeight())
        )
        label.setFrame_(
            AK.NSMakeRect(4, (table.rowHeight() - text_height) / 2, column.width() - 8, text_height)
        )
        cell.setTextField_(label)
        cell.addSubview_(label)
        return cell

    def tableView_rowViewForRow_(self, table: Any, row: int) -> Any:
        """Provide a rounded native row using its alternating background index."""
        row_view: Any = HistoryRowView.alloc().initWithFrame_(AK.NSZeroRect)
        row_view.row_index = row
        row_view.theme = self.theme
        return row_view

    def tableViewSelectionDidChange_(self, notification: Any) -> None:
        """Refresh visible cell ink when selection moves to another themed row."""
        table: Any = notification.object()
        visible: Any = table.rowsInRect_(table.visibleRect())
        for row in range(visible.location, visible.location + visible.length):
            for column in range(table.numberOfColumns()):
                cell: Any = table.viewAtColumn_row_makeIfNecessary_(column, row, False)
                if cell is not None:
                    cell.textField().setTextColor_(self.text_color(table, row))

    @objc.python_method
    def replay_button(self, row: int) -> Any:
        """Create a separate action for the visible row's exact puzzle."""
        button: Any = AK.NSButton.buttonWithTitle_target_action_("Replay", self, "replayRow:")
        button.setBezelStyle_(AK.NSBezelStyleRounded)
        button.setTag_(row)
        button.setAccessibilityLabel_("Replay puzzle")
        apply_action_theme(button, self.theme)
        apply_native_accent(button, self.theme)
        try:
            button.setEnabled_(self.record_for_row(row) is not None)
        except SaveError as error:
            self.status_label.setStringValue_(str(error))
            button.setEnabled_(False)
        return button

    @objc.python_method
    def value_for_column(self, record: GameHistoryEntry | None, key: str) -> str:
        """Render one history entry without querying any additional rows."""
        if record is None:
            return "Unavailable"
        if key == "ended_at":
            return format_ended_at(record.ended_at)
        if key == "elapsed_seconds":
            return format_elapsed(record.elapsed_seconds)
        return str(getattr(record, key))

    def replayRow_(self, sender: Any) -> None:
        """Start a fresh attempt on the clicked row's exact puzzle."""
        try:
            record: GameHistoryEntry | None = self.record_for_row(int(sender.tag()))
        except SaveError as error:
            self.status_label.setStringValue_(str(error))
            return
        if record is not None:
            self.replay(record.puzzle_id)


class HistoryDocumentView(AK.NSView):
    """Scroll the data table and a bounded set of separate Replay buttons together."""

    table: Any
    source: HistoryDataSource
    replay_buttons: dict[int, Any]
    theme: Theme = DEFAULT_THEME

    def drawRect_(self, dirty_rect: Any) -> None:
        """Fill the Replay strip with the same surface as its surrounding window."""
        (self.theme.window_background or AK.NSColor.windowBackgroundColor()).setFill()
        AK.NSRectFill(dirty_rect)

    def isFlipped(self) -> bool:
        """Align the document's top edge with the native table rows."""
        return True

    def resizeSubviewsWithOldSize_(self, old_size: Any) -> None:
        """Keep the table and separate action strip aligned as the window resizes."""
        objc.super(HistoryDocumentView, self).resizeSubviewsWithOldSize_(old_size)
        if hasattr(self, "table"):
            self.table.setFrameSize_(
                (self.bounds().size.width - REPLAY_AREA_WIDTH, self.table.frame().size.height)
            )
            self.refresh_replay_buttons()
            self.table.headerView().setFrameSize_(
                (self.table.frame().size.width, self.table.headerView().frame().size.height)
            )
            self.table.headerView().setNeedsDisplay_(True)

    def clipBoundsChanged_(self, notification: Any) -> None:
        """Recycle action buttons when scrolling exposes different history rows."""
        self.refresh_replay_buttons()

    @objc.python_method
    def refresh_replay_buttons(self) -> None:
        """Keep only visible actions and position them beside their corresponding rows."""
        visible: Any = self.table.rowsInRect_(self.table.visibleRect())
        rows: set[int] = set(
            range(visible.location, min(visible.location + visible.length, self.source.row_count))
        )
        for row in self.replay_buttons.keys() - rows:
            self.replay_buttons.pop(row).removeFromSuperview()
        for row in sorted(rows):
            if row not in self.replay_buttons:
                self.replay_buttons[row] = self.source.replay_button(row)
                self.addSubview_(self.replay_buttons[row])
            rect: Any = self.convertRect_fromView_(self.table.rectOfRow_(row), self.table)
            self.replay_buttons[row].setFrame_(
                AK.NSMakeRect(
                    AK.NSMaxX(self.table.frame()) + REPLAY_BUTTON_GAP,
                    AK.NSMidY(rect) - REPLAY_BUTTON_HEIGHT / 2,
                    REPLAY_BUTTON_WIDTH,
                    REPLAY_BUTTON_HEIGHT,
                )
            )

    @objc.python_method
    def reload(self) -> None:
        """Refresh document height and actions after the underlying history changes."""
        for button in self.replay_buttons.values():
            button.removeFromSuperview()
        self.replay_buttons.clear()
        self.table.reloadData()
        self.setFrameSize_((self.frame().size.width, self.table.frame().size.height))
        self.refresh_replay_buttons()


class HistoryWindow:
    """Own a scrollable AppKit window and its bounded table data source."""

    def __init__(self, store: HistoryStore, replay: Callable[[str], None]) -> None:
        """Build the native table with a separate scrolling action strip."""
        self.theme: Theme = DEFAULT_THEME
        self.window: Any = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 980, 540),
            AK.NSWindowStyleMaskTitled
            | AK.NSWindowStyleMaskClosable
            | AK.NSWindowStyleMaskResizable,
            AK.NSBackingStoreBuffered,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setMinSize_((970, 370))
        self.window.setTitle_("History")
        self.window.center()
        content: Any = self.window.contentView()
        self.status_label: Any = AK.NSTextField.labelWithString_("")
        self.status_label.setFrame_(AK.NSMakeRect(18, 510, 944, 20))
        self.status_label.setFont_(AK.NSFont.systemFontOfSize_(12))
        self.status_label.setTextColor_(AK.NSColor.secondaryLabelColor())
        self.status_label.setAutoresizingMask_(AK.NSViewWidthSizable | AK.NSViewMinYMargin)
        content.addSubview_(self.status_label)
        self.table: Any = AK.NSTableView.alloc().initWithFrame_(AK.NSZeroRect)
        self.table.setFocusRingType_(AK.NSFocusRingTypeNone)
        self.table.setRowHeight_(30)
        self.table.setStyle_(AK.NSTableViewStyleInset)
        self.table.setUsesAlternatingRowBackgroundColors_(False)
        self.table.setHeaderView_(
            HistoryHeaderView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 826, 23))
        )
        self.table.setAllowsColumnReordering_(False)
        self.table.setColumnAutoresizingStyle_(AK.NSTableViewLastColumnOnlyAutoresizingStyle)
        for key, title, width in COLUMNS:
            column: Any = AK.NSTableColumn.alloc().initWithIdentifier_(key)
            column.headerCell().setStringValue_(title)
            column.setWidth_(width)
            column.setMinWidth_(width)
            column.setMaxWidth_(float("inf") if key == "status" else width)
            column.setResizingMask_(AK.NSTableColumnAutoresizingMask)
            self.table.addTableColumn_(column)
        self.source: Any = HistoryDataSource.alloc().init()
        self.source.store = store
        self.source.replay = replay
        self.source.row_count = 0
        self.source.pages = OrderedDict()
        self.source.status_label = self.status_label
        self.table.setDataSource_(self.source)
        self.table.setDelegate_(self.source)
        scroll: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSMakeRect(18, 18, 944, 457))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setAutoresizingMask_(AK.NSViewWidthSizable | AK.NSViewHeightSizable)
        self.document: Any = HistoryDocumentView.alloc().initWithFrame_(
            AK.NSMakeRect(0, 0, 944, 480)
        )
        self.document.table = self.table
        self.document.source = self.source
        self.document.replay_buttons = {}
        self.document.setAutoresizingMask_(AK.NSViewWidthSizable)
        self.table.setFrame_(AK.NSMakeRect(0, 0, 944 - REPLAY_AREA_WIDTH, 480))
        self.document.addSubview_(self.table)
        scroll.setDocumentView_(self.document)
        content.addSubview_(scroll)
        header: Any = self.table.headerView()
        header.setFrame_(AK.NSMakeRect(18, 475, 826, 23))
        header.setAutoresizingMask_(AK.NSViewMinYMargin)
        content.addSubview_(header)
        scroll.contentView().setPostsBoundsChangedNotifications_(True)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.document,
            "clipBoundsChanged:",
            AK.NSViewBoundsDidChangeNotification,
            scroll.contentView(),
        )

    def apply_theme(self, theme: Theme, appearance: Any = None) -> None:
        """Recolor existing rows and actions without resetting history, scrolling, or selection."""
        self.theme = theme
        self.window.setAppearance_(appearance)
        self.window.setBackgroundColor_(
            theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        self.status_label.setTextColor_(theme.secondary_text)
        self.source.theme = theme
        self.document.theme = theme
        self.table.headerView().theme = theme
        self.table.setBackgroundColor_(theme.controls.background)
        self.table.enclosingScrollView().setBackgroundColor_(theme.controls.background)
        for button in self.document.replay_buttons.values():
            apply_action_theme(button, theme)
            apply_native_accent(button, theme)
        selected: Any = self.table.selectedRowIndexes().copy()
        clip: Any = self.table.enclosingScrollView().contentView()
        origin: Any = clip.bounds().origin
        self.table.reloadData()
        self.table.selectRowIndexes_byExtendingSelection_(selected, False)
        clip.scrollToPoint_(origin)
        self.table.enclosingScrollView().reflectScrolledClipView_(clip)
        for view in (self.document, self.table, self.table.headerView()):
            view.setNeedsDisplay_(True)

    def show(self) -> None:
        """Refresh the count and bring the native list forward for keyboard navigation."""
        self.source.pages.clear()
        self.source.row_count = self.source.store.count()
        self.status_label.setStringValue_(f"{self.source.row_count} recorded games")
        self.document.reload()
        if self.source.row_count:
            self.table.selectRowIndexes_byExtendingSelection_(
                AK.NSIndexSet.indexSetWithIndex_(0), False
            )
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.table)
