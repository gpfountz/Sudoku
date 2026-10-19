# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native macOS application shell and presentation controller."""

import os
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import AppKit as AK
import objc
from Foundation import NSBundle, NSObject, NSTimer
from PyObjCTools import AppHelper

from sudoku.board import SudokuBoard
from sudoku.catalog import Catalog, load_catalog
from sudoku.controls import (
    DigitButton,
    GlassChoiceControl,
    ThemeFocusOutline,
    ThemePopUpButton,
    ThemeSwitch,
    apply_action_theme,
    apply_native_accent,
    button_title,
)
from sudoku.daily import choose_daily_level
from sudoku.engine import cell_name
from sudoku.hint_types import HintLink
from sudoku.hints import Hint, HintStep, hint_steps, iter_hints
from sudoku.history import HistoryStore, hint_stage_key
from sudoku.history_ui import HistoryWindow, format_elapsed
from sudoku.import_session import replace_attempt
from sudoku.imported import is_imported
from sudoku.layout import MINIMUM_CONTENT_SIZE, AdaptiveLayout, fit_window_frame
from sudoku.legal import COPYRIGHT_NOTICE, license_text, third_party_text
from sudoku.model import LEVELS, Game, Preferences, Puzzle
from sudoku.puzzle_import import ValidatedImport
from sudoku.statistics_ui import StatisticsWindow
from sudoku.storage import SaveError, Store
from sudoku.theme import DEFAULT_THEME, Theme, theme_for_name
from sudoku.theme_names import THEME_NAMES
from sudoku.version import APP_VERSION


class AppController(NSObject):
    """Coordinate native controls, the independent model, and durable local saves."""

    game: Game
    preferences: Preferences
    theme: Theme = DEFAULT_THEME
    theme_labels: list[tuple[Any, bool]]
    store: Store
    history: HistoryStore
    history_window: HistoryWindow | None
    statistics_window: StatisticsWindow | None
    catalog: Catalog
    regular_game: Game
    daily_games: dict[str, Game]
    active_daily_date: str | None
    current_day: str
    window: Any
    adaptive_layout: AdaptiveLayout | None = None
    board: Any
    controls: dict[str, Any]
    settings_window: Any
    settings_controls: dict[str, Any]
    current_hint: Hint | None
    hint_stage: int
    hint_iterator: Iterator[Hint] | None
    hint_candidates: set[tuple[int, int]]
    hint_placements: set[tuple[int, int]]
    hint_focus: set[int]
    hint_removals: set[tuple[int, int]]
    hint_links: tuple[HintLink, ...] = ()
    last_tick: float
    last_save: float
    timer: Any
    save_problem: str = ""
    completion_shown: bool
    startup_failed: bool = True
    main_window_closing: bool = False
    clear_all_game: Game | None = None
    import_window: Any = None

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        """Load local state, construct the native window, and start the event loop timer."""
        directory: str | None = os.environ.get("SUDOKU_DATA_DIR")
        self.store = Store(Path(directory) if directory else None)
        self.history = HistoryStore(self.store.directory / "history.sqlite3")
        self.history_window = None
        self.statistics_window = None
        self.preferences = self.store.load_preferences()
        self.theme = theme_for_name(self.preferences.theme)
        try:
            self.catalog = load_catalog()
            restored: Game | None = self.store.load_game(self.catalog)
            self.regular_game = restored or self.store.start_game("Easy")
        except (SaveError, OSError, ValueError, sqlite3.Error) as error:
            self.alert("Cannot open regular puzzles", str(error))
            AK.NSApplication.sharedApplication().terminate_(None)
            return
        self.current_day = date.today().isoformat()
        self.daily_games = {}
        try:
            today_game: Game | None = self.store.load_daily_game(self.current_day, self.catalog)
            if today_game is not None:
                self.daily_games[self.current_day] = today_game
            self.active_daily_date = self.store.load_active_daily_date()
            if self.preferences.daily_enabled and self.active_daily_date:
                active_game: Game | None = self.daily_games.get(self.active_daily_date)
                if active_game is None:
                    active_game = self.store.load_daily_game(self.active_daily_date, self.catalog)
                if active_game is not None:
                    self.daily_games[self.active_daily_date] = active_game
                    self.game = active_game
                else:
                    self.active_daily_date = None
                    self.game = self.regular_game
            else:
                self.active_daily_date = None
                self.game = self.regular_game
        except SaveError as error:
            self.alert("Cannot restore daily game", str(error))
            self.active_daily_date = None
            self.game = self.regular_game
        self.controls = {}
        self.settings_controls = {}
        self.settings_window = None
        self.current_hint = None
        self.hint_stage = 0
        self.hint_iterator = None
        self.hint_candidates = set()
        self.hint_placements = set()
        self.hint_focus = set()
        self.hint_removals = set()
        self.save_problem = ""
        self.completion_shown = self.game.complete
        self.last_tick = self.last_save = time.monotonic()
        self.build_menu()
        self.build_window()
        self.refresh()
        self.startup_failed = False
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.board)
        AK.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        try:
            self.history.ensure_ready()
        except SaveError as error:
            self.alert("Cannot open history", str(error))
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True
        )
        self.save()
        if self.store.warnings:
            self.alert("Saved game recovery", "\n\n".join(self.store.warnings))
        if self.preferences.window_full_screen:
            self.performSelector_withObject_afterDelay_("restoreFullScreen:", None, 0.0)

    @objc.python_method
    def label(self, text: str, size: float = 13, secondary: bool = False) -> Any:
        """Create a native, noneditable label using system typography."""
        label: Any = AK.NSTextField.labelWithString_(text)
        label.setFont_(AK.NSFont.systemFontOfSize_(size))
        label.setTextColor_(self.theme.secondary_text if secondary else self.theme.text)
        self.theme_labels.append((label, secondary))
        return label

    @objc.python_method
    def button(self, title: str, action: str, parent: Any, key: str | None = None) -> Any:
        """Create a native glass action button without changing its action."""
        button: Any = AK.NSButton.buttonWithTitle_target_action_(title, self, action)
        button.setBezelStyle_(AK.NSBezelStyleGlass)
        parent.addSubview_(button)
        if key:
            self.controls[key] = button
        return button

    @objc.python_method
    def menu_item(
        self, menu: Any, title: str, action: str, key: str = "", shift: bool = False
    ) -> None:
        """Add a native menu command with an optional standard keyboard shortcut."""
        item: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        item.setTarget_(self)
        if shift:
            item.setKeyEquivalentModifierMask_(
                AK.NSEventModifierFlagCommand | AK.NSEventModifierFlagShift
            )
        menu.addItem_(item)

    @objc.python_method
    def build_menu(self) -> None:
        """Install app, game, edit, window, and help menus."""
        bar: Any = AK.NSMenu.alloc().init()
        menus: dict[str, Any] = {}
        for title in ("Sudoku", "Game", "Edit", "Window", "Help"):
            root: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            submenu: Any = AK.NSMenu.alloc().initWithTitle_(title)
            root.setSubmenu_(submenu)
            bar.addItem_(root)
            menus[title] = submenu
        self.menu_item(menus["Sudoku"], "About Sudoku", "about:")
        self.menu_item(menus["Sudoku"], "Settings…", "settings:", ",")
        menus["Sudoku"].addItem_(AK.NSMenuItem.separatorItem())
        self.menu_item(menus["Sudoku"], "Hide Sudoku", "hideApp:", "h")
        self.menu_item(menus["Sudoku"], "Quit Sudoku", "quitApp:", "q")
        for title, action, key in (
            ("New Game…", "newGame:", "n"),
            ("Import Puzzle…", "importPuzzle:", "i"),
            ("Daily Game", "dailyGames:", "d"),
            ("Return to Regular Game", "returnRegular:", ""),
            ("Restart…", "restart:", ""),
            ("Pause / Resume", "pause:", "p"),
            ("Hint", "hint:", "j"),
            ("History…", "history:", ""),
            ("Statistics…", "statistics:", ""),
            ("Recover Saving…", "recover:", ""),
        ):
            if action in ("dailyGames:", "returnRegular:") and not self.preferences.daily_enabled:
                continue
            self.menu_item(menus["Game"], title, action, key)
        self.menu_item(menus["Edit"], "Undo", "undo:", "z")
        self.menu_item(menus["Edit"], "Redo", "redo:", "z", True)
        self.menu_item(menus["Edit"], "Erase Cell", "erase:")
        self.menu_item(menus["Edit"], "Fill Legal Candidates", "fill:", "f")
        self.menu_item(menus["Edit"], "Auto Complete Singles", "autoComplete:", "a")
        self.menu_item(menus["Edit"], "Toggle Candidates", "toggleNotes:")
        self.menu_item(menus["Edit"], "Toggle Color Mode", "toggleColor:")
        self.menu_item(menus["Window"], "Minimize", "minimize:", "m")
        self.menu_item(menus["Window"], "Close", "closeWindow:", "w")
        self.menu_item(menus["Help"], "Keyboard & Trackpad Guide", "help:", "?")
        AK.NSApplication.sharedApplication().setMainMenu_(bar)
        AK.NSApplication.sharedApplication().setWindowsMenu_(menus["Window"])

    @objc.python_method
    def build_window(self) -> None:
        """Construct the game window with a board and native control sidebar."""
        style: int = (
            AK.NSWindowStyleMaskTitled
            | AK.NSWindowStyleMaskClosable
            | AK.NSWindowStyleMaskMiniaturizable
            | AK.NSWindowStyleMaskResizable
        )
        self.window = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 960, 780), style, AK.NSBackingStoreBuffered, False
        )
        self.window.setTitle_(os.environ.get("SUDOKU_WINDOW_TITLE", "Sudoku"))
        self.window.setContentMinSize_(MINIMUM_CONTENT_SIZE)
        self.window.setReleasedWhenClosed_(False)
        self.window.center()
        autosave_name: str = os.environ.get("SUDOKU_WINDOW_AUTOSAVE_NAME", "SudokuMainWindow")
        self.window.setFrameUsingName_(autosave_name)
        screen: Any = self.window.screen() or AK.NSScreen.mainScreen()
        if screen is not None:
            frame: Any = self.window.frame()
            visible: Any = screen.visibleFrame()
            restored: tuple[float, float, float, float] = fit_window_frame(
                (frame.origin.x, frame.origin.y, frame.size.width, frame.size.height),
                (visible.origin.x, visible.origin.y, visible.size.width, visible.size.height),
            )
            self.window.setFrame_display_(AK.NSMakeRect(*restored), False)
        self.window.setFrameAutosaveName_(autosave_name)
        self.window.setDelegate_(self)
        content: Any = self.window.contentView()
        self.theme_labels = []
        for key, label_text, size, secondary in (
            ("title", "Sudoku", 30, False),
            ("subtitle", "", 13, True),  # Daily Game  ·  Hard  ·  0/81 filled
            ("input_label", "ENTRY ORDER", 10, True),
            ("palette_label", "", 12, True),
            ("hint_title", "A little help", 17, False),
            ("status", "", 12, True),  # Solved. Nicely done!
            ("timer", "", 13, True),
            ("footer", "", 11, True),  # drag or shift + arrows...
        ):
            self.controls[key] = self.label(label_text, size, secondary)
            content.addSubview_(self.controls[key])
        icon_path: str = NSBundle.mainBundle().pathForResource_ofType_("Sudoku", "icns") or str(
            Path(__file__).resolve().parent.parent / "resources" / "Sudoku.icns"
        )
        icon: Any = AK.NSImageView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 56, 56))
        icon.setImage_(AK.NSImage.alloc().initWithContentsOfFile_(icon_path))
        icon.setImageScaling_(AK.NSImageScaleProportionallyUpOrDown)
        icon.setAccessibilityElement_(False)
        content.addSubview_(icon)
        self.controls["app_icon"] = icon
        self.controls["title"].setFont_(
            AK.NSFont.systemFontOfSize_weight_(30, AK.NSFontWeightSemibold)
        )
        level_picker: Any = ThemePopUpButton.alloc().initWithFrame_pullsDown_(
            AK.NSMakeRect(0, 0, 110, 24), False
        )
        level_picker.addItemsWithTitles_(list(LEVELS))
        level_picker.setControlSize_(AK.NSControlSizeSmall)
        level_picker.setFont_(AK.NSFont.systemFontOfSize_(13))
        level_picker.setTarget_(self)
        level_picker.setAction_("changeImportedLevel:")
        level_picker.setHidden_(True)
        level_picker.setToolTip_("Choose this imported puzzle’s level")
        level_picker.setAccessibilityLabel_("Imported puzzle level")
        self.controls["import_level"] = level_picker
        self.board = SudokuBoard.alloc().initWithFrame_(AK.NSMakeRect(24, 110, 590, 590))
        self.board.controller = self
        content.addSubview_(self.board)
        self.button("New Game…", "newGame:", content, "new")
        self.button("Daily Game", "dailyGames:", content, "daily")
        self.button("Import Game", "importPuzzle:", content, "import")
        self.button("Restart…", "restart:", content, "restart")
        self.button("Pause", "pause:", content, "pause")
        for key, title, action in (
            ("undo", "Undo", "undo:"),
            ("redo", "Redo", "redo:"),
            ("erase", "Erase", "erase:"),
            ("fill", "Fill Candidates", "fill:"),
            ("auto_complete", "Auto Complete", "autoComplete:"),
        ):
            self.button(title, action, content, key)
        for key, labels, action in (
            ("order", ["Cell First", "Number First"], "orderChanged:"),
            ("mode", ["Answers", "Candidates", "Color"], "modeChanged:"),
        ):
            control: Any = GlassChoiceControl.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 260, 28))
            control.configure(labels, self, action)
            content.addSubview_(control)
            self.controls[key] = control
        for digit in range(1, 10):
            button: Any = DigitButton.buttonWithTitle_target_action_(str(digit), self, "digit:")
            button.theme = self.theme
            content.addSubview_(button)
            self.controls[f"digit{digit}"] = button
            button.setTag_(digit)
            button.setFont_(AK.NSFont.systemFontOfSize_(24))
            button.setButtonType_(AK.NSButtonTypePushOnPushOff)
            button.setAccessibilityLabel_(f"Digit {digit}")
        scroll: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 230, 150))
        scroll.setHasVerticalScroller_(True)
        scroll.setDrawsBackground_(False)
        text: Any = AK.NSTextView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 220, 150))
        text.setEditable_(False)
        text.setSelectable_(True)
        text.setDrawsBackground_(False)
        text.setFont_(AK.NSFont.systemFontOfSize_(13))
        text.setTextColor_(self.theme.secondary_text)
        text.setTextContainerInset_((0, 4))
        text.setVerticallyResizable_(True)
        text.setHorizontallyResizable_(False)
        text.setAutoresizingMask_(AK.NSViewWidthSizable)
        text.textContainer().setWidthTracksTextView_(True)
        scroll.setDocumentView_(text)
        content.addSubview_(scroll)
        self.controls["hint_scroll"] = scroll
        self.controls["hint_text"] = text
        self.button("Get Hint", "hint:", content, "hint")
        self.button("Apply", "applyHint:", content, "apply_hint")
        self.button("Show Another Hint", "anotherHint:", content, "another_hint")
        self.button("Back", "previousHint:", content, "previous_hint")
        self.button("Reveal Selected Cell…", "reveal:", content, "reveal")
        self.controls["reveal"].setHidden_(True)
        self.controls["daily"].setHidden_(not self.preferences.daily_enabled)
        self.adaptive_layout = AdaptiveLayout(self.window, self.board, self.controls)
        self.layout()
        self.apply_appearance()

    @objc.python_method
    def layout(self) -> None:
        """Adapt native panel arrangements to the current content viewport."""
        if self.adaptive_layout is not None:
            self.adaptive_layout.update()

    def windowDidResize_(self, notification: Any) -> None:
        """Relayout game controls when the main window changes size."""
        if notification.object() == self.window:
            self.layout()

    @objc.python_method
    def remember_full_screen(self, full_screen: bool) -> None:
        """Persist a changed main-window mode through the existing save/error handling."""
        if not self.startup_failed and self.preferences.window_full_screen != full_screen:
            self.preferences.window_full_screen = full_screen
            self.save()

    @objc.python_method
    def capture_full_screen(self) -> None:
        """Capture the live mode before closing or quitting can change the window style."""
        if not self.main_window_closing:
            self.remember_full_screen(
                bool(self.window.styleMask() & AK.NSWindowStyleMaskFullScreen)
            )

    def restoreFullScreen_(self, sender: Any) -> None:
        """Restore the saved mode after launch has made the main window visible."""
        if (
            not self.startup_failed
            and not self.main_window_closing
            and self.preferences.window_full_screen
            and self.window.isVisible()
            and not self.window.styleMask() & AK.NSWindowStyleMaskFullScreen
        ):
            self.window.toggleFullScreen_(None)

    def windowDidEnterFullScreen_(self, notification: Any) -> None:
        """Remember successful full-screen entry for the game window only."""
        if notification.object() == self.window and not self.main_window_closing:
            self.remember_full_screen(True)

    def windowDidExitFullScreen_(self, notification: Any) -> None:
        """Remember deliberate exits while ignoring the exit caused by closing the window."""
        if notification.object() == self.window and not self.main_window_closing:
            self.remember_full_screen(False)

    def windowDidFailToEnterFullScreen_(self, window: Any) -> None:
        """Fall back to normal window mode if macOS rejects full-screen entry."""
        if window == self.window and not self.main_window_closing:
            self.remember_full_screen(False)

    def windowShouldClose_(self, window: Any) -> bool:
        """Keep the game window's last mode through native full-screen close transitions."""
        if window == self.window:
            self.capture_full_screen()
            self.main_window_closing = True
        return True

    @objc.python_method
    def apply_appearance(self) -> None:
        """Apply a window override or inherit the live system appearance."""
        names: dict[str, str] = {
            "Light": AK.NSAppearanceNameAqua,
            "Dark": AK.NSAppearanceNameDarkAqua,
        }
        appearance: Any = (
            AK.NSAppearance.appearanceNamed_(names[self.preferences.appearance])
            if self.preferences.appearance in names
            else None
        )
        self.window.setAppearance_(appearance)
        if self.settings_window:
            self.settings_window.setAppearance_(appearance)
        self.apply_theme(self.theme)

    @objc.python_method
    def apply_theme(self, theme: Theme) -> None:
        """Refresh theme-aware views without changing the appearance preference."""
        self.theme = theme
        self.window.setBackgroundColor_(
            theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        self.apply_settings_theme()
        for label, secondary in self.theme_labels:
            label.setTextColor_(theme.secondary_text if secondary else theme.text)
        self.controls["hint_text"].setTextColor_(theme.secondary_text)
        self.controls["palette_label"].setStringValue_(self.palette_status_text(self.game))
        for key in ("order", "mode"):
            self.controls[key].apply_theme(theme)
        for key, control in self.controls.items():
            if (
                key != "import_level"
                and isinstance(control, AK.NSButton)
                and not isinstance(control, DigitButton)
            ):
                apply_action_theme(control, theme)
        self.controls["import_level"].apply_theme(theme)
        if self.adaptive_layout:
            apply_action_theme(self.adaptive_layout.compact_menu, theme)
        for digit in range(1, 10):
            button: Any = self.controls[f"digit{digit}"]
            button.theme = theme
            button.setAccessibilityLabel_(self.digit_accessibility_label(self.game, digit))
            button.setNeedsDisplay_(True)
        self.board.pencil_cursor = None
        if self.board.cursor_is_candidate:
            self.window.invalidateCursorRectsForView_(self.board)
        self.board.setNeedsDisplay_(True)
        for auxiliary in (
            getattr(self, "history_window", None),
            getattr(self, "statistics_window", None),
            self.import_window,
        ):
            if auxiliary is not None and not getattr(auxiliary, "closed", False):
                auxiliary.apply_theme(theme, self.window.appearance())

    @objc.python_method
    def apply_settings_theme(self) -> None:
        """Recolor open Settings, retaining preference values and native control behavior."""
        if not self.settings_window:
            return
        self.settings_window.setBackgroundColor_(
            self.theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        for control in self.settings_controls.values():
            if isinstance(control, (ThemeSwitch, ThemePopUpButton)):
                control.apply_theme(self.theme)

    @objc.python_method
    def palette_status_text(self, game: Game) -> str:
        """Describe the active entry using the current theme's color names."""
        if game.color_mode:
            color_name: str = (
                self.theme.annotations.name(game.active_color) if game.active_color < 9 else "Clear"
            )
            return f"Color  {color_name}"
        mode: str = "Candidate" if game.note_mode else "Active digit"
        return f"{mode}  {game.active_digit}"

    @objc.python_method
    def digit_accessibility_label(self, game: Game, digit: int) -> str:
        """Name a keypad tile consistently with the active color palette."""
        if not game.color_mode:
            return f"Digit {digit}"
        return f"Color {self.theme.annotations.name(digit)}" if digit < 9 else "Clear cell color"

    @objc.python_method
    def refresh(self) -> None:
        """Reflect current state in native controls without modifying the game."""
        game: Game = self.game
        filled: int = sum(bool(value) for value in game.values)
        editable_level: bool = self.can_change_import_level()
        level_picker: Any = self.controls["import_level"]
        level_picker.setHidden_(not editable_level)
        level_picker.selectItemWithTitle_(game.puzzle.level)
        if self.active_daily_date:
            daily_day: date = date.fromisoformat(self.active_daily_date)
            self.controls["title"].setStringValue_("Daily Game")
            self.controls["subtitle"].setStringValue_(
                f"{self.format_daily_date(daily_day)}  ·  {game.puzzle.level}  ·  "
                f"{filled}/81 filled"
            )
        else:
            self.controls["title"].setStringValue_("Sudoku")
            rating_text: str = (
                f"Rating {game.puzzle.rating:.1f}"
                if game.puzzle.rating is not None
                else f"Imported · {game.puzzle.identifier}"
            )
            level_prefix: str = "" if editable_level else f"{game.puzzle.level}  "
            self.controls["subtitle"].setStringValue_(
                f"{level_prefix}·  {rating_text}  ·  {filled}/81 filled"
            )
        self.controls["order"].setSelectedSegment_(
            0 if self.preferences.input_order == "Cell First" else 1
        )
        self.controls["mode"].setSelectedSegment_(
            2 if game.color_mode else 1 if game.note_mode else 0
        )
        self.controls["palette_label"].setStringValue_(self.palette_status_text(game))
        self.controls["pause"].setTitle_("Resume" if game.paused else "Pause")
        can_play: bool = not game.paused and not game.complete
        self.controls["pause"].setEnabled_(not game.complete)
        self.controls["daily"].setHidden_(not self.preferences.daily_enabled)
        today_game: Game | None = self.daily_games.get(date.today().isoformat())
        self.controls["daily"].setEnabled_(
            self.preferences.daily_enabled
            and (
                not self.store.daily_game_exists(date.today().isoformat())
                or (today_game is not None and not today_game.complete)
            )
        )
        self.controls["timer"].setHidden_(not self.preferences.show_timer)
        self.refresh_timer()
        self.controls["undo"].setEnabled_(bool(game.undo_stack) and can_play)
        self.controls["redo"].setEnabled_(bool(game.redo_stack) and not game.paused)
        self.controls["erase"].setEnabled_(
            can_play
            and (
                game.color_mode or game.can_edit_answer(game.selected, self.preferences.error_check)
            )
        )
        for key in ("mode", "order"):
            self.controls[key].setEnabled_(not game.paused)
        for key in ("fill", "auto_complete", "hint"):
            self.controls[key].setEnabled_(can_play)
        self.controls["apply_hint"].setEnabled_(
            self.current_hint is not None
            and self.hint_stage == len(hint_steps(game, self.current_hint))
            and can_play
        )
        self.controls["hint"].setTitle_("Next Step" if self.current_hint else "Get Hint")
        self.controls["hint"].setEnabled_(
            can_play
            and (
                not self.current_hint or self.hint_stage < len(hint_steps(game, self.current_hint))
            )
        )
        self.controls["another_hint"].setEnabled_(can_play and bool(self.current_hint))
        self.controls["another_hint"].setHidden_(not self.controls["reveal"].isHidden())
        self.controls["previous_hint"].setEnabled_(can_play and self.hint_stage > 1)
        completed: frozenset[int] = game.completed_digits
        for digit in range(1, 10):
            button: Any = self.controls[f"digit{digit}"]
            button.set_color_mode(game.color_mode, digit)
            button.setTitle_("Clear" if game.color_mode and digit == 9 else str(digit))
            button.setAccessibilityLabel_(self.digit_accessibility_label(game, digit))
            self.controls[f"digit{digit}"].setState_(
                AK.NSControlStateValueOn
                if digit == (game.active_color if game.color_mode else game.active_digit)
                else AK.NSControlStateValueOff
            )
            self.controls[f"digit{digit}"].setEnabled_(not game.paused)
            self.controls[f"digit{digit}"].set_dimmed(
                not game.color_mode and self.preferences.dim_completed_digits and digit in completed
            )
            self.controls[f"digit{digit}"].setAccessibilityHelp_(
                "Nine or more filled cells contain this digit; still selectable."
                if not game.color_mode
                and self.preferences.dim_completed_digits
                and digit in completed
                else ""
            )
        footer: str
        if game.color_mode:
            footer = "Drag or Shift + arrows paint colors"
        elif game.note_mode:
            footer = "Notes: drag or Shift + arrows"
        elif self.preferences.drag_answers_as_candidates:
            footer = "Drag or Shift + arrows paint candidates"
        else:
            footer = "N toggles candidate entry"
        self.controls["footer"].setStringValue_(footer)
        mode_name: str = (
            "Color" if game.color_mode else "Candidates" if game.note_mode else "Answers"
        )
        status: str = self.save_problem or (
            "Paused — board hidden"
            if game.paused
            else "Solved. Nicely done!"
            if game.complete
            else f"{cell_name(game.selected).capitalize()}  ·  "
            f"{mode_name}  ·  {self.preferences.input_order}"
        )
        self.controls["status"].setStringValue_(status)
        if not self.current_hint and not self.controls["reveal"].isHidden():
            pass
        elif not self.current_hint:
            self.controls["hint_text"].setString_(
                "Stuck? Ask for a nudge, then reveal the reasoning when you’re ready.\n\n"
                "Hints use your current board. You choose whether to apply them."
            )
        self.layout()
        self.board.update_cursor()
        self.board.setNeedsDisplay_(True)

    @objc.python_method
    def save(self) -> None:
        """Persist progress and keep failures visible without interrupting play repeatedly."""
        try:
            if self.active_daily_date:
                self.daily_games[self.active_daily_date] = self.game
                self.store.save_daily_game(self.active_daily_date, self.game)
            else:
                self.regular_game = self.game
            self.store.save_game(self.regular_game)
            self.store.save_active_daily_date(self.active_daily_date)
            self.store.save_preferences(self.preferences)
            if self.game.complete and self.game.solved_at is not None:
                self.history.record_completion(self.game, self.active_daily_date)
            self.save_problem = ""
        except SaveError as error:
            self.save_problem = str(error)
        self.last_save = time.monotonic()

    @objc.python_method
    def clear_hint(self) -> None:
        """Invalidate a displayed deduction after any board mutation."""
        self.current_hint = None
        self.hint_stage = 0
        self.hint_iterator = None
        self.hint_candidates = set()
        self.hint_placements = set()
        self.hint_focus.clear()
        self.hint_removals.clear()
        self.hint_links = ()
        self.controls["reveal"].setHidden_(True)

    @objc.python_method
    def changed(self, save: bool = True) -> None:
        """Invalidate stale hints, save complete edits, and announce completion."""
        self.clear_hint()
        if self.game.complete and not self.completion_shown and self.game.solved_at is None:
            self.game.solved_at = datetime.now(UTC).isoformat()
        if save:
            self.save()
        self.refresh()
        if self.game.complete and not self.completion_shown:
            self.completion_shown = True
            self.alert(
                "Puzzle complete",
                f"Level: {self.game.puzzle.level}\n"
                f"Time: {format_elapsed(self.game.elapsed)}\n"
                f"Hints: {len(self.game.viewed_hint_stages)}  ·  "
                f"Reveals: {len(self.game.revealed_cells)}\n"
                f"Incorrect answers: {len(self.game.incorrect_entries)}",
            )
        elif not self.game.complete:
            self.completion_shown = False

    @objc.python_method
    def refresh_timer(self) -> None:
        """Update visible elapsed time only when its displayed value changes."""
        if not self.preferences.show_timer:
            return
        seconds: int = int(self.game.elapsed)
        text: str = (
            f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"
            if seconds >= 3600
            else f"{seconds // 60:02}:{seconds % 60:02}"
        )
        label: Any = self.controls["timer"]
        if label.stringValue() != text:
            label.setStringValue_(text)

    def tick_(self, timer: Any) -> None:
        """Count active foreground play and periodically persist elapsed time."""
        now: float = time.monotonic()
        if (
            not self.game.paused
            and not self.game.complete
            and AK.NSApplication.sharedApplication().isActive()
            and not self.window.isMiniaturized()
        ):
            self.game.elapsed += min(now - self.last_tick, 2.0)
        self.last_tick = now
        previous_save_problem: str = self.save_problem
        if now - self.last_save >= 10 and self.game._group is None:
            self.save()
        day_changed: bool = self.update_current_day()
        if day_changed or self.save_problem != previous_save_problem:
            self.refresh()
        else:
            self.refresh_timer()

    def digit_(self, sender: Any) -> None:
        """Choose a digit; Shift-click bypasses cell-first answer or candidate entry."""
        event: Any = AK.NSApplication.sharedApplication().currentEvent()
        select_only: bool = bool(event and event.modifierFlags() & AK.NSEventModifierFlagShift)
        self.select_digit(sender.tag(), select_only)

    def selectDigit_(self, sender: Any) -> None:
        """Select a keypad digit without entering an answer or candidate."""
        self.select_digit(sender.tag(), True)

    @objc.python_method
    def select_digit(self, digit: int, select_only: bool) -> None:
        """Share keypad selection and optional cell entry across mouse actions."""
        self.board.finish_gesture()
        if self.game.color_mode:
            if digit == 9 and not select_only and self.clear_all_game is self.game:
                self.clear_all_game = None
                if self.game.clear_all_colors():
                    self.changed()
                self.refresh()
                self.window.makeFirstResponder_(self.board)
                return
            self.clear_all_game = self.game if digit == 9 and not select_only else None
            self.game.active_color = digit
        else:
            self.clear_all_game = None
            self.game.active_digit = digit
        if self.preferences.input_order == "Cell First" and not select_only:
            if self.game.color_mode:
                self.game.paint_color(self.game.selected)
            elif self.game.note_mode:
                self.game.mark(self.game.selected, self.game.active_digit)
            else:
                self.game.set_value(
                    self.game.selected,
                    self.game.active_digit,
                    self.preferences.cleanup_notes,
                    error_check=self.preferences.error_check,
                )
            self.changed()
        else:
            self.save()
        self.refresh()
        self.window.makeFirstResponder_(self.board)

    def orderChanged_(self, sender: Any) -> None:
        """Persist the input-order preference and restore board focus."""
        self.clear_all_game = None
        self.preferences.input_order = (
            "Cell First" if sender.selectedSegment() == 0 else "Number First"
        )
        self.save()
        self.refresh()
        self.window.makeFirstResponder_(self.board)

    def modeChanged_(self, sender: Any) -> None:
        """Select answers, candidates, or colors without losing the prior entry mode."""
        self.clear_all_game = None
        selected: int = sender.selectedSegment()
        self.board.finish_gesture()
        self.game.color_mode = selected == 2
        if selected != 2:
            self.game.note_mode = selected == 1
        self.save()
        self.refresh()
        self.window.makeFirstResponder_(self.board)

    def toggleNotes_(self, sender: Any) -> None:
        """Toggle pencil mode using the keyboard or Edit menu."""
        if not self.game.paused:
            self.clear_all_game = None
            self.board.finish_gesture()
            self.game.color_mode = False
            self.game.note_mode = not self.game.note_mode
            self.save()
            self.refresh()

    def toggleColor_(self, sender: Any) -> None:
        """Enter or leave Color mode, restoring the prior answer or candidate mode."""
        if not self.game.paused:
            self.clear_all_game = None
            self.board.finish_gesture()
            self.game.color_mode = not self.game.color_mode
            self.save()
            self.refresh()
            self.window.makeFirstResponder_(self.board)

    def undo_(self, sender: Any) -> None:
        """Undo the most recent board action and refocus the game."""
        self.clear_all_game = None
        if self.game.undo():
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def redo_(self, sender: Any) -> None:
        """Redo the most recently undone board action."""
        self.clear_all_game = None
        if self.game.redo():
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def erase_(self, sender: Any) -> None:
        """Clear the selected cell's color or editable answer and notes."""
        self.clear_all_game = None
        changed: bool = (
            self.game.paint_color(self.game.selected, "remove")
            if self.game.color_mode
            else self.game.clear(self.game.selected, error_check=self.preferences.error_check)
        )
        if changed:
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def fill_(self, sender: Any) -> None:
        """Explicitly fill legal pencil marks with a single undoable action."""
        if self.game.fill_candidates():
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def autoComplete_(self, sender: Any) -> None:
        """Apply logical singles and correct lone pencil marks as one undoable action."""
        self.board.finish_gesture()
        if self.game.wrong_answers():
            self.alert(
                "Check your entries first",
                "Auto Complete stopped because at least one entered answer is incorrect.",
            )
        else:
            completed: int = self.game.auto_complete_singles(self.preferences.cleanup_notes)
            if completed:
                self.changed()
            else:
                self.alert(
                    "No singles available",
                    "No singles follow from the current answers, and no empty cell has "
                    "a lone pencil mark that matches this puzzle’s solution.",
                )
        self.window.makeFirstResponder_(self.board)

    def pause_(self, sender: Any) -> None:
        """Hide or restore the board and stop or resume elapsed play time."""
        self.board.finish_gesture()
        self.game.paused = not self.game.paused
        self.last_tick = time.monotonic()
        self.clear_hint()
        self.save()
        self.refresh()
        self.window.makeFirstResponder_(self.board)

    @objc.python_method
    def alert(self, title: str, message: str, buttons: tuple[str, ...] = ("OK",)) -> int:
        """Display a native modal message and return the chosen button index."""
        alert: Any = self.build_message_dialog(title, message, buttons)
        return int(alert.runModal()) - AK.NSAlertFirstButtonReturn

    @objc.python_method
    def build_message_dialog(
        self, title: str, message: str, buttons: tuple[str, ...] = ("OK",)
    ) -> Any:
        """Prepare a themed message dialog, including the puzzle completion summary."""
        alert: Any = AK.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        for button in buttons:
            alert.addButtonWithTitle_(button)
        self.apply_alert_theme(alert)
        return alert

    @objc.python_method
    def apply_alert_theme(self, alert: Any) -> None:
        """Theme modal surfaces, primary buttons, and focus while retaining native actions."""
        alert.window().setAppearance_(self.window.appearance())
        alert.window().setBackgroundColor_(
            self.theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        alert.layout()
        if self.theme is DEFAULT_THEME:
            return
        for button in alert.buttons():
            primary: bool = button.keyEquivalent() == "\r"
            if self.theme.high_contrast:
                button.setBezelStyle_(AK.NSBezelStyleRounded)
                button.setBezelColor_(self.theme.controls.background)
            if primary:
                # Modern NSAlert default buttons ignore bezelColor; tint native rendering.
                button.setBezelColor_(None)
                apply_native_accent(button, self.theme)
            button.setAttributedTitle_(
                button_title(
                    button, self.theme.controls.selected_text if primary else self.theme.text
                )
            )
            button.setFocusRingType_(AK.NSFocusRingTypeNone)
            outline: Any = ThemeFocusOutline.alloc().initWithFrame_(button.bounds())
            outline.theme = self.theme
            outline.tints_button = primary
            outline.setAutoresizingMask_(AK.NSViewWidthSizable | AK.NSViewHeightSizable)
            outline.setAccessibilityElement_(False)
            button.addSubview_(outline)

    @objc.python_method
    def build_help_dialog(self, message: str) -> Any:
        """Keep the guide within the visible screen and scroll its full text."""
        return self.build_text_dialog(
            "Keyboard & Trackpad Guide", message, "Keyboard and trackpad guide"
        )

    @objc.python_method
    def build_text_dialog(self, title: str, message: str, accessibility_label: str) -> Any:
        """Present selectable, scrolling reference text in a themed native dialog."""
        screen: Any = self.window.screen() or AK.NSScreen.mainScreen()
        visible_width: float = float(screen.visibleFrame().size.width) if screen else 900.0
        visible_height: float = float(screen.visibleFrame().size.height) if screen else 700.0
        width: float = min(640.0, max(360.0, visible_width - 120.0))
        height: float = min(430.0, max(240.0, visible_height - 220.0))
        scroll: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, width, height))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setScrollerStyle_(AK.NSScrollerStyleLegacy)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)

        content_width: float = float(scroll.contentSize().width)
        text: Any = AK.NSTextView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, content_width, height))
        text.setEditable_(False)
        text.setSelectable_(True)
        text.setDrawsBackground_(False)
        text.setFont_(AK.NSFont.systemFontOfSize_(14))
        text.setTextColor_(self.theme.text)
        text.setTextContainerInset_((6, 6))
        text.setVerticallyResizable_(True)
        text.setHorizontallyResizable_(False)
        text.setAutoresizingMask_(AK.NSViewWidthSizable)
        text.textContainer().setWidthTracksTextView_(True)
        text.textContainer().setContainerSize_((content_width, 1_000_000))
        text.setAccessibilityLabel_(accessibility_label)
        scroll.setDocumentView_(text)
        text.setString_(message)
        text.layoutManager().ensureLayoutForTextContainer_(text.textContainer())
        used_height: float = float(
            text.layoutManager().usedRectForTextContainer_(text.textContainer()).size.height
        )
        text.setFrameSize_((content_width, max(height, used_height + 12)))

        alert: Any = AK.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setAccessoryView_(scroll)
        alert.addButtonWithTitle_("OK")
        self.apply_alert_theme(alert)
        return alert

    @objc.python_method
    def can_change_import_level(self) -> bool:
        """Allow difficulty edits only for an unfinished import with its own puzzle identity."""
        return (
            self.active_daily_date is None
            and is_imported(self.game.puzzle.identifier)
            and not self.game.complete
        )

    def changeImportedLevel_(self, sender: Any) -> None:
        """Save an inline difficulty selection without replacing the imported attempt."""
        if not self.can_change_import_level():
            return
        level: str = str(sender.titleOfSelectedItem())
        if level not in LEVELS or level == self.game.puzzle.level:
            sender.selectItemWithTitle_(self.game.puzzle.level)
            return
        self.board.finish_gesture()
        try:
            self.store.imported.change_level(self.game, level)
        except SaveError as error:
            sender.selectItemWithTitle_(self.game.puzzle.level)
            self.alert("Cannot change imported puzzle level", str(error))
        else:
            self.save()
            self.refresh()
        finally:
            self.window.makeFirstResponder_(self.board)

    @objc.python_method
    def build_new_game_dialog(self) -> Any:
        """Build the themed difficulty dialog without starting or abandoning a game."""
        alert: Any = AK.NSAlert.alloc().init()
        alert.setMessageText_("New Sudoku")
        alert.setInformativeText_(
            "Choose a difficulty for a new regular puzzle. Your daily progress will remain saved."
            if self.active_daily_date
            else "Choose a difficulty. Your unfinished regular game will remain saved."
            if not self.regular_game.complete
            else "Choose a difficulty for your next puzzle."
        )
        popup: Any = ThemePopUpButton.alloc().initWithFrame_pullsDown_(
            AK.NSMakeRect(0, 0, 250, 32), False
        )
        popup.addItemsWithTitles_(list(LEVELS))
        popup.selectItemWithTitle_(self.regular_game.puzzle.level)
        popup.setAccessibilityLabel_("Puzzle difficulty")
        popup.apply_theme(self.theme)
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Start Game")
        alert.addButtonWithTitle_("Cancel")
        self.apply_alert_theme(alert)
        return alert

    def newGame_(self, sender: Any) -> None:
        """Choose a difficulty and end the regular attempt being replaced."""
        self.board.finish_gesture()
        self.save()
        if self.save_problem:
            self.alert("Cannot start a puzzle", self.save_problem)
            return
        alert: Any = self.build_new_game_dialog()
        popup: Any = alert.accessoryView()
        if alert.runModal() == AK.NSAlertFirstButtonReturn:
            abandoned: bool = False
            try:
                if not self.regular_game.complete:
                    abandoned = self.history.record_outcome(
                        self.regular_game, "Abandoned", datetime.now(UTC).isoformat()
                    )
                next_game: Game = self.store.start_game(str(popup.titleOfSelectedItem()))
            except SaveError as error:
                if abandoned:
                    self.history.remove_outcome(self.regular_game.attempt_id)
                self.alert("Cannot start a puzzle", str(error))
                return
            self.regular_game = next_game
            self.active_daily_date = None
            self.game = self.regular_game
            self.last_tick = time.monotonic()
            self.changed()
        self.window.makeFirstResponder_(self.board)

    @objc.python_method
    def format_daily_date(self, day: date) -> str:
        """Format a compact unambiguous date for native daily-game controls."""
        return f"{day.strftime('%b')} {day.day}, {day.year}"

    @objc.python_method
    def update_current_day(self) -> bool:
        """Load a newly arrived local day's game when the date changes."""
        today: str = date.today().isoformat()
        if today == self.current_day:
            return False
        self.current_day = today
        try:
            game: Game | None = self.store.load_daily_game(today, self.catalog)
            if game is not None:
                self.daily_games[today] = game
        except SaveError as error:
            self.save_problem = str(error)
        return True

    def dailyGames_(self, sender: Any) -> None:
        """Open today's assigned game or select one weighted catalog difficulty."""
        if not self.preferences.daily_enabled:
            return
        self.board.finish_gesture()
        self.save()
        if self.save_problem:
            self.alert("Cannot start daily game", self.save_problem)
            return
        self.update_current_day()
        today: str = self.current_day
        try:
            selected_game: Game | None = self.daily_games.get(today)
            if selected_game is None:
                selected_game = self.store.load_daily_game(today, self.catalog)
            if selected_game is None:
                level: str = choose_daily_level(
                    self.catalog, self.preferences.daily_minimum, self.preferences.daily_maximum
                )
                selected_game = self.store.start_daily_game(today, level)
            if selected_game.complete:
                return
            if self.history.has_outcome(selected_game.attempt_id):
                selected_game = Game(selected_game.puzzle)
                self.store.save_daily_game(today, selected_game)
            if is_imported(self.game.puzzle.identifier) and not self.game.complete:
                self.regular_game = replace_attempt(
                    self.store,
                    self.history,
                    self.game,
                    None,
                    lambda: self.store.start_replay(self.game.puzzle.identifier, activate=False),
                )
            self.daily_games[today] = selected_game
            self.active_daily_date = today
            self.game = selected_game
            self.completion_shown = False
            self.last_tick = time.monotonic()
            self.changed()
        except (SaveError, ValueError) as error:
            self.alert("Cannot start daily game", str(error))
        self.window.makeFirstResponder_(self.board)

    def returnRegular_(self, sender: Any) -> None:
        """Leave daily progress saved and return to the current regular puzzle."""
        if self.active_daily_date:
            self.board.finish_gesture()
            self.save()
            self.active_daily_date = None
            self.game = self.regular_game
            self.completion_shown = self.game.complete
            self.last_tick = time.monotonic()
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def history_(self, sender: Any) -> None:
        """Open a bounded, scrollable history of newly solved attempts."""
        try:
            if self.history_window is None:
                self.history_window = HistoryWindow(self.history, self.replay_puzzle)
            self.history_window.apply_theme(self.theme, self.window.appearance())
            self.history_window.show()
        except SaveError as error:
            self.alert("Cannot open history", str(error))

    def statistics_(self, sender: Any) -> None:
        """Open per-level summaries of recorded attempts and available puzzles."""
        try:
            if self.store.players is None:
                raise SaveError("Player storage has not been initialized")
            if self.statistics_window is None:
                self.statistics_window = StatisticsWindow(self.history, self.store.players)
            self.statistics_window.apply_theme(self.theme, self.window.appearance())
            self.statistics_window.show()
        except SaveError as error:
            self.alert("Cannot open statistics", str(error))

    @objc.python_method
    def replay_puzzle(self, identifier: str) -> None:
        """Start a separate regular attempt on the selected history puzzle."""
        self.board.finish_gesture()
        self.save()
        try:
            if self.save_problem:
                raise SaveError(self.save_problem)
            next_game: Game = replace_attempt(
                self.store,
                self.history,
                self.game,
                self.active_daily_date,
                lambda: self.store.start_replay(identifier, activate=False),
            )
        except SaveError as error:
            self.alert("Cannot replay puzzle", str(error))
            return
        self.regular_game = next_game
        self.active_daily_date = None
        self.game = self.regular_game
        self.completion_shown = False
        self.last_tick = time.monotonic()
        self.changed()
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.board)

    def importPuzzle_(self, sender: Any) -> None:
        """Open explicit clipboard or file import without changing the current attempt."""
        from sudoku.import_ui import ImportWindow

        self.board.finish_gesture()
        if self.import_window is None or self.import_window.closed:
            self.import_window = ImportWindow.alloc().init()
            self.import_window.setup(self.store, self.play_import)
        self.import_window.apply_theme(self.theme, self.window.appearance())
        self.import_window.show()

    @objc.python_method
    def play_import(self, validated: ValidatedImport, level: str) -> bool:
        """Start matching clues under their catalog identity or save a new import."""
        self.board.finish_gesture()
        self.save()
        try:
            if self.save_problem:
                raise SaveError(self.save_problem)
            match: Puzzle | None = self.catalog.find_givens(validated.givens)
            next_game: Game = replace_attempt(
                self.store,
                self.history,
                self.game,
                self.active_daily_date,
                lambda: (
                    self.store.start_replay(match.identifier, activate=False)
                    if match is not None
                    else self.store.imported.start(validated, level)
                ),
            )
        except (SaveError, OSError, sqlite3.Error, ValueError) as error:
            self.alert("Cannot import puzzle", str(error))
            return False
        self.regular_game = next_game
        self.active_daily_date = None
        self.game = next_game
        self.completion_shown = False
        self.last_tick = time.monotonic()
        self.changed()
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.board)
        return True

    def restart_(self, sender: Any) -> None:
        """Restart the current puzzle only after explicit confirmation."""
        if (
            self.alert(
                "Restart this puzzle?",
                "Your answers, notes, timer, and undo history will be reset.",
                ("Cancel", "Restart"),
            )
            == 1
        ):
            if is_imported(self.game.puzzle.identifier):
                self.save()
                try:
                    if self.save_problem:
                        raise SaveError(self.save_problem)
                    self.game = replace_attempt(
                        self.store,
                        self.history,
                        self.game,
                        None,
                        lambda: self.store.start_replay(
                            self.game.puzzle.identifier, activate=False
                        ),
                        outcome="Restarted",
                    )
                except SaveError as error:
                    self.alert("Cannot restart puzzle", str(error))
                    return
                self.regular_game = self.game
                self.last_tick = time.monotonic()
                self.changed()
                return
            if not self.game.complete:
                try:
                    self.history.record_outcome(
                        self.game,
                        "Restarted",
                        datetime.now(UTC).isoformat(),
                        self.active_daily_date,
                    )
                except SaveError as error:
                    self.alert("Cannot restart puzzle", str(error))
                    return
            self.game = Game(self.game.puzzle)
            self.last_tick = time.monotonic()
            self.changed()
        self.window.makeFirstResponder_(self.board)

    def hint_(self, sender: Any) -> None:
        """Offer a nudge, then an explanation, or clearly label missing solver coverage."""
        if self.game.paused or self.game.complete:
            return
        self.board.finish_gesture()
        wrong: set[int] = self.game.wrong_answers()
        if wrong:
            if (
                self.alert(
                    "Check your entries first",
                    "At least one entered answer differs from this puzzle’s solution. "
                    "Locate an incorrect entry before asking for a logical hint?",
                    ("Cancel", "Locate One"),
                )
                == 1
            ):
                self.game.selected = min(wrong)
                self.hint_focus = {self.game.selected}
                self.refresh()
            return
        if self.current_hint:
            self.hint_stage = min(
                len(hint_steps(self.game, self.current_hint)), self.hint_stage + 1
            )
            self.present_hint()
        else:
            self.anotherHint_(sender)

    @objc.python_method
    def present_hint(self) -> None:
        """Show one teaching stage and its temporary board annotations."""
        if not self.current_hint:
            return
        key: str = hint_stage_key(self.game, self.current_hint, self.hint_stage)
        if key not in self.game.viewed_hint_stages:
            self.game.viewed_hint_stages.add(key)
            self.save()
        step: HintStep = hint_steps(self.game, self.current_hint)[self.hint_stage - 1]
        self.hint_focus = set(step.focus)
        self.hint_candidates = set(step.candidates)
        self.hint_placements = set(step.placements)
        self.hint_removals = set(step.eliminations)
        self.hint_links = step.links
        self.controls["hint_text"].setString_(f"{step.title}\n\n{step.text}")
        self.controls["hint_text"].scrollRangeToVisible_((0, 0))
        self.refresh()

    def previousHint_(self, sender: Any) -> None:
        """Return to the preceding explanation stage without changing the board."""
        if self.current_hint and not self.game.paused:
            self.hint_stage = max(1, self.hint_stage - 1)
            self.present_hint()

    def anotherHint_(self, sender: Any) -> None:
        """Show a different supported deduction, cycling after the final alternative."""
        if self.game.paused or self.game.complete or self.game.wrong_answers():
            return
        if self.hint_iterator is None:
            self.hint_iterator = iter_hints(self.game)
        self.current_hint = next(self.hint_iterator, None)
        if self.current_hint is None:
            self.hint_iterator = iter_hints(self.game)
            self.current_hint = next(self.hint_iterator, None)
        if self.current_hint:
            self.hint_stage = 1
            self.present_hint()
        else:
            self.clear_hint()
            self.controls["hint_text"].setString_(
                "No useful hint was found with the supported techniques for your current "
                "answers and pencil marks.\n\n"
                "Removals you have already made are skipped. Add notes or use Fill Candidates "
                "to explore further eliminations. You can also keep working or explicitly "
                "reveal an editable cell."
            )
            self.controls["reveal"].setHidden_(False)
            self.refresh()

    def applyHint_(self, sender: Any) -> None:
        """Apply exactly the displayed deduction as one reversible action."""
        hint: Hint | None = self.current_hint
        if not hint or self.hint_stage < len(hint_steps(self.game, hint)) or self.game.paused:
            return
        self.game.begin_gesture()
        for index, digit in hint.placements:
            self.game.set_value(
                index,
                digit,
                self.preferences.cleanup_notes,
                error_check=self.preferences.error_check,
            )
            self.game.selected = index
        if hint.eliminations:
            self.game.eliminate(hint.eliminations)
        self.game.end_gesture()
        self.changed()
        self.window.makeFirstResponder_(self.board)

    def reveal_(self, sender: Any) -> None:
        """Reveal an explicitly selected editable cell with an honest spoiler warning."""
        if self.game.paused:
            return
        index: int = self.game.selected
        if self.game.puzzle.givens[index] or self.game.values[index]:
            self.alert(
                "Select an empty cell",
                "Choose an empty cell on the board, then click Reveal Selected Cell again.",
            )
            return
        if (
            self.alert(
                "Reveal this cell?",
                f"This supplies the answer at {cell_name(index)} without explaining a deduction. "
                "You can undo the reveal.",
                ("Cancel", "Reveal"),
            )
            == 1
        ):
            changed: bool = self.game.set_value(
                index,
                self.game.puzzle.solution[index],
                self.preferences.cleanup_notes,
                error_check=self.preferences.error_check,
            )
            if changed:
                self.game.revealed_cells.add(index)
                self.changed()

    def settings_(self, sender: Any) -> None:
        """Show a native preferences window with immediately persisted choices."""
        if not self.settings_window:
            self.build_settings()
        for name in ("appearance", "theme", "error_check", "daily_minimum", "daily_maximum"):
            self.settings_controls[name].selectItemWithTitle_(getattr(self.preferences, name))
        for name in (
            "highlight_digits",
            "dim_completed_digits",
            "highlight_peers",
            "drag_answers_as_candidates",
            "cleanup_notes",
            "show_timer",
            "daily_enabled",
        ):
            self.settings_controls[name].setState_(int(getattr(self.preferences, name)))
        self.update_daily_settings_visibility()
        self.apply_appearance()
        self.settings_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def build_settings(self) -> None:
        """Construct labeled Cocoa appearance, theme, and assistance preferences."""
        self.settings_window = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 470, 582),
            AK.NSWindowStyleMaskTitled | AK.NSWindowStyleMaskClosable,
            AK.NSBackingStoreBuffered,
            False,
        )
        self.settings_window.setReleasedWhenClosed_(False)
        self.settings_window.setTitle_("Sudoku Settings")
        self.settings_window.center()
        content: Any = self.settings_window.contentView()
        for key, title, options, position in (
            ("appearance", "Appearance", ["System", "Light", "Dark"], 525),
            ("theme", "Theme", list(THEME_NAMES), 475),
            ("error_check", "Show errors", ["Off", "Rule Conflicts", "Against Solution"], 425),
            ("daily_minimum", "Daily minimum", list(LEVELS), 110),
            ("daily_maximum", "Daily maximum", list(LEVELS), 60),
        ):
            label: Any = self.label(title)
            label.setFrame_(AK.NSMakeRect(25, position + 2, 140, 24))
            self.settings_controls[f"{key}_label"] = label
            content.addSubview_(label)
            popup: Any = ThemePopUpButton.alloc().initWithFrame_pullsDown_(
                AK.NSMakeRect(165, position, 275, 30), False
            )
            popup.addItemsWithTitles_(options)
            popup.setTarget_(self)
            popup.setAction_("preferenceChanged:")
            popup.setIdentifier_(key)
            popup.setAccessibilityLabel_(title)
            content.addSubview_(popup)
            self.settings_controls[key] = popup
        for row, (key, title) in enumerate(
            (
                ("highlight_digits", "Highlight matching digits and candidates"),
                ("dim_completed_digits", "Dim digits used in nine filled cells"),
                ("highlight_peers", "Highlight the selected row, column, and box"),
                (
                    "drag_answers_as_candidates",
                    "Drag or Shift + arrows in Answers mode paint candidates",
                ),
                ("cleanup_notes", "Remove peer candidates when entering answers"),
                ("show_timer", "Show elapsed play time"),
                ("daily_enabled", "Enable Daily Game"),
            )
        ):
            switch_y: float = 380 - row * 37
            switch_label: Any = self.label(title)
            switch_label.setFrame_(AK.NSMakeRect(25, switch_y - 3, 350, 34))
            switch_label.setLineBreakMode_(AK.NSLineBreakByWordWrapping)
            switch_label.cell().setWraps_(True)
            switch_label.cell().setUsesSingleLineMode_(False)
            content.addSubview_(switch_label)
            toggle: Any = ThemeSwitch.alloc().initWithFrame_(AK.NSMakeRect(390, switch_y, 54, 24))
            toggle.setTarget_(self)
            toggle.setAction_("preferenceChanged:")
            toggle.setIdentifier_(key)
            toggle.setAccessibilityLabel_(title)
            content.addSubview_(toggle)
            self.settings_controls[key] = toggle
            self.settings_controls[f"{key}_label"] = switch_label
        label = self.label("Settings are saved automatically on this Mac.", 11, True)
        label.setFrame_(AK.NSMakeRect(25, 25, 420, 24))
        content.addSubview_(label)
        self.update_daily_settings_visibility()
        self.apply_settings_theme()

    @objc.python_method
    def update_daily_settings_visibility(self) -> None:
        """Show daily difficulty controls only while the daily feature is enabled."""
        for key in ("daily_minimum", "daily_maximum"):
            self.settings_controls[key].setHidden_(not self.preferences.daily_enabled)
            self.settings_controls[f"{key}_label"].setHidden_(not self.preferences.daily_enabled)

    @objc.python_method
    def set_daily_enabled(self, enabled: bool) -> None:
        """Show or hide local daily games while preserving saved progress."""
        self.board.finish_gesture()
        self.preferences.daily_enabled = enabled
        if not enabled:
            self.returnRegular_(None)
        self.settings_controls["daily_enabled"].setState_(int(enabled))
        self.update_daily_settings_visibility()
        self.save()
        self.build_menu()
        self.layout()
        self.refresh()

    def preferenceChanged_(self, sender: Any) -> None:
        """Apply and persist the changed native setting immediately."""
        key: str = str(sender.identifier())
        value: str | bool = (
            str(sender.titleOfSelectedItem())
            if key in ("appearance", "theme", "error_check", "daily_minimum", "daily_maximum")
            else bool(sender.state())
        )
        if key == "daily_enabled":
            self.set_daily_enabled(bool(value))
            return
        setattr(self.preferences, key, value)
        if key == "theme":
            self.theme = theme_for_name(self.preferences.theme)
        minimum_index: int = LEVELS.index(self.preferences.daily_minimum)
        maximum_index: int = LEVELS.index(self.preferences.daily_maximum)
        if key == "daily_minimum" and minimum_index > maximum_index:
            self.preferences.daily_maximum = self.preferences.daily_minimum
            self.settings_controls["daily_maximum"].selectItemWithTitle_(
                self.preferences.daily_maximum
            )
        elif key == "daily_maximum" and maximum_index < minimum_index:
            self.preferences.daily_minimum = self.preferences.daily_maximum
            self.settings_controls["daily_minimum"].selectItemWithTitle_(
                self.preferences.daily_minimum
            )
        self.apply_appearance()
        self.save()
        self.refresh()

    def recover_(self, sender: Any) -> None:
        """Preserve unreadable files and resume saving after explicit user action."""
        if not self.store.blocked:
            self.save()
            self.refresh()
            self.alert(
                "Saving status",
                self.save_problem or "Your game and settings are saved on this Mac.",
            )
        elif (
            self.alert(
                "Resume saving?",
                "Unreadable files will be renamed and preserved. "
                "The current game and settings will then be saved as new files.",
                ("Cancel", "Resume Saving"),
            )
            == 1
        ):
            try:
                self.store.recover()
                self.save()
            except OSError as error:
                self.save_problem = str(error)
            self.refresh()

    def help_(self, sender: Any) -> None:
        """Explain keyboard entry, color highlighting, and pointer painting."""
        self.build_help_dialog(
            "Arrow keys: move without wrapping\n"
            "1–9: enter a digit (Cell First), or choose a digit (Number First)\n"
            "Shift + 1–9, Shift-click or right-click a keypad digit: select without editing\n"
            "Space or Return: place the active digit (Number First), or toggle a color\n"
            "Shift + Space or Return: toggle a candidate (follows the drag setting in Answers)\n"
            "N: switch answers/candidates; C: enter or leave Color mode\n"
            "Delete or 0: clear the selected entry or color\n"
            "Command-Z / Shift-Command-Z: undo / redo\nCommand-J: hint\n"
            "Command-A: auto complete\nCommand-F: fill candidates\n"
            "Command-P: pause / resume\nCommand-N: new game\n"
            "Command-D: today’s daily game\nCommand-I: import puzzle\n"
            "Command-comma: settings\n"
            "Escape: dismiss hint highlights\n\n"
            "Right-click a puzzle cell for Answer, Candidate, and Color actions. "
            "Choose an answer or candidate digit, or choose from the 3×3 color palette; "
            "the active digit is highlighted in the number lists, while checkmarks show "
            "what is already in the cell; "
            "the selected color is "
            "outlined. Choosing the cell's current color clears it. The current mode stays "
            "selected; the chosen digit or color is "
            "remembered for its palette.\n\n"
            "In candidate mode, click to toggle the active candidate. Drag or Shift + arrows "
            "to paint it across cells. A painted gesture adds or removes based on its first cell. "
            "Hold Option to force removal. In Answers mode, both gestures can paint candidates "
            "when enabled in Settings. Small pointer movements during a click are ignored. "
            "Once a drag starts, it paints the starting cell even if the pointer stays within it. "
            "Diagonal drags skip cells touched only near a corner. "
            "Each gesture is one undo action.\n\n"
            "In Color mode, 1–8 choose highlight colors and 9 clears the selected color. "
            "Activate Clear twice in a row to remove all cell colors; Command-Z undoes it. "
            "Cell First applies a color immediately; Number First chooses it for a click. "
            "Drag or Shift + arrows paint across all crossed cells, including filled cells "
            "and givens. Starting on a cell with the chosen color removes it across the stroke. "
            "Press C again to return to the prior entry mode.\n\n"
            "Fill Candidates replaces notes with all candidates legal under the current entries. "
            "Auto Complete repeatedly fills cells with one legal candidate and digits with one "
            "legal position in a row, column, or box. The entire cascade is one undo action. "
            "Manual candidate entry is otherwise preserved, with optional peer cleanup.\n\n"
            "The timer stops while paused, minimized, or outside the app.",
        ).runModal()

    def about_(self, sender: Any) -> None:
        """Show author credit and provide offline access to all license notices."""
        choice: int = int(self.build_about_dialog().runModal()) - AK.NSAlertFirstButtonReturn
        if choice not in (1, 2):
            return
        try:
            content: str = license_text() if choice == 1 else third_party_text()
        except (OSError, UnicodeError) as error:
            self.alert("Cannot read license notices", str(error))
            return
        title: str = "GNU General Public License v3" if choice == 1 else "Third-Party Notices"
        self.build_text_dialog(title, content, title).runModal()

    @objc.python_method
    def build_about_dialog(self) -> Any:
        """Build the About notice with author, license, warranty, and puzzle credits."""
        return self.build_message_dialog(
            f"Sudoku {APP_VERSION}",
            "A native macOS Sudoku app written in Python.\n\n"
            f"{COPYRIGHT_NOTICE}\nOriginal author: Greg Pfountz\n\n"
            "Licensed under the GNU General Public License, version 3 only. "
            "You may copy, modify, and redistribute it under GPLv3. "
            "This program comes with no warranty.\n\n"
            "893,916 puzzles across six difficulty levels. Puzzle data: Sudoku Exchange Puzzle "
            "Bank, dedicated to the public domain. Ratings: Sukaku Explainer. "
            "Each bundled puzzle was independently checked for exactly one solution.\n\n"
            "Extreme puzzles may exceed this version’s logical hint techniques; "
            "reveals are labeled explicitly.",
            ("OK", "View License", "Third-Party Notices"),
        )

    def hideApp_(self, sender: Any) -> None:
        """Hide the application using the standard macOS command."""
        AK.NSApplication.sharedApplication().hide_(sender)

    def minimize_(self, sender: Any) -> None:
        """Minimize the game window."""
        self.window.miniaturize_(sender)

    def closeWindow_(self, sender: Any) -> None:
        """Close the currently focused application window."""
        window: Any = AK.NSApplication.sharedApplication().keyWindow()
        if window:
            window.performClose_(sender)

    def quitApp_(self, sender: Any) -> None:
        """Request normal app termination and its final save."""
        AK.NSApplication.sharedApplication().terminate_(sender)

    def applicationShouldTerminateAfterLastWindowClosed_(self, application: Any) -> bool:
        """Quit after the final app window closes."""
        return True

    def applicationWillTerminate_(self, notification: Any) -> None:
        """Finish pending gestures and persist progress before quitting."""
        if self.startup_failed:
            return
        if self.import_window is not None and not self.import_window.closed:
            self.import_window.close()
        self.capture_full_screen()
        self.main_window_closing = True
        self.board.finish_gesture()
        self.save()

    def applicationShouldTerminate_(self, application: Any) -> int:
        """Keep a failed save visible before allowing unsaved progress to be discarded."""
        if self.startup_failed:
            return AK.NSTerminateNow
        self.capture_full_screen()
        self.board.finish_gesture()
        self.save()
        if (
            self.save_problem
            and self.alert(
                "Your latest changes could not be saved",
                self.save_problem,
                ("Keep Playing", "Quit Anyway"),
            )
            == 0
        ):
            return AK.NSTerminateCancel
        self.main_window_closing = True
        return AK.NSTerminateNow


def main() -> None:
    """Launch the native Cocoa application and retain its controller."""
    app: Any = AK.NSApplication.sharedApplication()
    app.setActivationPolicy_(AK.NSApplicationActivationPolicyRegular)
    controller: Any = AppController.alloc().init()
    app.setDelegate_(controller)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
