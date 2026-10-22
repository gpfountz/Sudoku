# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise actual AppKit constraints and board coordinates without opening or saving windows."""

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import objc
import pytest
import Quartz as Q
from Foundation import NSProcessInfo, NSRunLoop, NSTimer

from scripts.preview_hint_links import preview_game, preview_hint
from sudoku.app import AppController
from sudoku.board import CandidateLayout, SudokuBoard, candidate_layout
from sudoku.compatibility import action_bezel_style
from sudoku.context_menu import CellContextMenu
from sudoku.controls import (
    GlassChoiceControl,
    ThemeFocusOutline,
    ThemeMenuRow,
    ThemePopUpButton,
    linear_rgb,
    native_accent_filter,
)
from sudoku.hint_types import HintLink, HintNode, candidate_link
from sudoku.hints import hint_steps
from sudoku.history import GameHistoryEntry, HistoryStore
from sudoku.history_ui import HistoryWindow
from sudoku.legal import COPYRIGHT_NOTICE, license_text, third_party_text
from sudoku.model import LEVELS, Game, Preferences, Snapshot
from sudoku.puzzle_import import ValidatedImport
from sudoku.storage import Store, game_data
from sudoku.theme import DEFAULT_THEME, THEMES, WARM_PAPER_THEME, theme_for_name
from sudoku.theme_names import THEME_NAMES
from sudoku.version import APP_VERSION

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1",
    reason="Native windows require a macOS WindowServer session; set RUN_NATIVE_LAYOUT_TESTS=1",
)


class LayoutPreviewWindow(AK.NSWindow):
    """Keep native layout tests independent of saved geometry and physical display size."""

    def setFrameUsingName_(self, name: str) -> bool:
        """Do not restore the user's window defaults."""
        return False

    def setFrameAutosaveName_(self, name: str) -> bool:
        """Do not write the user's window defaults."""
        return False

    def constrainFrameRect_toScreen_(self, frame: Any, screen: Any) -> Any:
        """Permit offscreen tests for external-display dimensions."""
        return frame


class LegacyInsetPopUpButton(AK.NSPopUpButton):
    """Model older AppKit padding outside a popup's Auto Layout alignment bounds."""

    def alignmentRectInsets(self) -> Any:
        """Reproduce the 54-by-52 frame surrounding a 40-point alignment rectangle."""
        return AK.NSEdgeInsetsMake(6, 7, 6, 7)


class LegacyRowMenu(AK.NSMenu):
    """Model shorter native text rows while preserving custom-view heights."""

    def size(self) -> Any:
        """Subtract two points per native text row from the modern menu metrics."""
        measured: Any = objc.super(LegacyRowMenu, self).size()
        native_rows: int = sum(item.view() is None for item in self.itemArray())
        return AK.NSMakeSize(measured.width, measured.height - 2 * native_rows)


def test_history_replay_buttons_sit_beside_the_table(
    tmp_path: Path,
    game: Game,
) -> None:
    """Keep Replay outside row backgrounds and replay the corresponding puzzle."""
    AK.NSApplication.sharedApplication()
    store: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    store.record_outcome(game, "Completed", "2026-09-25T19:39:00+00:00")
    replayed: list[str] = []
    history: HistoryWindow = HistoryWindow(store, replayed.append)
    try:
        history.show()
        scroll: Any = history.table.enclosingScrollView()
        status_column: int = history.table.numberOfColumns() - 1
        assert str(history.table.tableColumns()[status_column].identifier()) == "status"
        assert AK.NSMaxX(history.table.rectOfColumn_(status_column)) <= (
            scroll.contentView().bounds().size.width
        )
        assert not scroll.hasHorizontalScroller()
        assert scroll.documentView() == history.document
        assert history.table.headerView().superview() == history.window.contentView()
        button: Any = history.document.replay_buttons[0]
        assert button.superview() == history.document
        assert not AK.NSIntersectsRect(button.frame(), history.table.frame())
        assert AK.NSMidY(button.frame()) == pytest.approx(AK.NSMidY(history.table.rectOfRow_(0)))
        button.performClick_(None)
        assert replayed == [game.puzzle.identifier]
        for index in range(history.table.numberOfColumns()):
            column: Any = history.table.tableColumns()[index]
            cell: Any = history.source.tableView_viewForTableColumn_row_(history.table, column, 0)
            label: Any = cell.subviews()[0]
            assert label.frame().origin.y + label.frame().size.height / 2 == pytest.approx(
                history.table.rowHeight() / 2
            )
    finally:
        history.window.close()


@pytest.mark.parametrize("row_count", [0, 1, 130])
@pytest.mark.parametrize("scroller_style", [AK.NSScrollerStyleOverlay, AK.NSScrollerStyleLegacy])
def test_history_replay_actions_follow_scrolling_and_resizing(
    row_count: int, scroller_style: int
) -> None:
    """Keep visible actions aligned, bounded, and attached to the correct records."""
    AK.NSApplication.sharedApplication()
    records: list[GameHistoryEntry] = [
        GameHistoryEntry(
            str(row),
            "2026-10-02T19:33:00+00:00",
            "Completed",
            f"puzzle-{row}",
            "Medium",
            926,
            0,
            0,
            0,
            None,
        )
        for row in range(row_count)
    ]
    store: Any = Mock(spec=HistoryStore)
    store.count.return_value = row_count
    store.page.side_effect = lambda offset, limit: records[offset : offset + limit]
    replayed: list[str] = []
    history: HistoryWindow = HistoryWindow(store, replayed.append)
    try:
        history.show()
        scroll: Any = history.table.enclosingScrollView()
        scroll.setScrollerStyle_(scroller_style)
        for width, height in [(970, 370), (1280, 700), (980, 540)]:
            history.window.setContentSize_((width, height))
            history.window.contentView().layoutSubtreeIfNeeded()
            scroll.tile()
            assert AK.NSMaxX(history.table.rectOfColumn_(7)) <= history.table.bounds().size.width
            for target in (0, max(0, row_count - 1), 0):
                if row_count:
                    history.table.scrollRowToVisible_(target)
                visible: Any = history.table.rowsInRect_(history.table.visibleRect())
                expected: set[int] = set(
                    range(visible.location, min(visible.location + visible.length, row_count))
                )
                assert set(history.document.replay_buttons) == expected
                for row, button in history.document.replay_buttons.items():
                    assert button.tag() == row
                    assert not AK.NSIntersectsRect(button.frame(), history.table.frame())
                    assert AK.NSMidY(button.frame()) == pytest.approx(
                        AK.NSMidY(history.table.rectOfRow_(row))
                    )
                    assert AK.NSMaxX(button.frame()) <= scroll.contentView().bounds().size.width
                if row_count:
                    assert target in history.document.replay_buttons
                    history.document.replay_buttons[target].performClick_(None)
                    assert replayed[-1] == records[target].puzzle_id
                    assert len(history.document.replay_buttons) < 30
        store.count.return_value = 0
        history.show()
        assert not history.document.replay_buttons
    finally:
        history.window.close()


@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_history_rows_headers_and_replay_follow_every_theme(
    tmp_path: Path, game: Game, appearance: str
) -> None:
    """Render every history palette and retain selection, row text, and Replay actions."""
    AK.NSApplication.sharedApplication()
    store: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    store.record_outcome(game, "Completed", "2026-10-15T12:00:00+00:00")
    replayed: list[str] = []
    history: HistoryWindow = HistoryWindow(store, replayed.append)
    history.show()
    try:
        for name in THEME_NAMES:
            theme: Any = theme_for_name(name)
            history.apply_theme(theme, AK.NSAppearance.appearanceNamed_(appearance))
            assert history.table.selectedRow() == 0
            assert history.table.backgroundColor().isEqual_(theme.controls.background)
            assert history.status_label.textColor().isEqual_(theme.secondary_text)
            assert history.table.headerView().theme is theme
            row: Any = history.table.rowViewAtRow_makeIfNecessary_(0, True)
            assert row.theme is theme
            for view in (history.window.contentView(), history.table.headerView(), row):
                bitmap: Any = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
                view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
                assert bitmap.pixelsWide() > 0 and bitmap.pixelsHigh() > 0
            cell: Any = history.table.viewAtColumn_row_makeIfNecessary_(0, 0, True)
            assert (
                cell.textField().textColor().isEqual_(history.source.text_color(history.table, 0))
            )
            history.table.deselectAll_(None)
            assert cell.textField().textColor().isEqual_(theme.text)
            history.table.selectRowIndexes_byExtendingSelection_(
                AK.NSIndexSet.indexSetWithIndex_(0), False
            )
            button: Any = history.document.replay_buttons[0]
            assert button.target() is history.source and button.action() == "replayRow:"
            button.performClick_(None)
            assert replayed[-1] == game.puzzle.identifier
        assert len(replayed) == len(THEME_NAMES)
    finally:
        history.window.close()


@pytest.fixture
def native_controller(
    game: Game, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[Any]:
    """Exercise native and older-OS controls without startup or player-data writes."""
    if getattr(request, "param", False):
        monkeypatch.setattr("sudoku.compatibility.supports_glass_buttons", lambda: False)
    if getattr(request, "param", None) == "legacy-popup-insets":
        monkeypatch.setattr(AK, "NSPopUpButton", LegacyInsetPopUpButton)
    if getattr(request, "param", None) == "legacy-menu-rows":
        monkeypatch.setattr(AK, "NSMenu", LegacyRowMenu)
    with objc.autorelease_pool():
        AK.NSApplication.sharedApplication()
        monkeypatch.setattr(AK, "NSWindow", LayoutPreviewWindow)
        controller: Any = AppController.alloc().init()
        controller.game = game
        controller.preferences = Preferences()
        controller.controls = {}
        controller.settings_window = None
        controller.hint_focus = set()
        controller.hint_removals = set()
        controller.hint_candidates = set()
        controller.hint_placements = set()
        controller.hint_links = ()
        controller.build_window()
        try:
            yield controller
        finally:
            controller.window.setDelegate_(None)
            controller.window.close()
            controller.board.controller = None


@pytest.mark.parametrize("window_kind", ("history", "import"))
@pytest.mark.parametrize("appearance", ("Light", "Dark", "System"))
def test_auxiliary_windows_follow_theme_on_open_and_live_changes(
    native_controller: Any, tmp_path: Path, window_kind: str, appearance: str
) -> None:
    """Propagate themes and appearance to both auxiliary windows without resetting their data."""
    controller: Any = native_controller
    controller.history_window = None
    controller.import_window = None
    controller.history = HistoryStore(tmp_path / "history.sqlite3")
    controller.store = Store(tmp_path)
    controller.preferences.appearance = appearance
    controller.theme = WARM_PAPER_THEME
    controller.apply_appearance()
    before: dict[str, Any] = game_data(controller.game)
    auxiliary: Any = None
    try:
        if window_kind == "history":
            controller.history.record_outcome(
                controller.game, "Completed", "2026-10-15T12:00:00+00:00"
            )
            controller.history_(None)
            auxiliary = controller.history_window
        else:
            controller.importPuzzle_(None)
            auxiliary = controller.import_window
            auxiliary.values[0] = 5
            auxiliary.uncertain = {0}
            auxiliary.select_difficulty("Expert")
        assert auxiliary.theme is WARM_PAPER_THEME
        assert auxiliary.window.appearance() == controller.window.appearance()
        assert auxiliary.window.backgroundColor().isEqual_(WARM_PAPER_THEME.window_background)
        for name in ("Default Orchid", "High Contrast", "Default"):
            controller.theme = theme_for_name(name)
            controller.preferences.appearance = "Dark" if name != "Default" else "System"
            controller.apply_appearance()
            assert auxiliary.theme is controller.theme
            assert auxiliary.window.appearance() == controller.window.appearance()
            assert auxiliary.window.backgroundColor().isEqual_(
                controller.theme.window_background or AK.NSColor.windowBackgroundColor()
            )
            if window_kind == "history":
                assert auxiliary.source.theme is controller.theme
                assert auxiliary.source.row_count == 1
                assert auxiliary.table.selectedRow() == 0
                assert (
                    auxiliary.source.record_for_row(0).puzzle_id
                    == controller.game.puzzle.identifier
                )
            else:
                assert auxiliary.controls["regions"].theme is controller.theme
                assert auxiliary.values[0] == 5 and auxiliary.uncertain == {0}
                assert auxiliary.difficulty == "Expert"
        assert game_data(controller.game) == before
    finally:
        if auxiliary is not None:
            if window_kind == "import":
                auxiliary.close()
            else:
                auxiliary.window.close()


@pytest.mark.parametrize("appearance", ["Light", "Dark"])
def test_native_hint_links_keep_solid_and_dotted_styles(
    native_controller: Any, monkeypatch: pytest.MonkeyPatch, appearance: str
) -> None:
    """Render every proof edge, including the short diagonal inside r4c3."""
    controller: Any = native_controller
    controller.game = preview_game()
    controller.preferences.appearance = appearance
    controller.apply_appearance()
    step = hint_steps(controller.game, preview_hint(controller.game))[1]
    controller.hint_links = step.links
    controller.hint_candidates = set(step.candidates)
    controller.hint_focus = set(step.focus)
    original: Any = AK.NSBezierPath
    paths: list[Mock] = []

    def make_path() -> Mock:
        """Spy on real native paths while preserving actual drawing behavior."""
        path: Mock = Mock(wraps=original.bezierPath())
        paths.append(path)
        return path

    factory: Mock = Mock(wraps=original)
    factory.bezierPath.side_effect = make_path
    monkeypatch.setattr(AK, "NSBezierPath", factory)
    board: Any = controller.board
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    link_paths: list[Mock] = paths[:7]
    assert len(link_paths) == 7
    assert sum(path.setLineDash_count_phase_.called for path in link_paths) == 4
    assert all(
        path.setLineCapStyle_.call_args.args == (AK.NSRoundLineCapStyle,) for path in link_paths
    )
    assert all(path.stroke.called for path in link_paths)
    assert any(path.curveToPoint_controlPoint1_controlPoint2_.called for path in link_paths)


def test_hint_diagram_tracks_back_dismissal_and_missing_notes(native_controller: Any) -> None:
    """Update link state through actual controller navigation without storing anything."""
    controller: Any = native_controller
    controller.game = preview_game()
    controller.current_hint = preview_hint(controller.game)
    controller.hint_stage = 2
    controller.save = Mock()
    controller.refresh = Mock()
    controller.game.notes[49].discard(9)
    before: object = controller.game.snapshot()
    controller.present_hint()
    assert controller.hint_links == controller.current_hint.links
    board: Any = controller.board
    board.draw_text = Mock(wraps=board.draw_text)
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    layout: CandidateLayout = candidate_layout(board.cell_rect(0).size.width)
    assert any(
        call.args[0] == "9" and call.args[1] == layout.digit_rect(board.cell_rect(49), 9)
        for call in board.draw_text.call_args_list
    )
    assert controller.game.snapshot() == before
    controller.previousHint_(None)
    assert not controller.hint_links and not controller.hint_candidates
    controller.hint_stage = 3
    controller.present_hint()
    assert controller.hint_links and controller.hint_removals == {(29, 2)}
    controller.clear_hint()
    assert not controller.hint_links and not controller.hint_candidates


def test_overlapping_link_styles_and_group_bounds_remain_distinct(native_controller: Any) -> None:
    """Separate dual-strength edges and keep nested group links visible inside the board."""
    board: Any = native_controller.board
    layout: CandidateLayout = candidate_layout(board.cell_rect(0).size.width)
    scale: float = (board.bounds().size.width - 2) / 588
    strong: Any = board.hint_link_path(candidate_link((29, 4), (31, 4), True), layout, scale, True)
    weak: Any = board.hint_link_path(candidate_link((31, 4), (29, 4), False), layout, scale, True)
    assert strong.bounds().origin.y != weak.bounds().origin.y
    grouped: HintLink = HintLink(HintNode((0, 2), 1), HintNode((1,), 1), True)
    grouped_path: Any = board.hint_link_path(grouped, layout, scale, False)
    assert grouped_path.elementCount() == 2
    assert AK.NSMinY(grouped_path.bounds()) >= 0
    assert AK.NSMaxX(grouped_path.bounds()) <= board.bounds().size.width


def contains(parent: Any, child: Any) -> bool:
    """Allow half-point rounding while checking a descendant's actual native frame."""
    rect: Any = parent.convertRect_fromView_(
        child.alignmentRectForFrame_(child.frame()), child.superview()
    )
    bounds: Any = parent.bounds()
    return (
        rect.origin.x >= bounds.origin.x - 0.5
        and rect.origin.y >= bounds.origin.y - 0.5
        and AK.NSMaxX(rect) <= AK.NSMaxX(bounds) + 0.5
        and AK.NSMaxY(rect) <= AK.NSMaxY(bounds) + 0.5
    )


def test_theme_swap_updates_custom_views_without_changing_appearance(
    native_controller: Any,
) -> None:
    """Programmatic themes reach the board, keypad, and menu without changing mode."""
    controller: Any = native_controller
    names: tuple[str, ...] = tuple(f"Shade {index}" for index in range(1, 9))
    theme: Any = replace(
        DEFAULT_THEME,
        text=AK.NSColor.systemPurpleColor(),
        annotations=replace(DEFAULT_THEME.annotations, names=names),
    )
    original_appearance: Any = controller.window.appearance()
    controller.game.color_mode = True
    controller.game.active_color = 1

    controller.apply_theme(theme)
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    menu: Any = context.build_menu()

    assert controller.theme is theme
    assert controller.board.controller.theme is theme
    assert all(controller.controls[f"digit{digit}"].theme is theme for digit in range(1, 10))
    assert menu.itemWithTitle_("Answer").submenu().itemAtIndex_(0).view().theme is theme
    palette: Any = menu.itemWithTitle_("Color").submenu().itemAtIndex_(0).view()
    assert all(tile.theme is theme for tile in palette.subviews())
    first_tile: Any = next(tile for tile in palette.subviews() if tile.tag() == 1)
    assert first_tile.toolTip() == "Shade 1"
    assert controller.controls["palette_label"].stringValue() == "Color  Shade 1"
    assert controller.controls["digit1"].accessibilityLabel() == "Color Shade 1"
    assert controller.controls["hint_text"].textColor().isEqual_(theme.secondary_text)
    assert controller.window.appearance() == original_appearance
    assert controller.preferences.appearance == "System"


def test_theme_setting_fits_and_recolors_window(native_controller: Any) -> None:
    """Expose every theme in Settings and recolor without changing appearance."""
    controller: Any = native_controller
    controller.settings_controls = {}
    controller.build_settings()
    try:
        picker: Any = controller.settings_controls["theme"]
        assert tuple(
            picker.itemTitleAtIndex_(index) for index in range(picker.numberOfItems())
        ) == (THEME_NAMES)
        assert contains(controller.settings_window.contentView(), picker)
        appearance: Any = controller.window.appearance()
        controller.apply_theme(WARM_PAPER_THEME)
        assert controller.window.backgroundColor().isEqual_(WARM_PAPER_THEME.window_background)
        assert controller.controls["digit1"].theme is WARM_PAPER_THEME
        for key in ("order", "mode"):
            assert (
                controller.controls[key]
                .selectedSegmentBezelColor()
                .isEqual_(WARM_PAPER_THEME.accent)
            )
        assert controller.window.appearance() == appearance
        controller.apply_theme(DEFAULT_THEME)
        assert controller.window.backgroundColor().isEqual_(AK.NSColor.windowBackgroundColor())
        for key in ("order", "mode"):
            assert (
                controller.controls[key].selectedSegmentBezelColor().isEqual_(DEFAULT_THEME.accent)
            )
    finally:
        controller.settings_window.close()


@pytest.mark.parametrize("name", THEME_NAMES[1:])
@pytest.mark.parametrize("native_controller", [False, True], indirect=True)
def test_named_themes_reach_settings_menus_dialogs_and_choice_text(
    native_controller: Any, name: str
) -> None:
    """Keep native actions and full game state intact while recoloring every theme surface."""
    controller: Any = native_controller
    controller.regular_game = controller.game
    controller.active_daily_date = None
    controller.settings_controls = {}
    controller.build_settings()
    controller.game.set_value(1, 2)
    controller.game.mark(2, 3)
    controller.game.paint_color(2)
    before: dict[str, Any] = game_data(controller.game)
    theme: Any = theme_for_name(name)
    controller.apply_theme(theme)
    alert: Any = controller.build_new_game_dialog()
    try:
        for key in ("order", "mode"):
            choices: Any = controller.controls[key]
            for selected in range(len(choices.choice_buttons)):
                choices.setSelectedSegment_(selected)
                for index, button in enumerate(choices.choice_buttons):
                    text: Any = button.attributedTitle().attribute_atIndex_effectiveRange_(
                        AK.NSForegroundColorAttributeName, 0, None
                    )[0]
                    expected: Any = (
                        theme.controls.selected_text if index == selected else theme.text
                    )
                    assert text.isEqual_(expected)
                    assert button.target() == choices and button.action() == "segmentPressed:"
                    assert button.bezelStyle() == action_bezel_style(theme.high_contrast)
        assert controller.controls["digit1"].theme is theme
        for key in ("appearance", "theme", "error_check", "daily_minimum", "daily_maximum"):
            popup: Any = controller.settings_controls[key]
            assert popup.theme is theme
            assert all(item.view().theme is theme for item in popup.itemArray())
        assert alert.accessoryView().theme is theme
        assert alert.buttons()[0].bezelColor() is None
        assert alert.buttons()[0].layer().filters()
        primary_text: Any = (
            alert.buttons()[0]
            .attributedTitle()
            .attribute_atIndex_effectiveRange_(AK.NSForegroundColorAttributeName, 0, None)[0]
        )
        assert primary_text.isEqual_(theme.controls.selected_text)
        context: Any = CellContextMenu.alloc().init()
        context.configure(controller.board, 2)
        menu: Any = context.build_menu()
        assert menu.itemWithTitle_("Candidate").submenu().itemAtIndex_(0).view().theme is theme
        controller.apply_theme(DEFAULT_THEME)
        assert all(
            button.bezelStyle() == action_bezel_style()
            for button in controller.controls["mode"].choice_buttons
        )
        assert game_data(controller.game) == before
    finally:
        alert.window().close()
        controller.settings_window.close()


def test_high_contrast_board_adds_non_color_cues_without_editing_game(
    native_controller: Any,
) -> None:
    """Underline entered answers and outline matches, retaining the same values and notes."""
    controller: Any = native_controller
    controller.game.set_value(1, 2)
    controller.game.mark(2, 2)
    controller.game.active_digit = 2
    controller.game.note_mode = True
    controller.apply_theme(THEMES["High Contrast"])
    board: Any = controller.board
    board.draw_text = Mock()
    board.draw_match_outline = Mock()
    before: dict[str, Any] = game_data(controller.game)
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    assert any(call.kwargs.get("underline") is True for call in board.draw_text.call_args_list)
    assert any(call.kwargs.get("underline") is False for call in board.draw_text.call_args_list)
    assert any(
        call.args[0] == board.cell_rect(1) and not call.kwargs.get("candidate")
        for call in board.draw_match_outline.call_args_list
    )
    assert any(call.kwargs.get("candidate") for call in board.draw_match_outline.call_args_list)
    assert game_data(controller.game) == before


@pytest.mark.parametrize("name", THEME_NAMES)
@pytest.mark.parametrize("appearance", ("Light", "Dark"))
def test_board_draws_invalid_answers_with_palette_error_color(
    native_controller: Any, name: str, appearance: str
) -> None:
    """Use the theme's error ink for both the wrong answer and its circled X."""
    controller: Any = native_controller
    controller.preferences.error_check = "Against Solution"
    controller.preferences.appearance = appearance
    controller.apply_appearance()
    index: int = next(i for i, value in enumerate(controller.game.values) if not value)
    wrong: int = controller.game.puzzle.solution[index] % 9 + 1
    controller.game.set_value(index, wrong)
    controller.game.active_digit = wrong
    controller.apply_theme(theme_for_name(name))
    before: dict[str, Any] = game_data(controller.game)
    board: Any = controller.board
    board.draw_text = Mock()
    board.draw_error_marker = Mock()
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    calls: list[Any] = [
        call for call in board.draw_text.call_args_list if call.args[1] == board.cell_rect(index)
    ]
    assert calls
    assert all(call.args[3].isEqual_(controller.theme.hints.error_text) for call in calls)
    assert board.draw_error_marker.called
    assert all(
        marker.args[0] == board.cell_rect(index)
        and marker.args[1].isEqual_(controller.theme.hints.error_text)
        and marker.args[2]
        == pytest.approx(
            (1.6 if controller.theme.high_contrast else 1.25)
            * (board.bounds().size.width - 2)
            / 588
        )
        for marker in board.draw_error_marker.call_args_list
    )
    assert game_data(controller.game) == before


@pytest.mark.parametrize("width", (272, 590, 902))
@pytest.mark.parametrize(
    ("error_check", "paused"),
    (
        ("Off", False),
        ("Rule Conflicts", False),
        ("Against Solution", False),
        ("Against Solution", True),
    ),
)
def test_error_markers_follow_checking_policy_pause_and_board_size(
    native_controller: Any, width: int, error_check: str, paused: bool
) -> None:
    """Scale answer markers, hide them while paused, and respect optional error checking."""
    controller: Any = native_controller
    controller.game.set_value(1, 1)
    controller.game.set_value(2, controller.game.puzzle.solution[2])
    controller.game.paused = paused
    controller.preferences.error_check = error_check
    board: Any = SudokuBoard.alloc().initWithFrame_(AK.NSMakeRect(0, 0, width, width))
    board.controller = controller
    controller.window.contentView().addSubview_(board)
    board.draw_error_marker = Mock()
    before: dict[str, Any] = game_data(controller.game)
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    expected: set[int] = set() if paused else controller.game.errors(error_check)
    assert {
        index
        for index in range(81)
        if any(
            call.args[0] == board.cell_rect(index)
            for call in board.draw_error_marker.call_args_list
        )
    } == expected
    assert all(
        call.args[2] == pytest.approx(1.25 * (width - 2) / 588)
        for call in board.draw_error_marker.call_args_list
    )
    assert game_data(controller.game) == before
    board.removeFromSuperview()
    board.controller = None


def test_hint_removals_share_the_answer_error_marker(native_controller: Any) -> None:
    """Mark proposed removals in red while retaining readable candidate ink."""
    controller: Any = native_controller
    controller.game.mark(1, 4)
    controller.hint_removals = {(1, 4), (2, 5)}
    controller.hint_candidates = {(1, 4)}
    board: Any = controller.board
    board.draw_text = Mock(wraps=board.draw_text)
    board.draw_error_marker = Mock()
    before: dict[str, Any] = game_data(controller.game)
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    assert board.draw_error_marker.called
    assert len({call.args[0].origin.x for call in board.draw_error_marker.call_args_list}) == 2
    removed_digit_rect: Any = candidate_layout(board.cell_rect(1).size.width).digit_rect(
        board.cell_rect(1), 4
    )
    assert any(
        call.args[0] == "4"
        and call.args[1] == removed_digit_rect
        and call.args[3].isEqual_(controller.theme.text)
        for call in board.draw_text.call_args_list
    )
    for call in board.draw_error_marker.call_args_list:
        cell_width: float = board.cell_rect(1).size.width
        assert 0.30 * cell_width < 0.76 * call.args[0].size.width < 0.33 * cell_width
        assert call.args[1].isEqual_(controller.theme.hints.removal_stroke)
        assert call.args[2] == pytest.approx(0.95 * (board.bounds().size.width - 2) / 588)
    assert game_data(controller.game) == before


@pytest.mark.parametrize("cell_size", (30.0, 588 / 9, 100.0))
def test_candidate_spacing_balances_ink_gaps_at_every_size(cell_size: float) -> None:
    """Give the complete digit grid four equal clear gaps along each axis."""
    AK.NSApplication.sharedApplication()
    cell: Any = AK.NSMakeRect(11, 17, cell_size, cell_size)
    layout: CandidateLayout = candidate_layout(cell_size)
    assert layout.font_size == pytest.approx(cell_size * 0.25)
    for digits, extent, origin, ink_size, midpoint in (
        ((1, 2, 3), cell_size, cell.origin.x, layout.ink_width, AK.NSMidX),
        ((1, 4, 7), cell_size, cell.origin.y, layout.ink_height, AK.NSMidY),
    ):
        centers: list[float] = [midpoint(layout.digit_rect(cell, digit)) for digit in digits]
        gaps: list[float] = [
            centers[0] - ink_size / 2 - origin,
            centers[1] - centers[0] - ink_size,
            centers[2] - centers[1] - ink_size,
            origin + extent - centers[2] - ink_size / 2,
        ]
        assert gaps[0] > 0
        assert gaps == pytest.approx([gaps[0]] * 4)
        assert centers[1] == pytest.approx(origin + extent / 2)
    for digit in range(1, 10):
        assert AK.NSContainsRect(cell, layout.digit_rect(cell, digit))


@pytest.mark.parametrize("cell_size", (30.0, 588 / 9, 100.0))
@pytest.mark.parametrize("digit", (2, 5, 8))
def test_rendered_candidate_ink_is_centered_in_its_highlight(cell_size: float, digit: int) -> None:
    """Keep the actual rasterized numeral centered, including the flipped text baseline."""
    AK.NSApplication.sharedApplication()
    cell: Any = AK.NSMakeRect(0, 0, cell_size, cell_size)
    layout: CandidateLayout = candidate_layout(cell_size)
    rect: Any = layout.digit_rect(cell, digit)
    board: Any = SudokuBoard.alloc().initWithFrame_(cell)
    image: Any = AK.NSImage.alloc().initWithSize_((cell_size, cell_size))
    image.lockFocusFlipped_(True)
    try:
        AK.NSColor.whiteColor().setFill()
        AK.NSRectFill(cell)
        board.draw_text(
            str(digit),
            rect,
            layout.font_size,
            AK.NSColor.blackColor(),
            AK.NSFontWeightBold,
            candidate=layout,
        )
    finally:
        image.unlockFocus()
    bitmap: Any = AK.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    scale_x: float = bitmap.pixelsWide() / cell_size
    scale_y: float = bitmap.pixelsHigh() / cell_size
    pixels: list[tuple[int, int]] = [
        (x, y)
        for y in range(bitmap.pixelsHigh())
        for x in range(bitmap.pixelsWide())
        if bitmap.colorAtX_y_(x, y).brightnessComponent() < 0.5
    ]
    assert pixels
    center_x: float = (min(x for x, _ in pixels) + max(x for x, _ in pixels) + 1) / 2 / scale_x
    center_y: float = (min(y for _, y in pixels) + max(y for _, y in pixels) + 1) / 2 / scale_y
    assert center_x == pytest.approx(AK.NSMidX(rect), abs=1)
    assert center_y == pytest.approx(AK.NSMidY(rect), abs=1)


def test_sparse_candidates_and_hint_marks_keep_their_fixed_positions(
    native_controller: Any,
) -> None:
    """Center sparse notes and annotations in the same slots as a complete candidate grid."""
    controller: Any = native_controller
    controller.preferences.highlight_digits = True
    for digit in range(1, 10):
        controller.game.mark(1, digit)
    for digit in (2, 5, 8):
        controller.game.mark(2, digit)
    controller.game.active_digit = 2
    controller.hint_removals = {(2, 3)}
    controller.hint_placements = {(2, 9)}
    controller.hint_candidates = {(1, 9)}
    controller.apply_theme(THEMES["High Contrast"])
    board: Any = controller.board
    board.draw_text = Mock(wraps=board.draw_text)
    board.draw_error_marker = Mock(wraps=board.draw_error_marker)
    board.draw_match_outline = Mock(wraps=board.draw_match_outline)
    before: dict[str, Any] = game_data(controller.game)
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())
    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)
    layout: CandidateLayout = candidate_layout(board.cell_rect(1).size.width)
    for index, digits in ((1, range(1, 10)), (2, (2, 3, 5, 8, 9))):
        for digit in digits:
            rect: Any = layout.digit_rect(board.cell_rect(index), digit)
            assert any(
                call.args[0] == str(digit)
                and call.args[1] == rect
                and call.args[2] == layout.font_size
                and call.args[4] == AK.NSFontWeightBold
                and call.kwargs.get("candidate") is layout
                for call in board.draw_text.call_args_list
            )
    removal_rect: Any = layout.digit_rect(board.cell_rect(2), 3)
    assert all(
        AK.NSMidX(call.args[0]) == pytest.approx(AK.NSMidX(removal_rect))
        and AK.NSMidY(call.args[0]) == pytest.approx(AK.NSMidY(removal_rect))
        and AK.NSContainsRect(call.args[0], removal_rect)
        for call in board.draw_error_marker.call_args_list
    )
    highlight_rect: Any = layout.digit_rect(board.cell_rect(2), 2)
    assert any(
        AK.NSContainsRect(call.args[0], highlight_rect)
        and call.args[0].size.width > highlight_rect.size.width
        and AK.NSMidX(call.args[0]) == pytest.approx(AK.NSMidX(highlight_rect))
        and AK.NSMidY(call.args[0]) == pytest.approx(AK.NSMidY(highlight_rect))
        and call.kwargs.get("candidate") is True
        for call in board.draw_match_outline.call_args_list
    )
    assert game_data(controller.game) == before


@pytest.mark.parametrize("native_controller", [False, True, "legacy-popup-insets"], indirect=True)
def test_supported_styles_cover_actions_and_mode_controls(native_controller: Any) -> None:
    """Use supported styles for actions, entry modes, and the compact menu."""
    controller: Any = native_controller
    expected_style: int = action_bezel_style()
    for key in (
        "new",
        "daily",
        "import",
        "restart",
        "pause",
        "undo",
        "redo",
        "erase",
        "fill",
        "auto_complete",
        "previous_hint",
        "hint",
        "apply_hint",
        "another_hint",
        "reveal",
    ):
        assert controller.controls[key].bezelStyle() == expected_style
    for key in ("order", "mode"):
        choices: Any = controller.controls[key]
        assert isinstance(choices, GlassChoiceControl)
        assert len(choices.choice_buttons) == (2 if key == "order" else 3)
        assert all(button.bezelStyle() == expected_style for button in choices.choice_buttons)
        assert all(contains(choices, button) for button in choices.choice_buttons)
        choices.setSelectedSegment_(0)
        assert (
            sum(button.state() == AK.NSControlStateValueOn for button in choices.choice_buttons)
            == 1
        )
        choices.setEnabled_(False)
        assert not choices.isEnabled()
        assert all(not button.isEnabled() for button in choices.choice_buttons)
        choices.setEnabled_(True)
    compact_menu: Any = controller.adaptive_layout.compact_menu
    assert compact_menu.bezelStyle() == expected_style
    # Auto Layout sizes the alignment rectangle; native bezel margins can enlarge the frame.
    alignment: Any = compact_menu.alignmentRectForFrame_(compact_menu.frame())
    assert alignment.size.width == alignment.size.height == 40
    assert compact_menu.intrinsicContentSize().height <= compact_menu.frame().size.height
    assert all(
        controller.controls[f"digit{digit}"].bezelStyle() != getattr(AK, "NSBezelStyleGlass", -1)
        for digit in range(1, 10)
    )


def test_settings_use_native_switches(native_controller: Any) -> None:
    """Every binary preference stays labeled and uses a standard macOS switch."""
    controller: Any = native_controller
    controller.settings_controls = {}
    controller.build_settings()
    try:
        content: Any = controller.settings_window.contentView()
        for key in (
            "highlight_digits",
            "dim_completed_digits",
            "highlight_peers",
            "drag_answers_as_candidates",
            "cleanup_notes",
            "show_timer",
            "daily_enabled",
        ):
            toggle: Any = controller.settings_controls[key]
            label: Any = controller.settings_controls[f"{key}_label"]
            assert isinstance(toggle, AK.NSSwitch)
            assert toggle.identifier() == key
            assert toggle.target() == controller
            assert toggle.action() == "preferenceChanged:"
            assert toggle.accessibilityLabel() == label.stringValue()
            assert contains(content, toggle)
            assert contains(content, label)
    finally:
        controller.settings_window.close()


@pytest.mark.parametrize("appearance", ["Light", "Dark"])
def test_settings_theme_changes_preserve_native_preferences(
    native_controller: Any, appearance: str
) -> None:
    """Theme settings tint switches and focus without changing other saved preferences."""
    controller: Any = native_controller
    controller.preferences.appearance = appearance
    controller.settings_controls = {}
    controller.save = Mock()
    controller.refresh = Mock()
    controller.build_settings()
    before_preferences: Preferences = replace(controller.preferences)
    before_game: object = controller.game.snapshot()
    toggle: Any = controller.settings_controls["highlight_digits"]
    toggle.setState_(AK.NSControlStateValueOn)
    picker: Any = controller.settings_controls["theme"]
    try:
        picker.selectItemWithTitle_("Warm Paper")
        controller.preferenceChanged_(picker)
        assert controller.settings_window.backgroundColor().isEqual_(
            WARM_PAPER_THEME.window_background
        )
        assert toggle.layer().filters()
        assert toggle.state() == AK.NSControlStateValueOn
        assert controller.settings_controls["appearance"].focusRingType() == AK.NSFocusRingTypeNone
        assert controller.preferences == replace(before_preferences, theme="Warm Paper")

        toggle.setState_(AK.NSControlStateValueOff)
        controller.preferenceChanged_(toggle)
        assert not controller.preferences.highlight_digits
        assert toggle.layer().filters()

        picker.selectItemWithTitle_("Default")
        controller.preferenceChanged_(picker)
        assert controller.settings_window.backgroundColor().isEqual_(
            AK.NSColor.windowBackgroundColor()
        )
        assert not toggle.layer().filters()
        assert controller.settings_controls["appearance"].focusRingType() == (
            AK.NSFocusRingTypeDefault
        )
        assert controller.preferences == replace(before_preferences, highlight_digits=False)
        assert controller.game.snapshot() == before_game
        assert controller.save.call_count == 3
    finally:
        controller.settings_window.close()


@pytest.mark.parametrize("appearance", [AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua])
def test_native_accent_tint_preserves_neutral_switch_details(appearance: str) -> None:
    """Tint native accent pixels in linear RGB while retaining white and gray switch details."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
        color_filter: Any = native_accent_filter(WARM_PAPER_THEME.accent)
        source: tuple[float, ...] = linear_rgb(AK.NSColor.controlAccentColor())
        target: tuple[float, ...] = linear_rgb(WARM_PAPER_THEME.accent)
        for channel, key in enumerate(("inputRVector", "inputGVector", "inputBVector")):
            vector: Any = color_filter.valueForKey_(key)
            assert sum(vector.valueAtIndex_(index) * source[index] for index in range(3)) == (
                pytest.approx(target[channel])
            )
            for neutral in (0.0, 0.25, 0.5, 1.0):
                assert sum(vector.valueAtIndex_(index) * neutral for index in range(3)) == (
                    pytest.approx(neutral)
                )
            assert vector.valueAtIndex_(3) == 0
        assert color_filter.valueForKey_("inputAVector").W() == 1
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


@pytest.mark.parametrize(
    "key", ["appearance", "theme", "error_check", "daily_minimum", "daily_maximum"]
)
def test_settings_dropdowns_theme_open_rows_and_restore_native_menus(
    native_controller: Any, key: str
) -> None:
    """Every Settings dropdown themes its open rows without accumulating extra width."""
    controller: Any = native_controller
    controller.settings_controls = {}
    controller.build_settings()
    try:
        controller.apply_theme(WARM_PAPER_THEME)
        popup: Any = controller.settings_controls[key]
        width: float = popup.menu().size().width
        for _ in range(3):
            popup.menuWillOpen_(popup.menu())
            assert popup.menu().size().width == width
        selected: Any = popup.selectedItem()
        popup.menu_willHighlightItem_(popup.menu(), selected)
        for item in popup.itemArray():
            row: Any = item.view()
            assert isinstance(row, ThemeMenuRow)
            assert row.theme is WARM_PAPER_THEME
            assert row.enclosingMenuItem() == item
            assert row.highlighted == (item == selected)
            assert row.acceptsFirstResponder()
            assert row.accessibilityLabel() == item.title()
        controller.apply_theme(DEFAULT_THEME)
        assert popup.menu().delegate() is None
        assert all(item.view() is None for item in popup.itemArray())
        assert popup.menu().showsStateColumn()
    finally:
        controller.settings_window.close()


def test_settings_menu_mouse_and_accessibility_choices_send_one_action(
    native_controller: Any,
) -> None:
    """Themed menu input applies the selected preference once without editing the puzzle."""
    controller: Any = native_controller
    controller.settings_controls = {}
    controller.save = Mock()
    controller.refresh = Mock()
    controller.build_settings()
    before: object = controller.game.snapshot()
    try:
        controller.apply_theme(WARM_PAPER_THEME)
        popup: Any = controller.settings_controls["error_check"]
        popup.itemWithTitle_("Off").view().mouseUp_(None)
        assert popup.titleOfSelectedItem() == controller.preferences.error_check == "Off"
        assert controller.save.call_count == 1
        assert popup.itemWithTitle_("Against Solution").view().accessibilityPerformPress()
        assert (
            popup.titleOfSelectedItem() == controller.preferences.error_check == "Against Solution"
        )
        assert controller.save.call_count == 2
        assert controller.game.snapshot() == before
    finally:
        controller.settings_window.close()


@pytest.mark.parametrize("input_method", ["keyboard", "mouse"])
def test_themed_dropdown_keeps_native_menu_selection(
    native_controller: Any, input_method: str
) -> None:
    """Exercise genuine keyboard and mouse events inside native themed menu tracking."""
    controller: Any = native_controller
    controller.settings_controls = {}
    controller.preferences.appearance = "Light"
    controller.preferences.theme = "Warm Paper"
    controller.save = Mock()
    controller.refresh = Mock()
    controller.build_settings()
    controller.apply_theme(WARM_PAPER_THEME)
    popup: Any = controller.settings_controls["appearance"]
    popup.selectItemWithTitle_("Light")
    application: Any = AK.NSApplication.sharedApplication()
    controller.settings_window.makeKeyAndOrderFront_(None)
    event_state: dict[str, Any] = {}
    original_cursor: Any = Q.CGEventGetLocation(Q.CGEventCreate(None))

    def select_dark(timer: Any) -> None:
        """Select Dark through actual events while the native menu tracks."""
        if input_method == "mouse":
            row: Any = popup.itemWithTitle_("Dark").view()
            window: Any = row.window()
            event_state["row_frame"] = str(row.frame())
            event_state["window_visible"] = bool(window and window.isVisible())
            if window is None or not window.isVisible() or row.bounds().size.width <= 0:
                return
            point: Any = row.convertPoint_toView_(
                (row.bounds().size.width / 2, row.bounds().size.height / 2), None
            )
            event_state["click_point"] = str(point)
            screen_point: Any = window.convertPointToScreen_(point)
            display_height: float = float(AK.NSScreen.screens()[0].frame().size.height)
            event_state["cursor_error"] = Q.CGWarpMouseCursorPosition(
                (screen_point.x, display_height - screen_point.y)
            )
            content: Any = window.contentView()
            event_state["hit_target"] = (
                content.hitTest_(content.convertPoint_fromView_(point, None)) == row
            )
            mouse_selector: str = (
                "mouseEventWithType_location_modifierFlags_timestamp_windowNumber_"
                "context_eventNumber_clickCount_pressure_"
            )
            mouse_factory: Any = getattr(AK.NSEvent, mouse_selector)
            event_types: tuple[int, ...] = (
                (AK.NSEventTypeLeftMouseDown, AK.NSEventTypeLeftMouseUp)
                if event_state.get("hover_sent")
                else (AK.NSEventTypeMouseMoved,)
            )
            if event_state.get("hover_sent"):
                timer.invalidate()
            event_state["hover_sent"] = True
            for event_type in event_types:
                mouse_event: Any = mouse_factory(
                    event_type,
                    point,
                    0,
                    NSProcessInfo.processInfo().systemUptime(),
                    window.windowNumber(),
                    None,
                    0,
                    1,
                    1,
                )
                application.postEvent_atStart_(mouse_event, False)
            return
        timer.invalidate()
        event_selector: str = (
            "keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_"
            "characters_charactersIgnoringModifiers_isARepeat_keyCode_"
        )
        event_factory: Any = getattr(AK.NSEvent, event_selector)
        for code, characters in ((125, "\uf701"), (36, "\r")):
            key_event: Any = event_factory(
                AK.NSEventTypeKeyDown,
                (0, 0),
                AK.NSEventModifierFlagFunction if code == 125 else 0,
                0,
                controller.settings_window.windowNumber(),
                None,
                characters,
                characters,
                False,
                code,
            )
            application.postEvent_atStart_(key_event, False)

    timer: Any = NSTimer.timerWithTimeInterval_repeats_block_(0.05, True, select_dark)
    guard: Any = NSTimer.timerWithTimeInterval_repeats_block_(
        3, False, lambda timer: popup.menu().cancelTracking()
    )
    for scheduled in (timer, guard):
        NSRunLoop.mainRunLoop().addTimer_forMode_(scheduled, AK.NSEventTrackingRunLoopMode)
    try:
        popup.performClick_(None)
        assert popup.titleOfSelectedItem() == controller.preferences.appearance == "Dark", (
            event_state
        )
        assert controller.save.call_count == 1
    finally:
        timer.invalidate()
        guard.invalidate()
        if input_method == "mouse":
            Q.CGWarpMouseCursorPosition(original_cursor)
        controller.settings_window.close()


@pytest.mark.parametrize("theme", [DEFAULT_THEME, WARM_PAPER_THEME])
def test_new_game_dialog_themes_difficulty_and_buttons_without_starting_game(
    native_controller: Any, theme: Any
) -> None:
    """Difficulty menus and modal buttons follow the theme while retaining native actions."""
    controller: Any = native_controller
    controller.regular_game = controller.game
    controller.active_daily_date = None
    controller.apply_theme(theme)
    before: object = controller.game.snapshot()
    alert: Any = controller.build_new_game_dialog()
    try:
        popup: Any = alert.accessoryView()
        assert isinstance(popup, ThemePopUpButton)
        assert popup.theme is theme
        assert popup.titleOfSelectedItem() == controller.game.puzzle.level
        assert [item.title() for item in popup.itemArray()] == [
            "Easy",
            "Medium",
            "Hard",
            "Expert",
            "Master",
            "Extreme",
        ]
        assert alert.buttons()[0].keyEquivalent() == "\r"
        assert alert.buttons()[1].keyEquivalent() == "\x1b"
        if theme is WARM_PAPER_THEME:
            assert alert.buttons()[0].bezelColor() is None
            assert alert.buttons()[0].layer().filters()
            assert all(isinstance(item.view(), ThemeMenuRow) for item in popup.itemArray())
            for button in alert.buttons():
                assert button.focusRingType() == AK.NSFocusRingTypeNone
                outline: Any = next(
                    child for child in button.subviews() if isinstance(child, ThemeFocusOutline)
                )
                assert outline.theme is theme
                assert outline.hitTest_((0, 0)) is None
        else:
            assert all(item.view() is None for item in popup.itemArray())
        assert controller.game.snapshot() == before
    finally:
        alert.window().close()


@pytest.mark.parametrize("appearance", ["Light", "Dark"])
@pytest.mark.parametrize("size", [(960, 780), (400, 600)])
@pytest.mark.parametrize("theme", ["Default", "Warm Paper", "High Contrast"])
def test_import_level_click_keeps_progress_and_fits_header(
    native_controller: Any,
    tmp_path: Path,
    isolated_catalog: Any,
    unmatched_import: ValidatedImport,
    appearance: str,
    size: tuple[int, int],
    theme: str,
) -> None:
    """Select a level from the real header dropdown with no modal or change to any board cell."""
    controller: Any = native_controller
    controller.store = Store(tmp_path)
    controller.store.load_game(isolated_catalog)
    controller.history = HistoryStore(tmp_path / "history.sqlite3")
    controller.game = controller.store.imported.start(unmatched_import, "Hard")
    controller.store.activate_replay(controller.game)
    controller.regular_game = controller.game
    controller.active_daily_date = None
    controller.daily_games = {}
    controller.current_hint = None
    controller.hint_stage = 0
    controller.save_problem = ""
    controller.preferences.appearance = appearance
    controller.preferences.theme = theme
    controller.theme = theme_for_name(theme)
    controller.apply_appearance()
    controller.window.setContentSize_(size)
    controller.refresh()
    picker: Any = controller.controls["import_level"]
    subtitle: Any = controller.controls["subtitle"]
    assert isinstance(picker, ThemePopUpButton)
    assert not picker.isHidden()
    assert picker.titleOfSelectedItem() == "Hard"
    assert picker.theme is controller.theme
    assert AK.NSMaxX(picker.frame()) <= AK.NSMinX(subtitle.frame())
    assert picker.frame().size.width > 0
    assert picker.frame().size.height > 0
    assert [item.title() for item in picker.itemArray()] == list(LEVELS)
    before: dict[str, Any] = game_data(controller.game)
    controller.alert = Mock()
    controller.build_message_dialog = Mock()
    if theme == "Default":
        picker.selectItemWithTitle_("Expert")
        picker.sendAction_to_(picker.action(), picker.target())
    else:
        picker.menuWillOpen_(picker.menu())
        picker.itemWithTitle_("Expert").view().accessibilityPerformPress()
    assert controller.game.puzzle.level == picker.titleOfSelectedItem() == "Expert"
    controller.alert.assert_not_called()
    controller.build_message_dialog.assert_not_called()
    assert game_data(controller.game) == before
    restored: Game | None = Store(tmp_path).load_game(isolated_catalog)
    assert restored is not None
    assert restored.puzzle.level == "Expert"
    assert game_data(restored) == before


@pytest.mark.parametrize("source", ["regular", "matched_import", "daily", "completed_import"])
def test_header_level_is_read_only_for_catalog_and_completed_games(
    native_controller: Any, source: str
) -> None:
    """Show the original level as ordinary subtitle text outside editable imported attempts."""
    controller: Any = native_controller
    controller.active_daily_date = "2026-10-19" if source == "daily" else None
    controller.daily_games = {}
    controller.store = Mock()
    controller.current_hint = None
    controller.hint_stage = 0
    controller.save_problem = ""
    if source == "completed_import":
        controller.game.puzzle = replace(
            controller.game.puzzle, identifier="IMP-000001", rating=None
        )
        controller.game.values = list(controller.game.puzzle.solution)
    controller.refresh()
    assert controller.controls["import_level"].isHidden()
    assert controller.game.puzzle.level in controller.controls["subtitle"].stringValue()


@pytest.mark.parametrize("name", ["Default", "Warm Paper", "High Contrast"])
@pytest.mark.parametrize("appearance", [AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua])
def test_completion_dialog_tint_retains_native_action(
    native_controller: Any, name: str, appearance: str
) -> None:
    """Keep the completion button's native action, Return shortcut, tint, and game state."""
    controller: Any = native_controller
    theme: Any = theme_for_name(name)
    controller.window.setAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
    controller.apply_theme(theme)
    before: dict[str, Any] = game_data(controller.game)
    alert: Any = controller.build_message_dialog("Puzzle complete", "Level: Easy\nTime: 5:00")
    primary: Any = alert.buttons()[0]
    application: Any = AK.NSApplication.sharedApplication()

    def confirm(timer: Any) -> None:
        """Dismiss through the unchanged NSButton action while the alert is modal."""
        primary.performClick_(None)

    timer: Any = NSTimer.timerWithTimeInterval_repeats_block_(0.1, False, confirm)
    guard: Any = NSTimer.timerWithTimeInterval_repeats_block_(
        3, False, lambda timer: application.abortModal()
    )
    for scheduled in (timer, guard):
        NSRunLoop.mainRunLoop().addTimer_forMode_(scheduled, AK.NSModalPanelRunLoopMode)
    try:
        assert primary.title() == "OK" and primary.keyEquivalent() == "\r"
        assert alert.runModal() == AK.NSAlertFirstButtonReturn
        if theme is DEFAULT_THEME:
            assert primary.layer() is None or not primary.layer().filters()
        else:
            assert primary.bezelColor() is None
            assert primary.layer().filters()
            outline: Any = next(
                child for child in primary.subviews() if isinstance(child, ThemeFocusOutline)
            )
            assert outline.theme is theme and outline.tints_button
            original_filter: Any = primary.layer().filters()[0]
            primary.setAppearance_(
                AK.NSAppearance.appearanceNamed_(
                    AK.NSAppearanceNameDarkAqua
                    if appearance == AK.NSAppearanceNameAqua
                    else AK.NSAppearanceNameAqua
                )
            )
            assert primary.layer().filters()[0] != original_filter
        assert game_data(controller.game) == before
    finally:
        timer.invalidate()
        guard.invalidate()
        alert.window().close()


@pytest.mark.parametrize("name", ["Default", "Warm Paper", "High Contrast"])
@pytest.mark.parametrize("appearance", [AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua])
@pytest.mark.parametrize("action", ["Locate One", "Restart", "Reveal"])
def test_cancel_first_dialog_keeps_readable_text_and_native_actions(
    native_controller: Any, name: str, appearance: str, action: str
) -> None:
    """Avoid primary-action ink on Cancel while preserving button order and shortcuts."""
    controller: Any = native_controller
    theme: Any = theme_for_name(name)
    controller.window.setAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
    controller.apply_theme(theme)
    before: dict[str, Any] = game_data(controller.game)
    alert: Any = controller.build_message_dialog(
        "Check your entries first", "Locate an incorrect entry?", ("Cancel", action)
    )
    cancel: Any = alert.buttons()[0]
    affirmative: Any = alert.buttons()[1]

    def confirm(timer: Any) -> None:
        """Choose the second action through the original native alert target."""
        affirmative.performClick_(None)

    timer: Any = NSTimer.timerWithTimeInterval_repeats_block_(0.1, False, confirm)
    guard: Any = NSTimer.timerWithTimeInterval_repeats_block_(
        3, False, lambda timer: AK.NSApplication.sharedApplication().abortModal()
    )
    for scheduled in (timer, guard):
        NSRunLoop.mainRunLoop().addTimer_forMode_(scheduled, AK.NSModalPanelRunLoopMode)
    try:
        assert cancel.keyEquivalent() == "\x1b"
        assert affirmative.keyEquivalent() == ""
        assert alert.window().defaultButtonCell() is None
        if theme is not DEFAULT_THEME:
            for button in alert.buttons():
                color: Any = button.attributedTitle().attribute_atIndex_effectiveRange_(
                    AK.NSForegroundColorAttributeName, 0, None
                )[0]
                assert color.isEqual_(theme.text)
                assert button.layer() is None or not button.layer().filters()
                outline: Any = next(
                    child for child in button.subviews() if isinstance(child, ThemeFocusOutline)
                )
                assert not outline.tints_button
        assert alert.runModal() == AK.NSAlertSecondButtonReturn
        assert game_data(controller.game) == before
    finally:
        timer.invalidate()
        guard.invalidate()
        alert.window().close()


@pytest.mark.parametrize("native_controller", [False, True], indirect=True)
def test_glass_choices_forward_clicks_without_editing_board(native_controller: Any) -> None:
    """Glass selection buttons retain the existing mode actions and puzzle state."""
    controller: Any = native_controller
    before: object = controller.game.snapshot()
    controller.save = Mock()
    controller.refresh = Mock()
    controller.controls["order"].choice_buttons[1].performClick_(None)
    controller.controls["mode"].choice_buttons[1].performClick_(None)
    assert controller.preferences.input_order == "Number First"
    assert controller.game.note_mode
    assert controller.controls["order"].selectedSegment() == 1
    assert controller.controls["mode"].selectedSegment() == 1
    assert controller.game.snapshot() == before


@pytest.mark.parametrize("native_controller", [False, True], indirect=True)
def test_glass_choices_refresh_with_real_game_state(native_controller: Any) -> None:
    """Opening a game can select and enable the new choice rows without error."""
    controller: Any = native_controller
    controller.active_daily_date = None
    controller.daily_games = {}
    controller.store = Mock()
    controller.current_hint = None
    controller.hint_stage = 0
    controller.save_problem = ""
    controller.refresh()
    assert controller.controls["order"].selectedSegment() == 0
    assert controller.controls["mode"].selectedSegment() == 0


@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("native_controller", [False, True], indirect=True)
def test_pause_button_can_resume_game(native_controller: Any, imported: bool) -> None:
    """Pause and resume regular and imported games through the actual native button."""
    controller: Any = native_controller
    if imported:
        controller.game.puzzle = replace(
            controller.game.puzzle, identifier="IMP-000013", rating=None
        )
    controller.active_daily_date = None
    controller.daily_games = {}
    controller.store = Mock()
    controller.current_hint = None
    controller.hint_stage = 0
    controller.save = Mock()
    controller.refresh()
    button: Any = controller.controls["pause"]
    assert button.title() == "Pause"
    assert button.isEnabled()

    button.performClick_(None)

    assert controller.game.paused
    assert button.title() == "Resume"
    assert button.isEnabled()
    assert not controller.controls["digit1"].isEnabled()

    button.performClick_(None)

    assert not controller.game.paused
    assert button.title() == "Pause"
    assert button.isEnabled()
    assert controller.controls["digit1"].isEnabled()
    assert controller.save.call_count == 2


@pytest.mark.parametrize("native_controller", [False, True], indirect=True)
def test_pause_button_disabled_for_completed_game(native_controller: Any) -> None:
    """Keep the pause action unavailable once all answers match the solution."""
    controller: Any = native_controller
    controller.active_daily_date = None
    controller.daily_games = {}
    controller.store = Mock()
    controller.current_hint = None
    controller.hint_stage = 0
    controller.game.values = list(controller.game.puzzle.solution)

    controller.refresh()

    assert not controller.controls["pause"].isEnabled()


def test_erase_control_tracks_solution_protection(native_controller: Any) -> None:
    """Refresh reflects preference changes while still allowing colors and incorrect edits."""
    controller: Any = native_controller
    controller.active_daily_date = None
    controller.daily_games = {}
    controller.store = Mock()
    controller.current_hint = None
    controller.hint_stage = 0
    controller.save_problem = ""
    controller.game.selected = 7
    controller.game.set_value(7, 8)
    controller.preferences.error_check = "Against Solution"
    controller.refresh()
    assert not controller.controls["erase"].isEnabled()
    controller.game.color_mode = True
    controller.refresh()
    assert controller.controls["erase"].isEnabled()
    controller.game.color_mode = False
    controller.preferences.error_check = "Off"
    controller.refresh()
    assert controller.controls["erase"].isEnabled()
    controller.preferences.error_check = "Against Solution"
    controller.game.set_value(7, 3)
    controller.refresh()
    assert controller.controls["erase"].isEnabled()


@pytest.mark.parametrize("theme", [DEFAULT_THEME, WARM_PAPER_THEME])
def test_glass_choices_keep_theme_accent_when_selection_changes(
    native_controller: Any, theme: Any
) -> None:
    """Theme changes and later selections tint only the active glass button."""
    controller: Any = native_controller
    before: object = controller.game.snapshot()
    controller.apply_theme(theme)
    for key in ("order", "mode"):
        choices: Any = controller.controls[key]
        for selected in range(len(choices.choice_buttons)):
            choices.setSelectedSegment_(selected)
            for index, button in enumerate(choices.choice_buttons):
                if index == selected:
                    assert button.bezelColor().isEqual_(theme.accent)
                else:
                    assert button.bezelColor() is None
    assert controller.game.snapshot() == before


def test_translucent_theme_colors_follow_light_and_dark(native_controller: Any) -> None:
    """Resolve alpha after AppKit chooses its current light or dark appearance."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        red_components: list[float] = []
        for name in (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua):
            AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(name))
            color: Any = DEFAULT_THEME.board.major_grid.resolve().colorUsingColorSpace_(
                AK.NSColorSpace.deviceRGBColorSpace()
            )
            red_components.append(float(color.redComponent()))
            assert color.alphaComponent() == pytest.approx(0.60)
        assert red_components[0] < red_components[1]
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


def test_board_uses_replaceable_theme_background(native_controller: Any) -> None:
    """A future image background can draw without changing board rendering."""
    controller: Any = native_controller
    for name in ("hint_focus", "hint_removals", "hint_candidates", "hint_placements"):
        setattr(controller, name, set())
    background: Mock = Mock()
    themed_board: Any = replace(DEFAULT_THEME.board, background=background)
    controller.apply_theme(replace(DEFAULT_THEME, board=themed_board))
    board: Any = controller.board
    bitmap: Any = board.bitmapImageRepForCachingDisplayInRect_(board.bounds())

    board.cacheDisplayInRect_toBitmapImageRep_(board.bounds(), bitmap)

    background.draw.assert_called()


@pytest.mark.parametrize("appearance", [AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua])
@pytest.mark.parametrize("theme_name", ["Default", "Warm Paper", "High Contrast"])
def test_about_dialog_displays_author_and_offline_notice_actions(
    native_controller: Any, appearance: str, theme_name: str
) -> None:
    """Keep legal credit and all three actions visible in Light and Dark themes."""
    controller: Any = native_controller
    controller.window.setAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
    controller.apply_theme(theme_for_name(theme_name))
    before: dict[str, Any] = game_data(controller.game)
    alert: Any = controller.build_about_dialog()
    try:
        alert.layout()
        assert alert.messageText() == f"Sudoku {APP_VERSION}"
        assert COPYRIGHT_NOTICE in alert.informativeText()
        assert "version 3 only" in alert.informativeText()
        assert "no warranty" in alert.informativeText()
        assert "Sudoku Exchange" in alert.informativeText()
        assert [button.title() for button in alert.buttons()] == [
            "OK",
            "View License",
            "Third-Party Notices",
        ]
        assert alert.window().appearance() == controller.window.appearance()
        for button in alert.buttons():
            assert AK.NSContainsRect(button.superview().bounds(), button.frame())
        assert game_data(controller.game) == before
    finally:
        alert.window().close()


@pytest.mark.parametrize("appearance", [AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua])
@pytest.mark.parametrize("kind", ["license", "third-party"])
def test_license_dialog_displays_complete_selectable_text(
    native_controller: Any, appearance: str, kind: str
) -> None:
    """Make the complete offline notices readable, selectable, and vertically scrollable."""
    controller: Any = native_controller
    controller.window.setAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
    message: str = license_text() if kind == "license" else third_party_text()
    alert: Any = controller.build_text_dialog("License notices", message, "License notices")
    try:
        scroll: Any = alert.accessoryView()
        alert.layout()
        scroll.tile()
        assert scroll.documentView().string() == message
        assert scroll.documentView().isSelectable()
        assert not scroll.documentView().isEditable()
        assert not scroll.hasHorizontalScroller()
        assert scroll.documentView().frame().size.height > scroll.contentView().bounds().size.height
        assert scroll.documentView().accessibilityLabel() == "License notices"
        scroll.contentView().scrollToPoint_(
            (
                0,
                scroll.documentView().frame().size.height
                - scroll.contentView().bounds().size.height,
            )
        )
        assert scroll.contentView().bounds().origin.y > 20
    finally:
        alert.window().close()


@pytest.mark.parametrize("choice", [0, 1, 2])
def test_about_actions_open_the_matching_offline_notice(
    native_controller: Any, choice: int
) -> None:
    """Route About buttons to the actual packaged text without opening a web browser."""
    controller: Any = native_controller
    controller.build_about_dialog = Mock(
        return_value=Mock(runModal=Mock(return_value=AK.NSAlertFirstButtonReturn + choice))
    )
    controller.build_text_dialog = Mock()
    controller.about_(None)
    if choice == 0:
        controller.build_text_dialog.assert_not_called()
    else:
        expected: str = license_text() if choice == 1 else third_party_text()
        assert controller.build_text_dialog.call_args.args[1] == expected
        controller.build_text_dialog.return_value.runModal.assert_called_once()


def test_about_reports_missing_license_without_crashing(
    native_controller: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Show an actionable error when the offline resource cannot be read."""
    controller: Any = native_controller
    controller.build_about_dialog = Mock(
        return_value=Mock(runModal=Mock(return_value=AK.NSAlertSecondButtonReturn))
    )
    controller.alert = Mock()
    monkeypatch.setattr("sudoku.app.license_text", Mock(side_effect=OSError("Missing license")))
    controller.about_(None)
    controller.alert.assert_called_once_with("Cannot read license notices", "Missing license")


def test_help_dialog_scrolls_long_text(native_controller: Any) -> None:
    """Keep the guide text within a fixed viewport with a visible vertical scrollbar."""
    message: str = "Arrow keys and trackpad gestures remain available.\n" * 100
    alert: Any = native_controller.build_help_dialog(message)
    scroll: Any = alert.accessoryView()
    alert.layout()
    scroll.tile()
    assert scroll.documentView().string() == message
    assert scroll.hasVerticalScroller()
    assert not scroll.hasHorizontalScroller()
    assert scroll.scrollerStyle() == AK.NSScrollerStyleLegacy
    assert scroll.documentView().frame().size.height > scroll.contentView().bounds().size.height
    assert not scroll.verticalScroller().isHidden()
    assert 0 <= scroll.contentView().bounds().origin.y < 20
    scroll.contentView().scrollToPoint_(
        (0, scroll.documentView().frame().size.height - scroll.contentView().bounds().size.height)
    )
    assert scroll.contentView().bounds().origin.y > 20


def test_help_dialog_hides_unneeded_scrollbar(native_controller: Any) -> None:
    """Avoid showing a scrollbar when the entire guide text fits."""
    alert: Any = native_controller.build_help_dialog("Short guide")
    scroll: Any = alert.accessoryView()
    alert.layout()
    scroll.tile()
    assert scroll.documentView().frame().size.height == scroll.contentView().bounds().size.height
    assert scroll.verticalScroller().isHidden()


@pytest.mark.parametrize(
    ("width", "height"),
    [(1120, 820), (700, 1000), (700, 740), (1200, 640), (520, 640), (400, 480), (1200, 480)],
)
@pytest.mark.parametrize("daily", [False, True])
def test_native_panel_containment(
    native_controller: Any, width: float, height: float, daily: bool
) -> None:
    """Keep panels, keypad digits, hint actions, and wrapped button rows inside their owners."""
    c: Any = native_controller
    c.controls["daily"].setHidden_(not daily)
    c.controls["hint"].setTitle_("Next Step")
    c.controls["hint_text"].setString_("A long explanation that wraps across several lines. " * 100)
    c.window.setContentSize_((width, height))
    c.layout()
    c.layout()
    a: Any = c.adaptive_layout
    for view in (a.header, a.scroller, a.actions, c.controls["status"]):
        assert contains(a.root, view)
    for view in (a.board_panel, a.support_scroll):
        assert contains(a.group, view)
    for view in (a.keypad, a.hints):
        if not view.isHiddenOrHasHiddenAncestor():
            assert contains(a.support, view)
    for key in ("order", "mode", "footer", *(f"digit{i}" for i in range(1, 10))):
        assert contains(a.keypad, c.controls[key]), key
    for key in ("hint", "previous_hint", "apply_hint", "another_hint", "hint_scroll"):
        if not c.controls[key].isHiddenOrHasHiddenAncestor():
            assert contains(a.hints, c.controls[key]), key
    assert c.board.bounds().size.width == c.board.bounds().size.height
    assert contains(a.document, a.group)
    for first, second in ((a.board_panel, a.support_scroll), (a.keypad, a.hints)):
        if first.isHiddenOrHasHiddenAncestor() or second.isHiddenOrHasHiddenAncestor():
            continue
        first_rect: Any = a.group.convertRect_fromView_(first.bounds(), first)
        second_rect: Any = a.group.convertRect_fromView_(second.bounds(), second)
        assert not AK.NSIntersectsRect(first_rect, second_rect)
    for index in range(81):
        rect: Any = c.board.cell_rect(index)
        point: Any = c.board.convertPoint_toView_((AK.NSMidX(rect), AK.NSMidY(rect)), None)
        event: Any = SimpleNamespace(locationInWindow=lambda point=point: point)
        assert c.board.index_at_event(event) == index
    for row in range(3):
        positions: list[Any] = [
            a.keypad.convertRect_fromView_(
                c.controls[f"digit{row * 3 + col + 1}"].bounds(),
                c.controls[f"digit{row * 3 + col + 1}"],
            )
            for col in range(3)
        ]
        assert positions[0].origin.y == positions[1].origin.y == positions[2].origin.y
        assert AK.NSMaxX(positions[0]) < positions[1].origin.x
        assert AK.NSMaxX(positions[1]) < positions[2].origin.x


def test_live_resize_preserves_board_and_state(native_controller: Any) -> None:
    """Continuously update real constraints without replacing the board or mutating progress."""
    c: Any = native_controller
    before: object = c.game.snapshot()
    board: Any = c.board
    c.window.makeFirstResponder_(board)
    for width in [*range(520, 1250, 17), *range(1250, 520, -17)]:
        c.window.setContentSize_((width, 750))
        c.layout()
        assert c.board is board
        assert c.window.firstResponder() == board
        assert contains(c.adaptive_layout.document, c.adaptive_layout.group)
    assert c.game.snapshot() == before


def pointer_at_cell(
    board: Any,
    index: int,
    offset: tuple[float, float] = (0.0, 0.0),
    modifiers: int = 0,
) -> Any:
    """Construct a window-coordinate pointer event within a native board cell."""
    rect: Any = board.cell_rect(index)
    point: Any = board.convertPoint_toView_(
        (AK.NSMidX(rect) + offset[0], AK.NSMidY(rect) + offset[1]), None
    )
    return SimpleNamespace(locationInWindow=lambda: point, modifierFlags=lambda: modifiers)


@pytest.mark.parametrize("control_click", [False, True])
@pytest.mark.parametrize("input_mode", ["Answers", "Candidates", "Color"])
def test_cell_secondary_click_opens_menu_without_editing(
    native_controller: Any,
    monkeypatch: pytest.MonkeyPatch,
    control_click: bool,
    input_mode: str,
) -> None:
    """Give Control-click the same cell menu without starting an editing gesture."""
    controller: Any = native_controller
    board: Any = controller.board
    game: Game = controller.game
    controller.refresh = Mock()
    controller.changed = Mock()
    controller.preferences.input_order = "Number First"
    game.note_mode = input_mode == "Candidates"
    game.color_mode = input_mode == "Color"
    game.active_digit = 4
    before: Snapshot = game.snapshot()
    history: list[Snapshot] = list(game.undo_stack)
    popup: Mock = Mock()
    monkeypatch.setattr(
        AK,
        "NSMenu",
        SimpleNamespace(alloc=AK.NSMenu.alloc, popUpContextMenu_withEvent_forView_=popup),
    )
    event: Any = pointer_at_cell(
        board, 10, modifiers=AK.NSEventModifierFlagControl if control_click else 0
    )

    if control_click:
        board.mouseDown_(event)
    else:
        board.rightMouseDown_(event)

    popup.assert_called_once()
    menu: Any = popup.call_args.args[0]
    assert menu.itemWithTitle_("Answer") is not None
    assert menu.itemWithTitle_("Candidate") is not None
    assert menu.itemWithTitle_("Color") is not None
    assert popup.call_args.args[1] is event
    assert popup.call_args.args[2] is board
    assert game.selected == 10
    assert controller.window.firstResponder() == board
    assert board.drag_origin is None
    assert board.context_menu_controller is None
    board.mouseUp_(event)
    assert game.snapshot() == before
    assert game.undo_stack == history


@pytest.mark.parametrize("text", [" ", "\r", "\n", "\x03"])
@pytest.mark.parametrize("input_order", ["Cell First", "Number First"])
@pytest.mark.parametrize("state", ["empty", "marked", "filled", "given", "paused", "remove_empty"])
def test_shift_activation_paints_candidate_in_place(
    native_controller: Any, text: str, input_order: str, state: str
) -> None:
    """Paint one candidate with drag semantics, no movement, and one undo entry."""
    controller: Any = native_controller
    game: Game = controller.game
    controller.refresh = Mock()
    controller.changed = Mock()
    controller.preferences.input_order = input_order
    controller.preferences.drag_answers_as_candidates = True
    game.note_mode = False
    game.active_digit = 4
    game.selected = 0 if state == "given" else 10
    if state == "marked":
        game.mark(10, 4)
    elif state == "filled":
        game.set_value(10, 4)
    game.paused = state == "paused"
    before: Snapshot = game.snapshot()
    history: list[Snapshot] = list(game.undo_stack)
    flags: int = AK.NSEventModifierFlagShift
    if state == "remove_empty":
        flags |= AK.NSEventModifierFlagOption
    event: Any = SimpleNamespace(
        charactersIgnoringModifiers=lambda: text,
        charactersByApplyingModifiers_=lambda modifiers: text,
        modifierFlags=lambda: flags,
    )

    controller.board.keyDown_(event)

    assert game.selected == (0 if state == "given" else 10)
    assert not game.note_mode
    if state in {"empty", "marked"}:
        assert game.values[10] == 0
        assert game.notes[10] == ({4} if state == "empty" else set())
        assert len(game.undo_stack) == len(history) + 1
        controller.changed.assert_called_once()
        assert game.undo()
        assert game.snapshot() == before
    else:
        assert game.snapshot() == before
        assert game.undo_stack == history


@pytest.mark.parametrize("text", [" ", "\r"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("shift", [False, True])
@pytest.mark.parametrize("mode", ["Answers", "Candidates", "Color"])
def test_activation_respects_paint_setting_and_mode(
    native_controller: Any, text: str, enabled: bool, shift: bool, mode: str
) -> None:
    """Keep ordinary activation and Color mode intact when adding shifted candidate entry."""
    controller: Any = native_controller
    game: Game = controller.game
    controller.refresh = Mock()
    controller.changed = Mock()
    controller.preferences.input_order = "Number First"
    controller.preferences.drag_answers_as_candidates = enabled
    game.selected = 10
    game.active_digit = 4
    game.active_color = 3
    game.note_mode = mode == "Candidates"
    game.color_mode = mode == "Color"
    event: Any = SimpleNamespace(
        charactersIgnoringModifiers=lambda: text,
        charactersByApplyingModifiers_=lambda modifiers: text,
        modifierFlags=lambda: AK.NSEventModifierFlagShift if shift else 0,
    )

    controller.board.keyDown_(event)

    candidate: bool = mode == "Candidates" or (mode == "Answers" and shift and enabled)
    assert game.values[10] == (4 if mode == "Answers" and not candidate else 0)
    assert game.notes[10] == ({4} if candidate else set())
    assert game.colors[10] == (3 if mode == "Color" else 0)
    assert game.selected == 10


@pytest.mark.parametrize("error_check", ["Off", "Rule Conflicts", "Against Solution"])
@pytest.mark.parametrize(
    "action", ["click", "keypad", "digit", "space", "return", "erase", "delete", "zero", "menu"]
)
def test_correct_answers_respect_solution_protection(
    native_controller: Any, error_check: str, action: str
) -> None:
    """Protect verified answers across input paths only while solution checking is active."""
    controller: Any = native_controller
    game: Game = controller.game
    controller.preferences.error_check = error_check
    controller.preferences.input_order = (
        "Number First" if action in ("click", "space", "return") else "Cell First"
    )
    controller.save = Mock()
    controller.refresh = Mock()
    controller.changed = Mock()
    game.selected = 4
    game.set_value(4, 5)
    game.mark(5, 8)
    game.active_digit = 8
    before: Snapshot = game.snapshot()
    history: list[Snapshot] = list(game.undo_stack)
    mistakes: set[tuple[int, int]] = set(game.incorrect_entries)
    if action == "click":
        controller.board.mouseDown_(pointer_at_cell(controller.board, 4))
        controller.board.mouseUp_(pointer_at_cell(controller.board, 4))
    elif action == "keypad":
        controller.select_digit(8, False)
    elif action == "erase":
        controller.erase_(None)
    elif action == "menu":
        context: Any = CellContextMenu.alloc().init()
        context.configure(controller.board, 4)
        menu: Any = context.build_menu()
        assert menu.itemWithTitle_("Answer").isEnabled() == (error_check != "Against Solution")
        assert menu.itemWithTitle_("Color").isEnabled()
        context.chooseAnswer_(SimpleNamespace(tag=lambda: 8))
    else:
        text: str = {"digit": "8", "space": " ", "return": "\r", "delete": "\x7f", "zero": "0"}[
            action
        ]
        controller.board.keyDown_(
            SimpleNamespace(charactersIgnoringModifiers=lambda: text, modifierFlags=lambda: 0)
        )
    if error_check == "Against Solution":
        assert game.snapshot() == before
        assert game.undo_stack == history
        assert game.incorrect_entries == mistakes
    else:
        assert game.values[4] == (0 if action in ("erase", "delete", "zero") else 8)
        assert len(game.undo_stack) == len(history) + 1
    assert game.selected == 4


@pytest.mark.parametrize(
    ("width", "height"), [(1120, 820), (700, 1000), (520, 640), (400, 480), (1200, 480)]
)
def test_resized_board_input(native_controller: Any, width: float, height: float) -> None:
    """Keep diagonal note strokes, selection-only clicks, and Shift-arrow entry aligned."""
    c: Any = native_controller
    c.window.setContentSize_((width, height))
    c.layout()
    c.refresh = Mock()
    c.changed = Mock()
    c.game.note_mode = True
    c.game.active_digit = 3

    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    c.board.mouseUp_(pointer_at_cell(c.board, 10))
    assert not c.game.notes[10]
    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    c.board.mouseDragged_(pointer_at_cell(c.board, 20))
    c.board.mouseUp_(pointer_at_cell(c.board, 20))
    assert c.game.notes[10] == c.game.notes[20] == {3}
    assert not c.game.notes[11] and not c.game.notes[19]
    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    c.board.mouseDragged_(pointer_at_cell(c.board, 20))
    c.board.mouseUp_(pointer_at_cell(c.board, 20))
    assert not c.game.notes[10] and not c.game.notes[20]
    c.game.note_mode = False
    event: Any = SimpleNamespace(
        charactersIgnoringModifiers=lambda: "\uf703",
        charactersByApplyingModifiers_=lambda flags: "\uf703",
        modifierFlags=lambda: AK.NSEventModifierFlagShift,
    )
    c.board.keyDown_(event)
    c.board.finish_gesture()
    assert c.game.selected == 21
    assert c.game.notes[20] == c.game.notes[21] == {3}


@pytest.mark.parametrize("input_order", ["Cell First", "Number First"])
@pytest.mark.parametrize("note_mode", [False, True])
@pytest.mark.parametrize("operation", ["add", "remove", "force_remove", "force_remove_empty"])
def test_candidate_drag_starts_in_initial_cell(
    native_controller: Any, input_order: str, note_mode: bool, operation: str
) -> None:
    """Paint once the movement tolerance is reached and suppress an answer on release."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = input_order
    c.game.note_mode = note_mode
    c.game.active_digit = 4
    if operation in {"remove", "force_remove"}:
        c.game.mark(10, 4)
    before: object = c.game.snapshot()
    undo_count: int = len(c.game.undo_stack)
    modifiers: int = AK.NSEventModifierFlagOption if operation.startswith("force_remove") else 0
    expected_notes: set[int] = {4} if operation == "add" else set()

    c.board.mouseDown_(pointer_at_cell(c.board, 10, modifiers=modifiers))
    assert c.game.snapshot() == before
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, (3.0, 0.0), modifiers))
    assert c.game.notes[10] == expected_notes
    assert c.game.values[10] == 0
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, (-0.25, 0.0), modifiers))
    c.board.mouseUp_(pointer_at_cell(c.board, 10, modifiers=modifiers))
    assert c.game.notes[10] == expected_notes
    assert c.game.values[10] == 0
    assert c.game.note_mode == note_mode
    if operation == "force_remove_empty":
        assert len(c.game.undo_stack) == undo_count
    else:
        assert len(c.game.undo_stack) == undo_count + 1
        assert c.game.undo()
        assert c.game.snapshot() == before
        assert c.game.redo()
        assert c.game.notes[10] == expected_notes


def test_candidate_drag_starts_near_cell_edge(native_controller: Any) -> None:
    """Paint the starting cell even when a short stroke misses its inset interior."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = "Number First"
    c.game.active_digit = 4
    rect: Any = c.board.cell_rect(10)
    near_edge: tuple[float, float] = (-rect.size.width / 2 + 2, 0.0)
    c.board.mouseDown_(pointer_at_cell(c.board, 10, near_edge))
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, (near_edge[0], 3.0)))
    assert c.game.notes[10] == {4}
    c.board.mouseUp_(pointer_at_cell(c.board, 10, (near_edge[0], 3.0)))
    assert c.game.notes[10] == {4}
    assert c.game.values[10] == 0


@pytest.mark.parametrize("start_index", [0, 10])
def test_candidate_drag_skips_filled_starting_cell(
    native_controller: Any, start_index: int
) -> None:
    """Preserve givens and answers while allowing strokes to continue into empty cells."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = "Number First"
    c.game.active_digit = 4
    if start_index == 10:
        c.game.set_value(start_index, 2)
    initial_value: int = c.game.values[start_index]
    before: object = c.game.snapshot()
    undo_count: int = len(c.game.undo_stack)
    c.board.mouseDown_(pointer_at_cell(c.board, start_index))
    c.board.mouseDragged_(pointer_at_cell(c.board, start_index, (3.0, 0.0)))
    c.board.mouseUp_(pointer_at_cell(c.board, start_index))
    assert c.game.snapshot() == before
    assert len(c.game.undo_stack) == undo_count

    c.board.mouseDown_(pointer_at_cell(c.board, start_index))
    c.board.mouseDragged_(pointer_at_cell(c.board, 20))
    c.board.mouseUp_(pointer_at_cell(c.board, 20))
    assert not c.game.notes[start_index]
    assert c.game.values[start_index] == initial_value
    assert c.game.notes[20] == {4}
    assert len(c.game.undo_stack) == undo_count + 1
    assert c.game.undo()
    assert c.game.snapshot() == before


@pytest.mark.parametrize("already_marked", [False, True])
def test_candidate_drag_continues_after_initial_cell(
    native_controller: Any, already_marked: bool
) -> None:
    """Keep one add/remove operation and undo action across a returning diagonal stroke."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = "Number First"
    c.game.active_digit = 4
    cells: tuple[int, ...] = (10, 20, 30)
    if already_marked:
        for index in cells:
            c.game.mark(index, 4)
    before: object = c.game.snapshot()
    undo_count: int = len(c.game.undo_stack)
    expected_notes: set[int] = set() if already_marked else {4}

    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, (3.0, 0.0)))
    assert c.game.notes[10] == expected_notes
    c.board.mouseDragged_(pointer_at_cell(c.board, 30))
    c.board.mouseDragged_(pointer_at_cell(c.board, 10))
    c.board.mouseUp_(pointer_at_cell(c.board, 10))
    assert all(c.game.notes[index] == expected_notes for index in cells)
    assert all(c.game.values[index] == 0 for index in cells)
    assert not c.game.notes[11] and not c.game.notes[19]
    assert not c.game.notes[21] and not c.game.notes[29]
    assert len(c.game.undo_stack) == undo_count + 1
    assert c.game.undo()
    assert c.game.snapshot() == before


@pytest.mark.parametrize(("painting_enabled", "move"), [(True, False), (True, True), (False, True)])
def test_answer_click_and_disabled_candidate_drag(
    native_controller: Any, painting_enabled: bool, move: bool
) -> None:
    """Retain answer clicks and honor the disabled Answers-mode painting preference."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = "Number First"
    c.preferences.drag_answers_as_candidates = painting_enabled
    c.game.active_digit = 4
    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    if move:
        c.board.mouseDragged_(pointer_at_cell(c.board, 10, (0.25, 0.0)))
    assert c.game.values[10] == 0
    assert not c.game.notes[10]
    c.board.mouseUp_(pointer_at_cell(c.board, 10))
    assert c.game.values[10] == 4
    assert not c.game.notes[10]


@pytest.mark.parametrize("input_order", ["Cell First", "Number First"])
@pytest.mark.parametrize("note_mode", [False, True])
def test_candidate_drag_jitter_keeps_click_behavior(
    native_controller: Any, input_order: str, note_mode: bool
) -> None:
    """Ignore small pointer jitter and preserve the active mode's normal click behavior."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = input_order
    c.game.note_mode = note_mode
    c.game.active_digit = 4
    c.game.mark(10, 7)
    before: object = c.game.snapshot()
    undo_count: int = len(c.game.undo_stack)
    offsets: tuple[tuple[float, float], ...] = (
        (0.5, 0.0),
        (2.0, 2.0),
        (-2.0, -2.0),
        (0.0, 0.0),
    )
    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    for offset in offsets:
        c.board.mouseDragged_(pointer_at_cell(c.board, 10, offset))
        assert c.game.snapshot() == before
    c.board.mouseUp_(pointer_at_cell(c.board, 10))
    if input_order == "Cell First":
        assert c.game.snapshot() == before
        assert len(c.game.undo_stack) == undo_count
    else:
        assert c.game.values[10] == (0 if note_mode else 4)
        assert c.game.notes[10] == ({4, 7} if note_mode else set())
        assert len(c.game.undo_stack) == undo_count + 1
        assert c.game.undo()
        assert c.game.snapshot() == before


@pytest.mark.parametrize("offset", [(3.0, 0.0), (-3.0, 0.0), (0.0, -3.0), (2.2, 2.2)])
def test_candidate_drag_uses_displacement_from_mouse_down(
    native_controller: Any, offset: tuple[float, float]
) -> None:
    """Start at the movement tolerance using total displacement rather than event deltas."""
    c: Any = native_controller
    c.refresh = Mock()
    c.changed = Mock()
    c.preferences.input_order = "Number First"
    c.game.active_digit = 4
    before: object = c.game.snapshot()
    c.board.mouseDown_(pointer_at_cell(c.board, 10))
    for fraction in (0.25, 0.5, 0.75):
        partial_offset: tuple[float, float] = (offset[0] * fraction, offset[1] * fraction)
        c.board.mouseDragged_(pointer_at_cell(c.board, 10, partial_offset))
        assert c.game.snapshot() == before
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, offset))
    assert c.game.notes[10] == {4}
    assert c.game.values[10] == 0
    c.board.mouseDragged_(pointer_at_cell(c.board, 10, (0.25, 0.0)))
    c.board.mouseUp_(pointer_at_cell(c.board, 10))
    assert c.game.notes[10] == {4}
    assert c.game.values[10] == 0
    assert len(c.game.undo_stack) == 1
    assert c.game.undo()
    assert c.game.snapshot() == before


def test_native_keypad_scaling_preserves_control_fonts(native_controller: Any) -> None:
    """Verify real tile dimensions shrink while glass choices keep native typography."""
    c: Any = native_controller
    control_font: float = c.controls["order"].choice_buttons[0].font().pointSize()
    hint_font: float = c.controls["hint"].font().pointSize()
    c.window.setContentSize_((1120, 820))
    c.layout()
    large: float = c.controls["digit1"].bounds().size.height
    c.window.setContentSize_((1200, 480))
    c.layout()
    assert c.board.bounds().size.width < 360
    assert c.controls["digit1"].bounds().size.height < large
    assert c.controls["order"].choice_buttons[0].font().pointSize() == control_font
    assert c.controls["hint"].font().pointSize() == hint_font
    c.window.setContentSize_((700, 1000))
    c.layout()
    assert (
        c.board.bounds().size.width
        <= c.adaptive_layout.scroller.contentView().bounds().size.width - 24
    )
    assert contains(c.window.contentView(), c.board)


@pytest.mark.parametrize(("width", "height"), [(400, 480), (520, 640), (1120, 820)])
def test_glass_choice_labels_fit_their_buttons(
    native_controller: Any, width: float, height: float
) -> None:
    """Keep every entry label legible at the supported narrow and wide sizes."""
    controller: Any = native_controller
    controller.window.setContentSize_((width, height))
    controller.layout()
    for key in ("order", "mode"):
        for button in controller.controls[key].choice_buttons:
            assert button.frame().size.width >= button.intrinsicContentSize().width - 1


def test_vertical_resize_keeps_top_of_board_visible(native_controller: Any) -> None:
    """Keep the board's top edge in view when its full-width height grows during resizing."""
    c: Any = native_controller
    c.window.setContentSize_((620, 1000))
    c.layout()
    a: Any = c.adaptive_layout
    a.document.scrollPoint_((0, a.document.bounds().size.height))
    c.window.setContentSize_((700, 1000))
    c.layout()
    viewport: Any = a.scroller.contentView().bounds()
    assert AK.NSMaxY(viewport) == pytest.approx(a.document.bounds().size.height, abs=1)


def test_support_scroll_never_moves_or_clips_board(native_controller: Any) -> None:
    """Keep all 81 cells visible while scrolling through supporting controls."""
    c: Any = native_controller
    for width, height in ((400, 720), (520, 720), (700, 1000), (1200, 720)):
        c.window.setContentSize_((width, height))
        c.layout()
        a: Any = c.adaptive_layout
        for destination in (0, a.support_document.bounds().size.height):
            a.support_document.scrollPoint_((0, destination))
            assert contains(a.scroller.contentView(), c.board)
            assert contains(c.window.contentView(), c.board)
        assert a.document.bounds().size.height == a.scroller.contentView().bounds().size.height


def test_new_arrangement_starts_at_top_of_controls(native_controller: Any) -> None:
    """Lay out the controls viewport before setting its initial scroll position."""
    c: Any = native_controller
    c.window.setContentSize_((700, 1000))
    c.layout()
    a: Any = c.adaptive_layout
    assert AK.NSMaxY(a.support_scroll.contentView().bounds()) == pytest.approx(
        a.support_document.bounds().size.height, abs=1
    )


@pytest.mark.parametrize("native_controller", [False, True, "legacy-popup-insets"], indirect=True)
def test_vertical_menu_preserves_entry_controls(native_controller: Any) -> None:
    """Keep entry controls visible while other actions use the compact menu."""
    c: Any = native_controller
    c.controls["daily"].setHidden_(True)
    c.controls["undo"].setEnabled_(False)
    c.window.setContentSize_((520, 800))
    c.layout()
    a: Any = c.adaptive_layout
    assert not a.compact_menu.isHidden()
    for key, control in c.controls.items():
        if isinstance(control, (AK.NSButton, AK.NSSegmentedControl)):
            is_entry: bool = key in ("order", "mode") or key.startswith("digit")
            assert bool(control.isHiddenOrHasHiddenAncestor()) != is_entry
    assert contains(a.support_scroll.contentView(), c.controls["order"])
    assert contains(a.support_scroll.contentView(), c.controls["digit9"])
    menu: Any = a.compact_menu.menu()
    assert menu.itemWithTitle_("Daily Game") is None
    assert not menu.itemWithTitle_("Undo").isEnabled()
    for key in ("new", "import", "restart", "hint", "fill", "auto_complete"):
        item: Any = menu.itemWithTitle_(c.controls[key].title())
        assert item.action() == c.controls[key].action()
        assert item.target() == c
    for title in ("Digit", "Entry order", "Entry mode"):
        assert menu.itemWithTitle_(title) is None
    assert contains(c.window.contentView(), c.board)
    c.window.setContentSize_((1120, 820))
    c.layout()
    assert a.compact_menu.isHidden()
    for key in ("new", "order", "mode", "hint", "digit1", "auto_complete"):
        assert not c.controls[key].isHiddenOrHasHiddenAncestor()


@pytest.mark.parametrize(("width", "height"), [(400, 720), (520, 800), (700, 1000)])
def test_vertical_entry_controls_and_board_fit(
    native_controller: Any, width: float, height: float
) -> None:
    """Show the entire keypad and board together before scrolling to further hint content."""
    c: Any = native_controller
    c.window.setContentSize_((width, height))
    c.layout()
    a: Any = c.adaptive_layout
    assert contains(c.window.contentView(), c.board)
    assert contains(a.support_scroll.contentView(), a.keypad)
    before: object = c.game.snapshot()
    c.save = Mock()
    c.refresh = Mock()
    c.controls["order"].setSelectedSegment_(1)
    c.orderChanged_(c.controls["order"])
    c.controls["mode"].setSelectedSegment_(1)
    c.modeChanged_(c.controls["mode"])
    assert c.preferences.input_order == "Number First"
    assert c.game.note_mode
    assert c.game.snapshot() == before


@pytest.mark.parametrize("notes", [False, True])
def test_color_mode_keyboard_entry_and_return_to_prior_mode(
    native_controller: Any, notes: bool
) -> None:
    """C restores either entry mode and keyboard painting includes a given cell."""
    c: Any = native_controller
    c.save = Mock()
    c.refresh = Mock()
    c.changed = Mock()
    c.game.note_mode = notes
    c.game.selected = 0

    def key(characters: str, flags: int = 0) -> Any:
        """Build the minimal native key event interface used by the board."""
        return SimpleNamespace(
            charactersIgnoringModifiers=lambda: characters,
            charactersByApplyingModifiers_=lambda modifiers: characters,
            modifierFlags=lambda: flags,
        )

    c.board.keyDown_(key("c"))
    assert c.game.color_mode and c.game.note_mode == notes
    c.board.keyDown_(key("3"))
    assert c.game.colors[0] == 3
    c.board.keyDown_(key(" "))
    assert c.game.colors[0] == 0
    c.board.keyDown_(key("\uf703", AK.NSEventModifierFlagShift))
    assert c.game.colors[:2] == [3, 3]
    c.board.flagsChanged_(key("", 0))
    assert len(c.game.undo_stack) == 3
    c.board.keyDown_(key("c"))
    assert not c.game.color_mode and c.game.note_mode == notes
    c.preferences.input_order = "Number First"
    c.board.keyDown_(key("c"))
    c.game.selected = 1
    c.board.keyDown_(key("4"))
    assert c.game.colors[1] == 3
    c.board.keyDown_(key("\r"))
    assert c.game.colors[1] == 4
    c.board.keyDown_(key("9"))
    c.board.keyDown_(key(" "))
    assert c.game.colors[1] == 0


def test_double_clear_is_undoable_without_confirmation(native_controller: Any) -> None:
    """The second consecutive 9 key clears all colors without opening an alert."""
    c: Any = native_controller
    c.save = Mock()
    c.refresh = Mock()
    c.changed = Mock()
    c.alert = Mock()
    c.game.color_mode = True
    c.game.active_color = 3
    c.game.paint_color(0)
    c.game.paint_color(1)
    c.game.selected = 0
    key: Any = SimpleNamespace(charactersIgnoringModifiers=lambda: "9", modifierFlags=lambda: 0)
    c.board.keyDown_(key)
    assert c.game.colors[:2] == [0, 3]
    c.alert.assert_not_called()
    c.board.keyDown_(key)
    assert not any(c.game.colors)
    c.alert.assert_not_called()
    assert c.game.undo()
    assert c.game.colors[:2] == [0, 3]


def test_clear_keypad_sequence_resets_after_another_color(native_controller: Any) -> None:
    """Number First keypad Clear removes all only after consecutive activations."""
    c: Any = native_controller
    c.save = Mock()
    c.refresh = Mock()
    c.changed = Mock()
    c.alert = Mock()
    c.preferences.input_order = "Number First"
    c.game.color_mode = True
    c.game.active_color = 2
    c.game.paint_color(1)
    c.select_digit(9, False)
    assert c.game.colors[1] == 2
    c.select_digit(3, False)
    c.select_digit(9, False)
    c.alert.assert_not_called()
    c.select_digit(9, False)
    assert not any(c.game.colors)
    c.alert.assert_not_called()


@pytest.mark.parametrize(
    ("color_mode", "note_mode"),
    [(False, False), (False, True), (True, False)],
)
def test_cell_menu_shows_all_modes(
    native_controller: Any, color_mode: bool, note_mode: bool
) -> None:
    """Keep all three actions available regardless of the visible input mode."""
    controller: Any = native_controller
    controller.game.color_mode = color_mode
    controller.game.note_mode = note_mode
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    menu: Any = context.build_menu()
    assert [item.title() for item in menu.itemArray()] == ["Answer", "Candidate", "Color"]
    assert all(item.isEnabled() for item in menu.itemArray())


@pytest.mark.parametrize("mode", ["Answer", "Candidate"])
def test_cell_menu_highlights_active_digit_independently_of_cell_marks(
    native_controller: Any, mode: str
) -> None:
    """Distinguish the active keypad digit from answers or notes already in a cell."""
    controller: Any = native_controller
    controller.game.active_digit = 7
    controller.game.notes[1] = {2, 7}
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    submenu: Any = context.build_menu().itemWithTitle_(mode).submenu()
    active: Any = submenu.itemAtIndex_(6)
    badge: Any = active.view()
    assert active.title() == "7"
    assert submenu.itemWithTitle_("7") == active
    assert badge.tag() == 7
    assert badge.frame().size.width <= submenu.size().width
    assert badge.frame().size.height >= 20
    assert badge.marked == (mode == "Candidate")
    assert submenu.itemAtIndex_(1).view() is None
    assert active.state() == (
        AK.NSControlStateValueOn if mode == "Candidate" else AK.NSControlStateValueOff
    )
    assert submenu.itemAtIndex_(1).state() == (
        AK.NSControlStateValueOn if mode == "Candidate" else AK.NSControlStateValueOff
    )


def test_active_digit_badge_follows_checked_number_column(native_controller: Any) -> None:
    """Keep the active square under native digits when another note has a checkmark."""
    controller: Any = native_controller
    controller.game.active_digit = 9
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)

    controller.game.notes[1] = set()
    unchecked: Any = context.digit_submenu("Candidate")
    unchecked.update()
    unchecked_badge: Any = unchecked.itemAtIndex_(8).view().badge_rect()

    controller.game.notes[1] = {5}
    checked: Any = context.digit_submenu("Candidate")
    checked.update()
    checked_badge: Any = checked.itemAtIndex_(8).view().badge_rect()
    column_width: float = checked.size().width - unchecked.size().width

    assert column_width > 0
    assert checked_badge.size.width == checked_badge.size.height == 20
    assert checked_badge.origin.x - unchecked_badge.origin.x == pytest.approx(column_width)
    assert checked_badge.origin.x + checked_badge.size.width <= checked.size().width
    assert checked.size().height == unchecked.size().height


def test_active_digit_badge_preserves_its_own_checkmark_space(native_controller: Any) -> None:
    """A checked active digit alone must still reserve room for its checkmark."""
    controller: Any = native_controller
    controller.game.active_digit = 5
    controller.game.notes[1] = {5}
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)

    highlighted: Any = context.digit_submenu("Candidate")
    controller.game.active_digit = 0
    plain: Any = context.digit_submenu("Candidate")
    highlighted.update()
    plain.update()

    badge: Any = highlighted.itemAtIndex_(4).view()
    square: Any = badge.badge_rect()
    assert badge.marked
    assert highlighted.size().width == plain.size().width
    assert highlighted.minimumWidth() == plain.size().width
    assert square.origin.x + square.size.width <= highlighted.size().width


@pytest.mark.parametrize("mode", ["Answer", "Candidate"])
@pytest.mark.parametrize("native_controller", [False, "legacy-menu-rows"], indirect=True)
def test_active_digit_badge_does_not_expand_menu(native_controller: Any, mode: str) -> None:
    """Keep normal number-menu width and row spacing with the square badge."""
    controller: Any = native_controller
    controller.game.notes[1] = {2, 7}
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    controller.game.active_digit = 7
    highlighted: Any = context.digit_submenu(mode)
    controller.game.active_digit = 0
    plain: Any = context.digit_submenu(mode)
    highlighted.update()
    plain.update()
    assert plain.size().width > 0 and plain.size().height > 0
    assert highlighted.minimumWidth() <= plain.size().width
    assert highlighted.size().width <= plain.size().width
    assert highlighted.size().height <= plain.size().height


@pytest.mark.parametrize("mode", ["Answer", "Candidate"])
def test_active_digit_badge_keeps_menu_action(native_controller: Any, mode: str) -> None:
    """The custom active row still enters an answer or toggles a candidate."""
    controller: Any = native_controller
    controller.changed = Mock()
    controller.game.active_digit = 4
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    submenu: Any = context.build_menu().itemWithTitle_(mode).submenu()
    submenu.itemAtIndex_(3).view().performClick_(None)
    if mode == "Answer":
        assert controller.game.values[1] == 4
    else:
        assert controller.game.notes[1] == {4}


def test_cell_menu_blocks_candidate_edits_on_filled_cells(native_controller: Any) -> None:
    """Keep coloring available while preventing notes on givens or answers."""
    controller: Any = native_controller
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 0)
    menu: Any = context.build_menu()
    assert not menu.itemWithTitle_("Candidate").isEnabled()
    assert menu.itemWithTitle_("Color").isEnabled()

    controller.game.set_value(1, 3)
    context.configure(controller.board, 1)
    menu = context.build_menu()
    assert not menu.itemWithTitle_("Candidate").isEnabled()
    assert menu.itemWithTitle_("Color").isEnabled()


def test_cell_menu_can_toggle_candidate_in_current_mode(native_controller: Any) -> None:
    """Keep candidate actions usable while Candidates is already selected."""
    controller: Any = native_controller
    controller.changed = Mock()
    controller.game.note_mode = True
    controller.game.notes[1].add(4)
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    candidate_menu: Any = context.build_menu().itemWithTitle_("Candidate").submenu()
    assert candidate_menu.itemAtIndex_(3).state() == AK.NSControlStateValueOn
    candidate_menu.performActionForItemAtIndex_(3)
    assert controller.game.notes[1] == set()
    assert controller.game.note_mode


@pytest.mark.parametrize(
    ("color_mode", "note_mode"),
    [(False, False), (False, True), (True, True)],
)
def test_cell_menu_edits_answer_and_candidate_without_switching_mode(
    native_controller: Any, color_mode: bool, note_mode: bool
) -> None:
    """Apply answer and candidate actions without changing the selected input mode."""
    controller: Any = native_controller
    controller.save = Mock()
    controller.refresh = Mock()
    controller.changed = Mock()
    controller.game.color_mode = color_mode
    controller.game.note_mode = note_mode
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    menu: Any = context.build_menu()
    candidate: Any = menu.itemWithTitle_("Candidate").submenu().itemAtIndex_(3)
    candidate.menu().performActionForItemAtIndex_(3)
    assert controller.game.notes[1] == {4}
    assert (controller.game.color_mode, controller.game.note_mode) == (color_mode, note_mode)
    assert controller.game.active_digit == 4
    assert controller.game.undo()
    assert controller.game.notes[1] == set()

    menu = context.build_menu()
    answer: Any = menu.itemWithTitle_("Answer").submenu().itemAtIndex_(2)
    answer.menu().performActionForItemAtIndex_(2)
    assert controller.game.values[1] == 3
    assert (controller.game.color_mode, controller.game.note_mode) == (color_mode, note_mode)
    assert controller.game.active_digit == 3
    assert controller.game.undo()
    assert controller.game.values[1] == 0


@pytest.mark.parametrize(
    ("color_mode", "note_mode"),
    [(False, False), (False, True), (True, True)],
)
def test_cell_color_menu_uses_three_by_three_grid_and_active_outline(
    native_controller: Any, color_mode: bool, note_mode: bool
) -> None:
    """Paint the clicked cell and outline the palette choice without switching modes."""
    controller: Any = native_controller
    controller.save = Mock()
    controller.refresh = Mock()
    controller.changed = Mock()
    controller.game.color_mode = color_mode
    controller.game.note_mode = note_mode
    controller.game.active_color = 5
    controller.game.colors[1] = 2
    context: Any = CellContextMenu.alloc().init()
    context.configure(controller.board, 1)
    menu: Any = context.build_menu()
    grid: Any = menu.itemWithTitle_("Color").submenu().itemAtIndex_(0).view()
    buttons: list[Any] = sorted(grid.subviews(), key=lambda button: button.tag())
    assert len(buttons) == 9
    assert all(button.focusRingType() == AK.NSFocusRingTypeNone for button in buttons)
    assert all(not button.shows_focus_outline for button in buttons)
    assert controller.controls["digit1"].shows_focus_outline
    assert [button.state() for button in buttons] == [
        AK.NSControlStateValueOn if color == 5 else AK.NSControlStateValueOff
        for color in range(1, 10)
    ]
    assert [button.frame().origin.x for button in buttons[:3]] == sorted(
        button.frame().origin.x for button in buttons[:3]
    )
    assert buttons[0].frame().origin.y == buttons[1].frame().origin.y
    assert buttons[3].frame().origin.y > buttons[0].frame().origin.y

    buttons[2].performClick_(None)
    assert controller.game.colors[1] == 3
    assert (controller.game.color_mode, controller.game.note_mode) == (color_mode, note_mode)
    assert controller.game.active_color == 3
    assert controller.game.undo()
    assert controller.game.colors[1] == 2

    menu = context.build_menu()
    grid = menu.itemWithTitle_("Color").submenu().itemAtIndex_(0).view()
    buttons = sorted(grid.subviews(), key=lambda button: button.tag())
    buttons[1].performClick_(None)
    assert controller.game.colors[1] == 0
    assert controller.game.active_color == 2
    assert (controller.game.color_mode, controller.game.note_mode) == (color_mode, note_mode)
    assert controller.game.undo()
    assert controller.game.colors[1] == 2


@pytest.mark.parametrize(
    "style", [AK.NSBezelStyleRounded, AK.NSBezelStyleTexturedRounded, AK.NSBezelStyleRegularSquare]
)
@pytest.mark.parametrize(("width", "height"), [(400, 600), (520, 800), (700, 1000), (1120, 820)])
def test_digit_tiles_have_gaps_between_actual_frames(
    native_controller: Any, width: float, height: float, style: int
) -> None:
    """Custom full-frame tiles must not overlap native button alignment margins."""
    c: Any = native_controller
    for digit in range(1, 10):
        c.controls[f"digit{digit}"].setBezelStyle_(style)
    c.window.setContentSize_((width, height))
    c.layout()
    grid: Any = c.adaptive_layout.digit_grid
    frames: list[Any] = [
        grid.convertRect_fromView_(
            c.controls[f"digit{digit}"].bounds(), c.controls[f"digit{digit}"]
        )
        for digit in range(1, 10)
    ]
    for index, frame in enumerate(frames):
        assert AK.NSMinX(frame) >= -0.5
        assert AK.NSMaxX(frame) <= grid.bounds().size.width + 0.5
        assert AK.NSMinY(frame) >= -0.5
        assert AK.NSMaxY(frame) <= grid.bounds().size.height + 0.5
        for other in frames[index + 1 :]:
            assert not AK.NSIntersectsRect(AK.NSInsetRect(frame, -1, -1), other)
