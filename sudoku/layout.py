# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Adaptive native panel arrangements with a readable compact scrolling fallback."""

from dataclasses import dataclass, replace
from typing import Any

import AppKit as AK

MINIMUM_CONTENT_SIZE: tuple[float, float] = (400, 600)
MINIMUM_BOARD: float = 288
PANEL_WIDTH: float = 260
KEYPAD_HEIGHT: float = 300
HINT_MINIMUM_HEIGHT: float = 224
GAP: float = 16
PADDING: float = 12


@dataclass(frozen=True)
class LayoutPlan:
    """A deterministic arrangement of square board and supporting native panels."""

    mode: str
    split_support: bool
    board: float
    panel_width: float
    hint_height: float
    width: float
    height: float

    @property
    def keypad_scale(self) -> float:
        """Scale digit tiles proportionally to the board, bounded by the panel width."""
        return min(1.0, self.board / 588, self.panel_width / 260)

    @property
    def keypad_height(self) -> float:
        """Keep text controls native-sized while scaling the three digit rows."""
        return 152 + 148 * self.keypad_scale


def supporting_width(board: float) -> float:
    """Narrow supporting controls to their readable text width as the board shrinks."""
    return max(220, min(PANEL_WIDTH, PANEL_WIDTH * board / 588))


def layout_plan(width: float, height: float, previous: str = "") -> LayoutPlan:
    """Choose arrangements with a 24-point exit band to avoid threshold oscillation."""
    available: float = max(MINIMUM_BOARD, width - PADDING * 2)
    vertical: float = max(0, height - PADDING * 2)
    wide: bool = height >= 550 and (width >= 850 or width >= 684 and width >= height * 1.15)
    short: bool = width >= 1000
    if (
        previous == "wide"
        and width >= 660
        and height >= 526
        and (width >= 826 or width >= height * 1.10)
    ):
        wide = True
    elif previous == "short-wide" and width >= 976 and height < 574:
        wide, short = False, True
    if wide or short:
        columns: int = 1 if wide else 2
        size: float = min(vertical, (available - columns * GAP) / (1 + columns * PANEL_WIDTH / 588))
        panel_width: float = supporting_width(size)
        size = min(vertical, max(MINIMUM_BOARD, available - columns * (panel_width + GAP)))
        keypad_height: float = 152 + 148 * min(1.0, size / 588, panel_width / 260)
        sidebar_height: float = (
            max(size, keypad_height + GAP + HINT_MINIMUM_HEIGHT)
            if wide
            else max(size, keypad_height)
        )
        hint_height: float = sidebar_height - keypad_height - GAP if wide else sidebar_height
        return LayoutPlan(
            "wide" if wide else "short-wide",
            not wide,
            size,
            panel_width,
            hint_height,
            size + columns * (panel_width + GAP),
            min(vertical, sidebar_height),
        )
    split: bool = width >= 504 or previous == "narrow-split" and width >= 480
    panel_width = min(360, (available - GAP) / 2) if split else min(360, available)
    size = max(0, min(available, vertical - GAP - 120))
    keypad_height = 152 + 148 * min(1.0, size / 588, panel_width / 260)
    support_height: float = (
        max(keypad_height, HINT_MINIMUM_HEIGHT)
        if split
        else keypad_height + GAP + HINT_MINIMUM_HEIGHT
    )
    return LayoutPlan(
        "narrow-split" if split else "narrow-stack",
        split,
        size,
        panel_width,
        max(keypad_height, HINT_MINIMUM_HEIGHT) if split else HINT_MINIMUM_HEIGHT,
        max(size, 2 * panel_width + GAP if split else panel_width),
        min(vertical, size + GAP + support_height),
    )


def fit_window_frame(
    frame: tuple[float, float, float, float], visible: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Clamp restored geometry to the selected screen's usable bounds."""
    x, y, width, height = frame
    sx, sy, sw, sh = visible
    width, height = min(width, sw), min(height, sh)
    return max(sx, min(x, sx + sw - width)), max(sy, min(y, sy + sh - height)), width, height


def stack(views: list[Any], vertical: bool, spacing: float = 8) -> Any:
    """Create an explicitly oriented AppKit stack with hidden controls excluded from layout."""
    result: Any = AK.NSStackView.stackViewWithViews_(views)
    result.setTranslatesAutoresizingMaskIntoConstraints_(False)
    result.setOrientation_(
        AK.NSUserInterfaceLayoutOrientationVertical
        if vertical
        else AK.NSUserInterfaceLayoutOrientationHorizontal
    )
    result.setAlignment_(AK.NSLayoutAttributeLeading if vertical else AK.NSLayoutAttributeTop)
    result.setDistribution_(AK.NSStackViewDistributionFill)
    result.setSpacing_(spacing)
    result.setDetachesHiddenViews_(True)
    for view in views:
        view.setTranslatesAutoresizingMaskIntoConstraints_(False)
    return result


def fixed(view: Any, attribute: str, value: float) -> Any:
    """Activate and return an adjustable dimension constraint."""
    constraint: Any = getattr(view, f"{attribute}Anchor")().constraintEqualToConstant_(value)
    constraint.setActive_(True)
    return constraint


def fill_width(view: Any, parent: Any) -> None:
    """Let a vertical stack child use its container's available width."""
    view.widthAnchor().constraintEqualToAnchor_(parent.widthAnchor()).setActive_(True)


class AdaptiveLayout:
    """Own native stacks and update only geometry as the content viewport changes."""

    def __init__(self, window: Any, board: Any, controls: dict[str, Any]) -> None:
        """Reparent existing controls without replacing their actions or input behavior."""
        self.window: Any = window
        self.board: Any = board
        self.controls: dict[str, Any] = controls
        self.mode: str = ""
        self.header_signature: tuple[tuple[str, ...], ...] = ()
        self.actions_signature: tuple[tuple[str, ...], ...] = ()
        self.constraints: dict[str, Any] = {}
        self.updating: bool = False
        self.header: Any = stack([], True)
        self.actions: Any = stack([], True)
        self.make_branding()
        self.keypad: Any = self.make_keypad()
        self.hints: Any = self.make_hints()
        self.support: Any = stack([self.keypad, self.hints], True, GAP)
        self.board_panel: Any = AK.NSView.alloc().initWithFrame_(AK.NSZeroRect)
        self.board_panel.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.board_panel.addSubview_(board)
        board.setTranslatesAutoresizingMaskIntoConstraints_(False)
        AK.NSLayoutConstraint.activateConstraints_(
            [
                board.leadingAnchor().constraintEqualToAnchor_(self.board_panel.leadingAnchor()),
                board.topAnchor().constraintEqualToAnchor_(self.board_panel.topAnchor()),
                board.widthAnchor().constraintEqualToAnchor_(self.board_panel.widthAnchor()),
                board.heightAnchor().constraintEqualToAnchor_(board.widthAnchor()),
            ]
        )
        self.support_scroll: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSZeroRect)
        self.support_scroll.setHasVerticalScroller_(True)
        self.support_scroll.setAutohidesScrollers_(True)
        self.support_scroll.setScrollerStyle_(AK.NSScrollerStyleOverlay)
        self.support_scroll.setDrawsBackground_(False)
        self.support_document: Any = AK.NSView.alloc().initWithFrame_(AK.NSZeroRect)
        self.support_document.addSubview_(self.support)
        self.support_scroll.setDocumentView_(self.support_document)
        AK.NSLayoutConstraint.activateConstraints_(
            [
                self.support.leadingAnchor().constraintEqualToAnchor_(
                    self.support_document.leadingAnchor()
                ),
                self.support.topAnchor().constraintEqualToAnchor_(
                    self.support_document.topAnchor()
                ),
            ]
        )
        self.group: Any = stack([self.board_panel, self.support_scroll], False, GAP)
        self.document: Any = AK.NSView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 800, 600))
        self.document.addSubview_(self.group)
        self.scroller: Any = AK.NSScrollView.alloc().initWithFrame_(AK.NSZeroRect)
        self.scroller.setHasVerticalScroller_(False)
        self.scroller.setAutohidesScrollers_(True)
        self.scroller.setDrawsBackground_(False)
        self.scroller.setDocumentView_(self.document)
        self.scroller.setVerticalScrollElasticity_(AK.NSScrollElasticityNone)
        self.scroller.setHorizontalScrollElasticity_(AK.NSScrollElasticityNone)
        self.scroller.setContentHuggingPriority_forOrientation_(
            1, AK.NSLayoutConstraintOrientationVertical
        )
        self.scroller.setContentCompressionResistancePriority_forOrientation_(
            1, AK.NSLayoutConstraintOrientationVertical
        )
        status: Any = controls["status"]
        self.root: Any = stack([self.header, self.scroller, self.actions, status], True, 8)
        content: Any = window.contentView()
        content.addSubview_(self.root)
        AK.NSLayoutConstraint.activateConstraints_(
            [
                self.root.leadingAnchor().constraintEqualToAnchor_constant_(
                    content.leadingAnchor(), 16
                ),
                self.root.trailingAnchor().constraintEqualToAnchor_constant_(
                    content.trailingAnchor(), -16
                ),
                self.root.topAnchor().constraintEqualToAnchor_constant_(content.topAnchor(), 12),
                self.root.bottomAnchor().constraintEqualToAnchor_constant_(
                    content.bottomAnchor(), -12
                ),
                self.group.centerXAnchor().constraintEqualToAnchor_(self.document.centerXAnchor()),
                self.group.topAnchor().constraintEqualToAnchor_constant_(
                    self.document.topAnchor(), PADDING
                ),
            ]
        )
        for child in (self.header, self.scroller, self.actions, status):
            fill_width(child, self.root)
        self.constraints["status_height"] = fixed(status, "height", 20)
        for key, view, attribute in (
            ("board_width", self.board_panel, "width"),
            ("board_height", self.board_panel, "height"),
            ("group_width", self.group, "width"),
            ("group_height", self.group, "height"),
            ("keypad_width", self.keypad, "width"),
            ("hint_width", self.hints, "width"),
            ("hint_height", self.hints, "height"),
            ("support_view_width", self.support_scroll, "width"),
            ("support_view_height", self.support_scroll, "height"),
            ("support_width", self.support, "width"),
            ("support_height", self.support, "height"),
        ):
            self.constraints[key] = fixed(view, attribute, 400)
        self.constraints["keypad_height"] = fixed(self.keypad, "height", KEYPAD_HEIGHT)

    def make_branding(self) -> None:
        """Keep icon, title, difficulty, and timer together above reflowing actions."""
        c: dict[str, Any] = self.controls
        c["title"].setFont_(AK.NSFont.systemFontOfSize_weight_(26, AK.NSFontWeightSemibold))
        for key in ("subtitle", "status"):
            c[key].setLineBreakMode_(AK.NSLineBreakByWordWrapping)
            c[key].cell().setWraps_(True)
            c[key].cell().setUsesSingleLineMode_(False)
        labels: Any = stack([c["title"], c["subtitle"]], True, 0)
        fixed(c["title"], "height", 32)
        self.constraints["subtitle_height"] = fixed(c["subtitle"], "height", 20)
        for child in (c["title"], c["subtitle"]):
            fill_width(child, labels)
        self.compact_menu: Any = AK.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            AK.NSZeroRect, True
        )
        self.compact_menu.setBezelStyle_(AK.NSBezelStyleGlass)
        self.compact_menu.setAccessibilityLabel_("Game actions")
        self.compact_menu.setFont_(AK.NSFont.systemFontOfSize_(14))
        self.compact_menu.cell().setArrowPosition_(AK.NSPopUpNoArrow)
        self.compact_menu.setHidden_(True)
        fixed(self.compact_menu, "width", 40)
        fixed(self.compact_menu, "height", 40)
        row: Any = stack([c["app_icon"], labels, c["timer"], self.compact_menu], False, 12)
        fixed(c["app_icon"], "width", 48)
        fixed(c["app_icon"], "height", 48)
        fixed(c["timer"], "width", 80)
        fixed(c["timer"], "height", 24)
        self.branding: Any = row
        self.header.addArrangedSubview_(row)
        fill_width(row, self.header)

    def make_keypad(self) -> Any:
        """Keep native entry switches above a permanent three-by-three digit grid."""
        c: dict[str, Any] = self.controls
        rows: list[Any] = []
        for offset in range(0, 9, 3):
            row: Any = stack(
                [c[f"digit{digit}"] for digit in range(offset + 1, offset + 4)], False, 8
            )
            row.setDistribution_(AK.NSStackViewDistributionFillEqually)
            self.constraints[f"digit_row_{offset}"] = fixed(row, "height", 44)
            for digit in range(offset + 1, offset + 4):
                self.constraints[f"digit_height_{digit}"] = fixed(c[f"digit{digit}"], "height", 44)
            rows.append(row)
        grid: Any = stack(rows, True, 8)
        self.digit_grid: Any = grid
        self.digit_rows: list[Any] = rows
        self.constraints["digit_grid_width"] = fixed(grid, "width", 260)
        for row in rows:
            fill_width(row, grid)
        result: Any = stack(
            [c["input_label"], c["order"], c["mode"], c["palette_label"], grid, c["footer"]],
            True,
            6,
        )
        for key, height in (
            ("input_label", 14),
            ("order", 28),
            ("mode", 28),
            ("palette_label", 20),
            ("footer", 32),
        ):
            fixed(c[key], "height", height)
        c["footer"].setLineBreakMode_(AK.NSLineBreakByWordWrapping)
        c["footer"].cell().setWraps_(True)
        c["footer"].cell().setUsesSingleLineMode_(False)
        result.setAlignment_(AK.NSLayoutAttributeCenterX)
        for child in result.arrangedSubviews():
            if child != grid:
                fill_width(child, result)
        return result

    def make_hints(self) -> Any:
        """Keep hint text independently scrollable with native actions outside its viewport."""
        c: dict[str, Any] = self.controls
        actions: Any = stack([c["previous_hint"], c["hint"], c["apply_hint"]], False, 4)
        self.hint_actions: Any = actions
        fixed(c["previous_hint"], "width", 50)
        fixed(c["apply_hint"], "width", 54)
        for key in ("previous_hint", "hint", "apply_hint", "another_hint", "reveal"):
            fixed(c[key], "height", 30)
        self.hint_alternatives: Any = stack([c["another_hint"], c["reveal"]], True, 0)
        fixed(self.hint_alternatives, "height", 30)
        for child in self.hint_alternatives.arrangedSubviews():
            fill_width(child, self.hint_alternatives)
        result: Any = stack(
            [c["hint_title"], c["hint_scroll"], actions, self.hint_alternatives], True, 8
        )
        fixed(c["hint_title"], "height", 24)
        fixed(actions, "height", 30)
        c["hint_scroll"].setContentHuggingPriority_forOrientation_(
            1, AK.NSLayoutConstraintOrientationVertical
        )
        for child in result.arrangedSubviews():
            fill_width(child, result)
        return result

    def button_rows(self, keys: list[str], width: float, parent: Any) -> None:
        """Wrap action rows using readable widths without replacing any buttons."""
        widths: dict[str, float] = {
            "new": 104,
            "daily": 116,
            "import": 116,
            "restart": 88,
            "pause": 80,
            "undo": 64,
            "redo": 64,
            "erase": 66,
            "fill": 120,
            "auto_complete": 124,
        }
        rows: list[list[str]] = [[]]
        used: float = 0
        for key in keys:
            needed: float = widths[key] + (8 if rows[-1] else 0)
            if used + needed > width and rows[-1]:
                rows.append([])
                used = 0
            rows[-1].append(key)
            used += widths[key] + (8 if len(rows[-1]) > 1 else 0)
        signature: tuple[tuple[str, ...], ...] = tuple(map(tuple, rows))
        attribute: str = "header_signature" if parent == self.header else "actions_signature"
        if getattr(self, attribute, ()) == signature:
            return
        for row in list(parent.arrangedSubviews()):
            if row == self.branding:
                continue
            for child in list(row.arrangedSubviews()):
                row.removeArrangedSubview_(child)
                child.removeFromSuperview()
            parent.removeArrangedSubview_(row)
            row.removeFromSuperview()
        for keys_in_row in rows:
            row = stack([self.controls[key] for key in keys_in_row], False, 8)
            fixed(row, "height", 30)
            parent.addArrangedSubview_(row)
            for key in keys_in_row:
                if f"button_{key}" not in self.constraints:
                    self.constraints[f"button_{key}"] = fixed(
                        self.controls[key], "width", widths[key]
                    )
                    fixed(self.controls[key], "height", 30)
        setattr(self, attribute, signature)

    def refresh_compact_menu(self) -> None:
        """Mirror existing button actions, availability, and entry choices in a native menu."""
        menu: Any = AK.NSMenu.alloc().initWithTitle_("Game actions")
        menu.setAutoenablesItems_(False)
        item: Any = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
        attributed_title: Any = AK.NSAttributedString.alloc().initWithString_attributes_(
            "≡",
            {AK.NSFontAttributeName: AK.NSFont.systemFontOfSize_(24)},  # Adjust the size as needed
        )
        item.setAttributedTitle_(attributed_title)
        menu.addItem_(item)
        for group in (
            ("new", "daily", "import", "restart", "pause"),
            ("undo", "redo", "erase", "fill", "auto_complete"),
            ("previous_hint", "hint", "apply_hint", "another_hint", "reveal"),
        ):
            if menu.numberOfItems() > 1:
                menu.addItem_(AK.NSMenuItem.separatorItem())
            for key in group:
                button: Any = self.controls[key]
                if button.isHidden():
                    continue
                item = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    button.title(), button.action(), ""
                )
                item.setTarget_(button.target())
                item.setEnabled_(button.isEnabled())
                menu.addItem_(item)
        self.compact_menu.setMenu_(menu)

    def update(self) -> None:
        """Change arrangements only at thresholds; resize constraints continuously within them."""
        if self.updating:
            return
        self.updating = True
        try:
            width: float = self.window.contentView().bounds().size.width - 32
            keys: list[str] = ["new"] + ([] if self.controls["daily"].isHidden() else ["daily"])
            self.button_rows(keys + ["import", "restart", "pause"], width, self.header)
            self.button_rows(
                ["undo", "redo", "erase", "fill", "auto_complete"], width, self.actions
            )
            # Measure the normal rows so hiding them cannot change the mode decision.
            for row in self.header.arrangedSubviews():
                row.setHidden_(False)
            self.actions.setHidden_(False)
            self.compact_menu.setHidden_(True)
            self.window.contentView().layoutSubtreeIfNeeded()
            for key in ("subtitle", "status"):
                label: Any = self.controls[key]
                label_width: float = label.bounds().size.width
                height: float = (
                    label.cell().cellSizeForBounds_(AK.NSMakeRect(0, 0, label_width, 1000)).height
                )
                self.constraints[f"{key}_height"].setConstant_(max(20, min(36, height)))
                label.setToolTip_(label.stringValue())
            self.window.contentView().layoutSubtreeIfNeeded()
            viewport: Any = self.scroller.contentView().bounds()
            distance_from_top: float = max(
                0, self.document.bounds().size.height - AK.NSMaxY(viewport)
            )
            plan: LayoutPlan = layout_plan(viewport.size.width, viewport.size.height, self.mode)
            vertical: bool = plan.mode not in ("wide", "short-wide")
            for row in self.header.arrangedSubviews():
                if row != self.branding:
                    row.setHidden_(vertical)
            self.actions.setHidden_(vertical)
            self.compact_menu.setHidden_(not vertical)
            self.keypad.setHidden_(False)
            self.hint_actions.setHidden_(vertical)
            self.hint_alternatives.setHidden_(vertical)
            self.refresh_compact_menu()
            self.window.contentView().layoutSubtreeIfNeeded()
            viewport = self.scroller.contentView().bounds()
            if vertical:
                available_height: float = viewport.size.height - 24 - GAP
                scale_limit: float = min(1.0, plan.panel_width / 260)
                board_size: float = (available_height - 152) / (1 + 148 / 588)
                if board_size / 588 > scale_limit:
                    board_size = available_height - 152 - 148 * scale_limit
                board_size = float(int(max(0, min(viewport.size.width - 24, board_size))))
                plan = replace(
                    plan,
                    board=board_size,
                    width=max(
                        board_size,
                        2 * plan.panel_width + GAP if plan.split_support else plan.panel_width,
                    ),
                    height=viewport.size.height - 24,
                )
                plan = replace(
                    plan, hint_height=max(120, plan.keypad_height) if plan.split_support else 120
                )
            changed: bool = plan.mode != self.mode
            if changed:
                self.mode = plan.mode
                horizontal: bool = plan.mode in ("wide", "short-wide")
                self.group.setOrientation_(
                    AK.NSUserInterfaceLayoutOrientationHorizontal
                    if horizontal
                    else AK.NSUserInterfaceLayoutOrientationVertical
                )
                self.group.setAlignment_(
                    AK.NSLayoutAttributeTop if horizontal else AK.NSLayoutAttributeCenterX
                )
                self.support.setOrientation_(
                    AK.NSUserInterfaceLayoutOrientationHorizontal
                    if plan.split_support
                    else AK.NSUserInterfaceLayoutOrientationVertical
                )
                self.support.setAlignment_(
                    AK.NSLayoutAttributeTop if plan.split_support else AK.NSLayoutAttributeLeading
                )
            support_width: float = (
                plan.panel_width * 2 + GAP if plan.split_support else plan.panel_width
            )
            support_height: float = (
                max(plan.keypad_height, plan.hint_height)
                if plan.split_support
                else plan.keypad_height + GAP + plan.hint_height
            )
            for key, value in {
                "board_width": plan.board,
                "board_height": plan.board,
                "group_width": plan.width,
                "group_height": plan.height,
                "keypad_width": plan.panel_width,
                "keypad_height": plan.keypad_height,
                "digit_grid_width": 260 * plan.keypad_scale,
                "hint_width": plan.panel_width,
                "hint_height": plan.hint_height,
                "support_view_width": support_width,
                "support_view_height": plan.height
                if plan.mode in ("wide", "short-wide")
                else plan.height - plan.board - GAP,
                "support_width": support_width,
                "support_height": support_height,
            }.items():
                self.constraints[key].setConstant_(value)
            for offset, row in zip(range(0, 9, 3), self.digit_rows, strict=True):
                self.constraints[f"digit_row_{offset}"].setConstant_(44 * plan.keypad_scale)
                row.setSpacing_(8 * plan.keypad_scale)
            self.digit_grid.setSpacing_(8 * plan.keypad_scale)
            for digit in range(1, 10):
                self.constraints[f"digit_height_{digit}"].setConstant_(44 * plan.keypad_scale)
                self.controls[f"digit{digit}"].setFont_(
                    AK.NSFont.systemFontOfSize_(24 * plan.keypad_scale)
                )
            support_view_height: float = self.constraints["support_view_height"].constant()
            old_support_view: Any = self.support_scroll.contentView().bounds()
            support_top_offset: float = max(
                0, self.support_document.bounds().size.height - AK.NSMaxY(old_support_view)
            )
            self.support_document.setFrameSize_(
                (support_width, max(support_height, support_view_height))
            )
            self.document.layoutSubtreeIfNeeded()
            self.support_document.layoutSubtreeIfNeeded()
            self.support_document.scrollPoint_(
                (
                    0,
                    max(
                        0,
                        support_height
                        - support_view_height
                        - (0 if changed else support_top_offset),
                    ),
                )
            )
            document_height: float = viewport.size.height
            self.document.setFrameSize_((viewport.size.width, document_height))
            self.document.layoutSubtreeIfNeeded()
            scroll_offset: float = 0 if changed else distance_from_top
            self.document.scrollPoint_(
                (0, max(0, document_height - viewport.size.height - scroll_offset))
            )
            self.scroller.reflectScrolledClipView_(self.scroller.contentView())
            self.window.invalidateCursorRectsForView_(self.board)
            self.board.setNeedsDisplay_(True)
        finally:
            self.updating = False
