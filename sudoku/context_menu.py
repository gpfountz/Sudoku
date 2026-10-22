# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native per-cell entry menu with an embedded color palette."""

from typing import Any

import AppKit as AK
import objc
from Foundation import NSDictionary, NSObject, NSString

from sudoku.controls import DigitButton
from sudoku.model import Game
from sudoku.theme import DEFAULT_THEME, Theme

ACTIVE_DIGIT_BADGE_SIZE: float = 20.0


def native_menu_row_height(menu: Any) -> float:
    """Measure a uniform text row while preserving the unshown menu's items and order."""
    item: Any = menu.itemAtIndex_(menu.numberOfItems() - 1)
    full_height: float = float(menu.size().height)
    menu.removeItem_(item)
    try:
        menu.update()
        return full_height - float(menu.size().height)
    finally:
        menu.addItem_(item)
        menu.update()


class ColorGridView(AK.NSView):
    """Arrange palette buttons in board reading order within a menu item."""

    def isFlipped(self) -> bool:
        """Place color one at the upper-left corner of the grid."""
        return True


class ActiveDigitMenuButton(AK.NSButton):
    """Draw an active number inside the normal-sized native menu row."""

    marked: bool = False
    title_column_offset: float = 0.0
    theme: Theme = DEFAULT_THEME

    def isFlipped(self) -> bool:
        """Draw from the menu row's top-left corner."""
        return True

    def wantsDefaultClipping(self) -> bool:
        """Allow the badge to use the menu's reserved space beyond this custom view."""
        return False

    @objc.python_method
    def badge_rect(self) -> Any:
        """Center the badge in the native title column, after any checkmark column."""
        bounds: Any = self.bounds()
        side: float = ACTIVE_DIGIT_BADGE_SIZE
        title_center: float = bounds.size.width / 2 + self.title_column_offset
        return AK.NSMakeRect(title_center - side / 2, (bounds.size.height - side) / 2, side, side)

    def drawRect_(self, dirty: Any) -> None:
        """Draw a 20-point accent square and retain the cell-content checkmark."""
        bounds: Any = self.bounds()
        square: Any = self.badge_rect()
        self.theme.controls.active_menu_fill.resolve().setFill()
        AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(square, 3, 3).fill()
        label: Any = NSString.stringWithString_(str(self.tag()))
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {
                AK.NSFontAttributeName: AK.NSFont.boldSystemFontOfSize_(14),
                AK.NSForegroundColorAttributeName: self.theme.text,
            }
        )
        measured: Any = label.sizeWithAttributes_(attributes)
        label.drawAtPoint_withAttributes_(
            (
                square.origin.x + (square.size.width - measured.width) / 2,
                (bounds.size.height - measured.height) / 2,
            ),
            attributes,
        )
        if self.marked:
            check: Any = NSString.stringWithString_("✓")
            check_attributes: Any = NSDictionary.dictionaryWithDictionary_(
                {
                    AK.NSFontAttributeName: AK.NSFont.systemFontOfSize_(10),
                    AK.NSForegroundColorAttributeName: self.theme.text,
                }
            )
            check_size: Any = check.sizeWithAttributes_(check_attributes)
            check.drawAtPoint_withAttributes_(
                (
                    max(1, self.title_column_offset),
                    (bounds.size.height - check_size.height) / 2,
                ),
                check_attributes,
            )


class CellContextMenu(NSObject):
    """Own one right-click menu and apply its choices to the clicked cell."""

    board: Any
    index: int
    menu: Any

    @objc.python_method
    def configure(self, board: Any, index: int) -> None:
        """Bind menu actions to the cell under the pointer."""
        self.board = board
        self.index = index
        self.menu = None

    @objc.python_method
    def build_menu(self) -> Any:
        """Show answer, candidate, and color choices for the clicked cell."""
        game: Game = self.board.controller.game
        menu: Any = AK.NSMenu.alloc().initWithTitle_("Cell actions")
        menu.setAutoenablesItems_(False)
        for mode in ("Answer", "Candidate", "Color"):
            item: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(mode, None, "")
            submenu: Any = self.color_submenu() if mode == "Color" else self.digit_submenu(mode)
            item.setSubmenu_(submenu)
            item.setEnabled_(
                mode == "Color"
                or (
                    game.can_edit_answer(self.index, self.board.controller.preferences.error_check)
                    and (mode == "Answer" or not game.values[self.index])
                )
            )
            menu.addItem_(item)
        self.menu = menu
        return menu

    @objc.python_method
    def digit_submenu(self, mode: str) -> Any:
        """Show a compact active-digit badge and check values present in the cell."""
        game: Game = self.board.controller.game
        submenu: Any = AK.NSMenu.alloc().initWithTitle_(mode)
        submenu.setAutoenablesItems_(False)
        action: str = "chooseAnswer:" if mode == "Answer" else "chooseCandidate:"
        selected_items: list[Any] = []
        active_item: Any = None
        for digit in range(1, 10):
            item: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                str(digit), action, ""
            )
            item.setTarget_(self)
            item.setTag_(digit)
            item.setAccessibilityLabel_(f"Digit {digit}")
            selected: bool = (
                game.values[self.index] == digit
                if mode == "Answer"
                else digit in game.notes[self.index]
            )
            if selected:
                selected_items.append(item)
            if digit == game.active_digit:
                active_item = item
            submenu.addItem_(item)

        # AppKit reserves a state-image column when a native row has a checkmark.
        # Measure that column before replacing the active row with a custom view.
        submenu.update()
        plain_width: float = float(submenu.size().width)
        row_height: float = native_menu_row_height(submenu) if active_item is not None else 0
        for item in selected_items:
            item.setState_(AK.NSControlStateValueOn)
        submenu.update()
        checked_width: float = float(submenu.size().width)
        if active_item is not None:
            button: Any = ActiveDigitMenuButton.alloc().initWithFrame_(
                AK.NSMakeRect(0, 0, plain_width, row_height)
            )
            button.setButtonType_(AK.NSButtonTypeMomentaryChange)
            button.setFocusRingType_(AK.NSFocusRingTypeNone)
            button.setTag_(game.active_digit)
            button.setTarget_(self)
            button.setAction_(action)
            button.setAccessibilityLabel_(f"Digit {game.active_digit}")
            button.marked = active_item in selected_items
            button.title_column_offset = checked_width - plain_width
            button.theme = self.board.controller.theme
            active_item.setView_(button)
        # AppKit may draw a submenu narrower than size() reports once its checked
        # row uses a custom view. Preserve the native checked-row width at popup.
        submenu.setMinimumWidth_(checked_width)
        return submenu

    @objc.python_method
    def color_submenu(self) -> Any:
        """Place eight native color tiles and Clear in a compact 3×3 view."""
        submenu: Any = AK.NSMenu.alloc().initWithTitle_("Color")
        submenu.setAutoenablesItems_(False)
        tile: float = 48
        gap: float = 4
        margin: float = 6
        side: float = margin * 2 + tile * 3 + gap * 2
        grid: Any = ColorGridView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, side, side))
        active: int = self.board.controller.game.active_color
        for color in range(1, 10):
            row, column = divmod(color - 1, 3)
            button: Any = DigitButton.alloc().initWithFrame_(
                AK.NSMakeRect(
                    margin + column * (tile + gap), margin + row * (tile + gap), tile, tile
                )
            )
            button.setButtonType_(AK.NSButtonTypeMomentaryChange)
            # Menus focus the first button; only the chosen color should have an outline.
            button.setFocusRingType_(AK.NSFocusRingTypeNone)
            button.shows_focus_outline = False
            button.theme = self.board.controller.theme
            button.setFont_(AK.NSFont.systemFontOfSize_(12 if color == 9 else 17))
            button.set_color_mode(True, color)
            button.setTitle_("Clear" if color == 9 else str(color))
            button.setAccessibilityLabel_(
                "Clear cell color"
                if color == 9
                else f"Color {self.board.controller.theme.annotations.name(color)}"
            )
            button.setToolTip_(
                "Clear cell color"
                if color == 9
                else self.board.controller.theme.annotations.name(color)
            )
            button.setTag_(color)
            button.setTarget_(self)
            button.setAction_("chooseColor:")
            button.setState_(
                AK.NSControlStateValueOn if color == active else AK.NSControlStateValueOff
            )
            grid.addSubview_(button)
        item: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Color palette", None, ""
        )
        item.setView_(grid)
        submenu.addItem_(item)
        return submenu

    @objc.python_method
    def finish_action(self, changed: bool) -> None:
        """Dismiss the menu and persist the clicked cell's edit and active selection."""
        if self.menu is not None:
            self.menu.cancelTracking()
        if changed:
            self.board.controller.changed()
        else:
            self.board.controller.save()
            self.board.controller.refresh()

    def chooseAnswer_(self, sender: Any) -> None:
        """Set an answer at the clicked editable cell without changing input mode."""
        game: Game = self.board.controller.game
        if game.complete or not game.can_edit_answer(
            self.index, self.board.controller.preferences.error_check
        ):
            return
        digit: int = int(sender.tag())
        game.active_digit = digit
        changed: bool = game.set_value(
            self.index,
            digit,
            self.board.controller.preferences.cleanup_notes,
            error_check=self.board.controller.preferences.error_check,
        )
        self.finish_action(changed)

    def chooseCandidate_(self, sender: Any) -> None:
        """Toggle a candidate at the clicked empty cell without changing input mode."""
        game: Game = self.board.controller.game
        if game.paused or game.complete or game.values[self.index]:
            return
        digit: int = int(sender.tag())
        game.active_digit = digit
        self.finish_action(game.mark(self.index, digit))

    def chooseColor_(self, sender: Any) -> None:
        """Toggle the chosen color on the clicked cell without changing input mode."""
        game: Game = self.board.controller.game
        if game.paused or game.complete:
            return
        game.active_color = int(sender.tag())
        self.finish_action(game.paint_color(self.index))
