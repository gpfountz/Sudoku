# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native controls with palette-specific sizing and presentation."""

from typing import Any

import AppKit as AK
import objc
from Foundation import NSDictionary, NSString

from sudoku import compatibility
from sudoku.compatibility import action_bezel_style
from sudoku.theme import DEFAULT_THEME, Theme


def button_title(button: Any, color: Any) -> Any:
    """Retain native button typography while using an adaptive foreground color."""
    attributes: Any = NSDictionary.dictionaryWithDictionary_(
        {AK.NSFontAttributeName: button.font(), AK.NSForegroundColorAttributeName: color}
    )
    return AK.NSAttributedString.alloc().initWithString_attributes_(button.title(), attributes)


def apply_action_theme(button: Any, theme: Theme) -> None:
    """Theme native action text and use opaque controls for High Contrast."""
    button.setBezelStyle_(action_bezel_style(theme.high_contrast))
    button.setBezelColor_(unselected_bezel_color(theme))
    button.setAttributedTitle_(button_title(button, theme.text))


def unselected_bezel_color(theme: Theme) -> Any:
    """Keep older rounded bezels native; their tint can darken a light background."""
    return (
        theme.controls.background
        if theme.high_contrast and compatibility.supports_glass_buttons()
        else None
    )


def horizontal_bezel_margin(buttons: list[Any]) -> float:
    """Reserve native bezel frames extending beyond horizontal alignment boxes."""
    margin: float = 0.0
    for button in buttons:
        insets: Any = button.alignmentRectInsets()
        margin = max(margin, float(insets.left), float(insets.right))
    return margin


def linear_rgb(color: Any) -> tuple[float, ...]:
    """Resolve an adaptive color in the linear RGB space used by Core Image."""
    resolved: Any = color.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
    components: tuple[float, ...] = (
        float(resolved.redComponent()),
        float(resolved.greenComponent()),
        float(resolved.blueComponent()),
    )
    return tuple(
        component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4
        for component in components
    )


def native_accent_filter(accent: Any) -> Any:
    """Remap native accent pixels while preserving neutral knobs, shadows, and text."""
    source: tuple[float, ...] = linear_rgb(AK.NSColor.controlAccentColor())
    destination: tuple[float, ...] = linear_rgb(accent)
    maximum: int = max(range(3), key=source.__getitem__)
    minimum: int = min(range(3), key=source.__getitem__)
    contrast: float = source[maximum] - source[minimum]
    if contrast < 0.0001:
        return None
    weights: list[float] = [0.0, 0.0, 0.0]
    weights[maximum] = 1 / contrast
    weights[minimum] = -1 / contrast
    color_filter: Any = AK.CIFilter.filterWithName_("CIColorMatrix")
    color_filter.setDefaults()
    for channel, key in enumerate(("inputRVector", "inputGVector", "inputBVector")):
        delta: float = destination[channel] - source[channel]
        vector: list[float] = [
            float(index == channel) + delta * weights[index] for index in range(3)
        ]
        color_filter.setValue_forKey_(AK.CIVector.vectorWithX_Y_Z_W_(*vector, 0), key)
    return color_filter


def apply_native_accent(view: Any, theme: Theme) -> None:
    """Tint native accent rendering in a view's appearance while preserving neutral pixels."""
    if theme is DEFAULT_THEME:
        if view.layer() is not None:
            view.layer().setFilters_(None)
        return
    view.setWantsLayer_(True)
    view.setLayerUsesCoreImageFilters_(True)

    def install_filter() -> None:
        """Resolve adaptive accents before installing the native rendering filter."""
        color_filter: Any = native_accent_filter(theme.accent)
        view.layer().setFilters_([color_filter] if color_filter is not None else None)

    view.effectiveAppearance().performAsCurrentDrawingAppearance_(install_filter)


class ThemeSwitch(AK.NSSwitch):
    """Keep native switch interaction and animation while tinting its accent pixels."""

    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def apply_theme(self, theme: Theme) -> None:
        """Refresh the switch tint without changing its value, target, or action."""
        self.theme = theme
        self.update_theme_tint()

    @objc.python_method
    def update_theme_tint(self) -> None:
        """Resolve the tint in this control's appearance, leaving Default fully native."""
        apply_native_accent(self, self.theme)

    def viewDidChangeEffectiveAppearance(self) -> None:
        """Retint native switch rendering when System switches between Light and Dark."""
        objc.super(ThemeSwitch, self).viewDidChangeEffectiveAppearance()
        self.update_theme_tint()


class ThemePopUpButton(AK.NSPopUpButton):
    """Keep native menu behavior with a theme-colored keyboard focus indicator."""

    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def apply_theme(self, theme: Theme) -> None:
        """Use native focus for Default and a custom accent outline for other themes."""
        self.theme = theme
        self.setFocusRingType_(
            AK.NSFocusRingTypeDefault if theme is DEFAULT_THEME else AK.NSFocusRingTypeNone
        )
        menu: Any = self.menu()
        menu.setDelegate_(self if theme is not DEFAULT_THEME else None)
        menu.setShowsStateColumn_(theme is DEFAULT_THEME)
        for item in menu.itemArray():
            item.setView_(None)
        if theme is not DEFAULT_THEME:
            self.prepare_menu_rows()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def prepare_menu_rows(self) -> None:
        """Draw theme highlights inside native menu tracking and selection geometry."""
        menu: Any = self.menu()
        attributes: Any = {AK.NSFontAttributeName: self.font()}
        title_width: float = max(
            float(NSString.stringWithString_(item.title()).sizeWithAttributes_(attributes).width)
            for item in menu.itemArray()
        )
        width: float = max(float(self.bounds().size.width), title_width + 40)
        for item in menu.itemArray():
            row: Any = ThemeMenuRow.alloc().initWithFrame_(AK.NSMakeRect(0, 0, width, 24))
            row.popup_ref = objc.WeakRef(self)
            row.font = self.font()
            row.theme = self.theme
            row.setAccessibilityRole_(AK.NSAccessibilityMenuItemRole)
            row.setAccessibilityLabel_(item.title())
            item.setView_(row)

    def menuWillOpen_(self, menu: Any) -> None:
        """Update checks and row widths immediately before a preference menu opens."""
        self.prepare_menu_rows()

    def menu_willHighlightItem_(self, menu: Any, item: Any) -> None:
        """Update custom row highlights during native keyboard and pointer tracking."""
        for choice in menu.itemArray():
            row: Any = choice.view()
            if row is not None:
                row.highlighted = choice == item
                row.setNeedsDisplay_(True)

    def becomeFirstResponder(self) -> bool:
        """Show keyboard focus when this preference becomes the active control."""
        accepted: bool = bool(objc.super(ThemePopUpButton, self).becomeFirstResponder())
        self.setNeedsDisplay_(True)
        return accepted

    def resignFirstResponder(self) -> bool:
        """Remove the theme outline when keyboard focus moves to another control."""
        accepted: bool = bool(objc.super(ThemePopUpButton, self).resignFirstResponder())
        self.setNeedsDisplay_(True)
        return accepted

    def drawRect_(self, dirty: Any) -> None:
        """Draw the native popup and an inset accent outline when it has focus."""
        objc.super(ThemePopUpButton, self).drawRect_(dirty)
        if (
            self.theme is not DEFAULT_THEME
            and self.window()
            and self.window().isKeyWindow()
            and self.window().firstResponder() == self
        ):
            self.theme.accent.setStroke()
            outline: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AK.NSInsetRect(self.bounds(), 2, 2), 6, 6
            )
            outline.setLineWidth_(2)
            outline.stroke()


class ThemeMenuRow(AK.NSView):
    """Draw one popup choice while its NSMenu retains tracking and keyboard selection."""

    popup_ref: Any
    font: Any
    theme: Theme = DEFAULT_THEME
    highlighted: bool = False

    def acceptsFirstResponder(self) -> bool:
        """Let the native menu focus a custom choice during keyboard navigation."""
        return True

    def keyDown_(self, event: Any) -> None:
        """Confirm focused menu choices using Return or Space."""
        if event.keyCode() in (36, 49, 76):
            self.activate()
        else:
            objc.super(ThemeMenuRow, self).keyDown_(event)

    def drawRect_(self, dirty: Any) -> None:
        """Paint the accent highlight, checked state, and readable menu title."""
        item: Any = self.enclosingMenuItem()
        if item is None:
            return
        selected: bool = self.highlighted or item.isHighlighted()
        if selected:
            self.theme.accent.setFill()
            AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AK.NSInsetRect(self.bounds(), 1, 0), 6, 6
            ).fill()
        color: Any = self.theme.controls.selected_text if selected else self.theme.text
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {AK.NSFontAttributeName: self.font, AK.NSForegroundColorAttributeName: color}
        )
        title: Any = NSString.stringWithString_(item.title())
        height: float = float(title.sizeWithAttributes_(attributes).height)
        position: float = (self.bounds().size.height - height) / 2
        title.drawAtPoint_withAttributes_((25, position), attributes)
        if item.state() == AK.NSControlStateValueOn:
            NSString.stringWithString_("✓").drawAtPoint_withAttributes_((8, position), attributes)

    @objc.python_method
    def activate(self) -> None:
        """Choose the clicked item and send the popup's existing preference action once."""
        popup: Any = self.popup_ref()
        item: Any = self.enclosingMenuItem()
        if popup is None or item is None:
            return
        popup.selectItem_(item)
        item.menu().cancelTracking()
        if popup.action() is not None:
            popup.sendAction_to_(popup.action(), popup.target())

    def mouseUp_(self, event: Any) -> None:
        """Choose a menu row on release using the native popup selection interface."""
        self.activate()

    def accessibilityPerformPress(self) -> bool:
        """Allow assistive technology to select the themed native menu choice."""
        self.activate()
        return True


class ThemeFocusOutline(AK.NSView):
    """Draw themed keyboard focus over a native dialog button without intercepting input."""

    theme: Theme = DEFAULT_THEME
    tints_button: bool = False

    def viewDidChangeEffectiveAppearance(self) -> None:
        """Refresh a default alert button's tint when its native appearance changes."""
        objc.super(ThemeFocusOutline, self).viewDidChangeEffectiveAppearance()
        if self.tints_button and self.superview() is not None:
            apply_native_accent(self.superview(), self.theme)

    def hitTest_(self, point: Any) -> Any:
        """Keep pointer interaction on the native button beneath this decoration."""
        return None

    def drawRect_(self, dirty: Any) -> None:
        """Draw an accent ring only when the enclosing button has keyboard focus."""
        button: Any = self.superview()
        window: Any = self.window()
        if window and window.isKeyWindow() and window.firstResponder() == button:
            # A tinted parent maps the native focus color into the theme accent once.
            color: Any = AK.NSColor.controlAccentColor() if self.tints_button else self.theme.accent
            color.setStroke()
            bounds: Any = AK.NSInsetRect(self.bounds(), 2, 2)
            outline: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, bounds.size.height / 2, bounds.size.height / 2
            )
            outline.setLineWidth_(2)
            outline.stroke()


class LegacyChoiceButton(AK.NSButton):
    """Keep a themed selected fill and its text paired across legacy window focus states."""

    theme: Theme = DEFAULT_THEME
    selection_fill: Any = DEFAULT_THEME.accent

    def drawRect_(self, dirty: Any) -> None:
        """Draw selected choices without AppKit's focus-dependent accent darkening."""
        selected: bool = self.state() == AK.NSControlStateValueOn
        pressed: bool = self.cell().isHighlighted()
        if not selected and not pressed:
            objc.super(LegacyChoiceButton, self).drawRect_(dirty)
            return
        # Rounded native buttons include invisible padding outside their bezel.
        # Use the same alignment box instead of painting that extra frame space.
        bezel: Any = self.alignmentRectForFrame_(self.bounds())
        frame: Any = AK.NSInsetRect(bezel, 0.5, 0.5)
        outline: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(frame, 6, 6)
        self.selection_fill.setFill()
        outline.fill()
        self.theme.controls.border.setStroke()
        outline.setLineWidth_(2 if self.theme.high_contrast else 1)
        outline.stroke()
        color: Any = self.theme.controls.selected_text
        if not self.isEnabled():
            color = color.colorWithAlphaComponent_(self.theme.controls.dimmed_opacity)
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {AK.NSFontAttributeName: self.font(), AK.NSForegroundColorAttributeName: color}
        )
        title: Any = NSString.stringWithString_(self.title())
        measured: Any = title.sizeWithAttributes_(attributes)
        title.drawAtPoint_withAttributes_(
            (
                frame.origin.x + (frame.size.width - measured.width) / 2,
                frame.origin.y + (frame.size.height - measured.height) / 2,
            ),
            attributes,
        )
        if self.window() and self.window().isKeyWindow() and self.window().firstResponder() == self:
            color.setStroke()
            focus: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                AK.NSInsetRect(frame, 2, 2), 4, 4
            )
            focus.setLineWidth_(2)
            focus.stroke()


def choice_button(title: str, target: Any) -> Any:
    """Use native glass controls and a paired-color fallback for older rounded controls."""
    button_type: Any = AK.NSButton if compatibility.supports_glass_buttons() else LegacyChoiceButton
    return button_type.buttonWithTitle_target_action_(title, target, "segmentPressed:")


class GlassChoiceControl(AK.NSStackView):
    """Present one-of-many choices as a compact row of adaptive native buttons."""

    choice_buttons: list[Any]
    choice_titles: list[tuple[Any, Any]]
    callback_target: Any
    callback_action: str
    selected_index: int = -1
    selected_bezel_color: Any = DEFAULT_THEME.accent
    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def configure(self, labels: list[str], target: Any, action: str) -> None:
        """Build native choices that forward one selection action."""
        self.callback_target = target
        self.callback_action = action
        self.choice_buttons = []
        self.choice_titles = []
        self.setOrientation_(AK.NSUserInterfaceLayoutOrientationHorizontal)
        self.setDistribution_(AK.NSStackViewDistributionFillEqually)
        self.setSpacing_(4)
        font: Any = AK.NSFont.systemFontOfSize_(13)
        for index, title in enumerate(labels):
            button: Any = choice_button(title, self)
            button.setTag_(index)
            button.setBezelStyle_(action_bezel_style())
            button.setButtonType_(AK.NSButtonTypePushOnPushOff)
            if not compatibility.supports_glass_buttons():
                # Older rounded cells can remap the normal title's ink in their on
                # state. Use explicit selected contents and change only the bezel.
                cell: Any = button.cell()
                cell.setShowsStateBy_(AK.NSContentsCellMask | AK.NSChangeBackgroundCellMask)
                cell.setHighlightsBy_(
                    AK.NSContentsCellMask | AK.NSPushInCellMask | AK.NSChangeBackgroundCellMask
                )
            button.setFont_(font)
            normal_title: Any = button_title(button, self.theme.text)
            selected_title: Any = button_title(button, self.theme.controls.selected_text)
            button.setAttributedTitle_(normal_title)
            button.setAccessibilityLabel_(title)
            self.addArrangedSubview_(button)
            self.choice_buttons.append(button)
            self.choice_titles.append((normal_title, selected_title))
        self.update_bezel_margins()

    @objc.python_method
    def update_bezel_margins(self) -> None:
        """Keep the entire first and last button frames inside the row's bounds."""
        margin: float = horizontal_bezel_margin(self.choice_buttons)
        self.setEdgeInsets_(AK.NSEdgeInsetsMake(0, margin, 0, margin))
        self.setDistribution_(
            AK.NSStackViewDistributionFillProportionally
            if margin
            else AK.NSStackViewDistributionFillEqually
        )

    @objc.python_method
    def apply_theme(self, theme: Theme) -> None:
        """Update normal and selected titles, retaining native choice actions and state."""
        self.theme = theme
        self.selected_bezel_color = theme.accent
        self.choice_titles = []
        for button in self.choice_buttons:
            if isinstance(button, LegacyChoiceButton):
                button.theme = theme
            button.setBezelStyle_(action_bezel_style(theme.high_contrast))
            self.choice_titles.append(
                (
                    button_title(button, theme.text),
                    button_title(button, theme.controls.selected_text),
                )
            )
        self.setSelectedSegment_(self.selected_index)
        self.update_bezel_margins()

    def setSelectedSegment_(self, index: int) -> None:
        """Keep exactly one native button visibly selected."""
        self.selected_index = index
        for button_index, button in enumerate(self.choice_buttons):
            if isinstance(button, LegacyChoiceButton):
                button.selection_fill = self.selected_bezel_color
            button.setBezelColor_(
                self.selected_bezel_color
                if button_index == index
                else unselected_bezel_color(self.theme)
            )
            button.setAttributedTitle_(
                self.choice_titles[button_index][1 if button_index == index else 0]
            )
            if not compatibility.supports_glass_buttons():
                button.setAttributedAlternateTitle_(self.choice_titles[button_index][1])
            button.setState_(
                AK.NSControlStateValueOn if button_index == index else AK.NSControlStateValueOff
            )
            button.setNeedsDisplay_(True)

    def selectedSegment(self) -> int:
        """Expose the selected choice to the existing controller actions."""
        return self.selected_index

    def setSelectedSegmentBezelColor_(self, color: Any) -> None:
        """Apply the theme accent to the selected choice, including later clicks."""
        self.selected_bezel_color = color
        self.setSelectedSegment_(self.selected_index)

    def selectedSegmentBezelColor(self) -> Any:
        """Expose the selection accent using the native segmented-control interface."""
        return self.selected_bezel_color

    def setEnabled_(self, enabled: bool) -> None:
        """Disable every choice while the game is paused."""
        for button in self.choice_buttons:
            button.setEnabled_(enabled)

    def isEnabled(self) -> bool:
        """Report whether the row currently accepts input."""
        return all(button.isEnabled() for button in self.choice_buttons)

    def segmentPressed_(self, sender: Any) -> None:
        """Select a glass choice and send the row's existing controller action."""
        self.setSelectedSegment_(int(sender.tag()))
        AK.NSApplication.sharedApplication().sendAction_to_from_(
            self.callback_action, self.callback_target, self
        )


class DigitButton(AK.NSButton):
    """Keep native button interaction while drawing a tile that fills its actual height."""

    dimmed: bool = False
    color_mode: bool = False
    palette_index: int = 0
    shows_focus_outline: bool = True
    theme: Theme = DEFAULT_THEME

    def alignmentRectInsets(self) -> Any:
        """Align the entire custom tile, without native bezel or shadow margins."""
        return AK.NSEdgeInsetsMake(0, 0, 0, 0)

    def rightMouseDown_(self, event: Any) -> None:
        """Select this digit without editing the board when the keypad is enabled."""
        if self.isEnabled():
            self.sendAction_to_("selectDigit:", self.target())

    def isFlipped(self) -> bool:
        """Use top-down coordinates for centered text rendering."""
        return True

    @objc.python_method
    def set_dimmed(self, dimmed: bool) -> None:
        """Dim only the digit, retaining selection and native button activation."""
        self.dimmed = dimmed
        self.setNeedsDisplay_(True)

    @objc.python_method
    def set_color_mode(self, enabled: bool, palette_index: int) -> None:
        """Show a color swatch or the clear action in the existing digit tile."""
        self.color_mode = enabled
        self.palette_index = palette_index
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty: Any) -> None:
        """Draw a full-height rounded tile with a vertically centered system-font digit."""
        selected: bool = self.state() == AK.NSControlStateValueOn
        pressed: bool = self.cell().isHighlighted()
        accent: Any = self.theme.accent
        background: Any = accent if selected else self.theme.controls.background
        if self.color_mode and self.palette_index < 9:
            background = self.theme.annotations.tile_fill(self.palette_index, selected)
        if pressed:
            background = self.theme.controls.pressed_background
        background.setFill()
        frame: Any = AK.NSInsetRect(self.bounds(), 2, 2)
        path: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(frame, 8, 8)
        path.fill()
        path.setLineWidth_(2 if self.theme.high_contrast else 1)
        border: Any = accent if selected else self.theme.controls.border
        if self.color_mode and self.palette_index < 9 and not selected:
            border = self.theme.annotations.color(self.palette_index)
        if selected:
            path.setLineWidth_(3)
        if self.shows_focus_outline and self.window() and self.window().firstResponder() == self:
            border = accent
            path.setLineWidth_(3)
        border.setStroke()
        path.stroke()
        color: Any = (
            self.theme.controls.selected_text
            if selected and not pressed and (not self.color_mode or self.palette_index == 9)
            else self.theme.text
        )
        if self.dimmed or not self.isEnabled():
            color = color.colorWithAlphaComponent_(self.theme.controls.dimmed_opacity)
        # Native attributes avoid retaining Python dictionaries across Cocoa text calls.
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {AK.NSFontAttributeName: self.font(), AK.NSForegroundColorAttributeName: color}
        )
        title: Any = NSString.stringWithString_(self.title())
        measured: Any = title.sizeWithAttributes_(attributes)
        title.drawAtPoint_withAttributes_(
            (
                (self.bounds().size.width - measured.width) / 2,
                (self.bounds().size.height - measured.height) / 2,
            ),
            attributes,
        )
