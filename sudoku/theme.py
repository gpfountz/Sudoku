# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Semantic, appearance-aware presentation colors for the native Sudoku UI."""

from dataclasses import dataclass, replace
from typing import Any, Protocol

import AppKit as AK

from sudoku.theme_names import DEFAULT_THEME_NAME, THEME_NAMES, WARM_PAPER_THEME_NAME
from sudoku.theme_palettes import ACCENT_PALETTES, PALETTES, PalettePair


class Background(Protocol):
    """Draw a themed surface; future image backgrounds can use this contract."""

    def draw(self, bounds: Any) -> None:
        """Fill the supplied AppKit drawing rectangle."""
        ...


@dataclass(frozen=True)
class SolidBackground:
    """Fill a themed surface with one adaptive native color."""

    color: Any

    def draw(self, bounds: Any) -> None:
        """Paint the full background before cells and annotations are drawn."""
        self.color.setFill()
        AK.NSRectFill(bounds)


@dataclass(frozen=True)
class ColorToken:
    """Resolve a translucent color in the view's current macOS appearance."""

    base: Any
    opacity: float

    def resolve(self) -> Any:
        """Apply opacity at draw time so Light and Dark colors stay adaptive."""
        return self.base.colorWithAlphaComponent_(self.opacity)


@dataclass(frozen=True)
class BoardTheme:
    """Colors and surface treatment used by the custom puzzle view."""

    background: Background
    peer_fill: ColorToken
    matching_answer_fill: ColorToken
    matching_candidate_fill: ColorToken
    major_grid: ColorToken
    minor_grid: ColorToken
    candidate_guides: ColorToken
    cursor_fill: Any
    cursor_outline: Any


@dataclass(frozen=True)
class ControlTheme:
    """Colors shared by keypad tiles and custom context-menu content."""

    background: Any
    pressed_background: Any
    border: Any
    selected_text: Any
    active_menu_fill: ColorToken
    dimmed_opacity: float = 0.38


@dataclass(frozen=True)
class HintTheme:
    """Colors that distinguish hint evidence, placements, and errors."""

    focus_fill: ColorToken
    error_fill: ColorToken
    error_text: Any
    evidence_stroke: Any
    placement_stroke: Any
    removal_stroke: Any


@dataclass(frozen=True)
class AnnotationTheme:
    """Keep the eight persistent color indices independent of their appearance."""

    names: tuple[str, ...]
    swatches: tuple[Any, ...]
    cell_opacity: float = 0.27
    tile_opacity: float = 0.28
    selected_tile_opacity: float = 0.48

    def __post_init__(self) -> None:
        """Keep visual swatches and spoken names aligned for every saved index."""
        if len(self.names) != 8 or len(self.swatches) != 8:
            raise ValueError("A Sudoku theme must name and color all eight annotation slots")

    def name(self, index: int) -> str:
        """Return the accessible name for a one-based annotation index."""
        if not 1 <= index <= len(self.names):
            raise ValueError(f"Annotation color {index} is out of range")
        return self.names[index - 1]

    def color(self, index: int) -> Any:
        """Return the color for a one-based, non-clear annotation index."""
        if not 1 <= index <= len(self.swatches):
            raise ValueError(f"Annotation color {index} is out of range")
        return self.swatches[index - 1]

    def cell_fill(self, index: int) -> Any:
        """Return the translucent overlay used for a colored puzzle cell."""
        return self.color(index).colorWithAlphaComponent_(self.cell_opacity)

    def tile_fill(self, index: int, selected: bool) -> Any:
        """Return the keypad or context-menu swatch fill."""
        opacity: float = self.selected_tile_opacity if selected else self.tile_opacity
        return self.color(index).colorWithAlphaComponent_(opacity)


@dataclass(frozen=True)
class Theme:
    """Collect semantic colors without coupling saved games to a palette."""

    text: Any
    secondary_text: Any
    accent: Any
    board: BoardTheme
    controls: ControlTheme
    hints: HintTheme
    annotations: AnnotationTheme
    window_background: Any | None = None
    high_contrast: bool = False


def default_theme() -> Theme:
    """Preserve today's adaptive AppKit colors in one replaceable theme."""
    accent: Any = AK.NSColor.controlAccentColor()
    text: Any = AK.NSColor.labelColor()
    orange: Any = AK.NSColor.systemOrangeColor()
    red: Any = AK.NSColor.systemRedColor()
    return Theme(
        text=text,
        secondary_text=AK.NSColor.secondaryLabelColor(),
        accent=accent,
        board=BoardTheme(
            background=SolidBackground(AK.NSColor.textBackgroundColor()),
            peer_fill=ColorToken(accent, 0.045),
            matching_answer_fill=ColorToken(accent, 0.25),
            matching_candidate_fill=ColorToken(accent, 0.30),
            major_grid=ColorToken(text, 0.60),
            minor_grid=ColorToken(text, 0.18),
            candidate_guides=ColorToken(accent, 0.45),
            cursor_fill=AK.NSColor.blackColor(),
            cursor_outline=AK.NSColor.whiteColor(),
        ),
        controls=ControlTheme(
            background=AK.NSColor.controlBackgroundColor(),
            pressed_background=AK.NSColor.selectedControlColor(),
            border=AK.NSColor.separatorColor(),
            selected_text=AK.NSColor.whiteColor(),
            active_menu_fill=ColorToken(accent, 0.32),
        ),
        hints=HintTheme(
            focus_fill=ColorToken(orange, 0.18),
            error_fill=ColorToken(red, 0.11),
            error_text=red,
            evidence_stroke=orange,
            placement_stroke=AK.NSColor.systemGreenColor(),
            removal_stroke=red,
        ),
        annotations=AnnotationTheme(
            names=("Red", "Orange", "Yellow", "Green", "Teal", "Blue", "Purple", "Pink"),
            swatches=(
                AK.NSColor.systemRedColor(),
                orange,
                AK.NSColor.systemYellowColor(),
                AK.NSColor.systemGreenColor(),
                AK.NSColor.systemTealColor(),
                AK.NSColor.systemBlueColor(),
                AK.NSColor.systemPurpleColor(),
                AK.NSColor.systemPinkColor(),
            ),
        ),
    )


DEFAULT_THEME: Theme = default_theme()


def _rgb_color(hex_value: str) -> Any:
    """Convert an opaque six-digit RGB value into an sRGB AppKit color."""
    return AK.NSColor.colorWithSRGBRed_green_blue_alpha_(
        int(hex_value[0:2], 16) / 255,
        int(hex_value[2:4], 16) / 255,
        int(hex_value[4:6], 16) / 255,
        1.0,
    )


def _adaptive_color(role: str, light_hex: str, dark_hex: str) -> Any:
    """Resolve a uniquely named theme role when macOS changes effective appearance."""
    light: Any = _rgb_color(light_hex)
    dark: Any = _rgb_color(dark_hex)

    def color_for_appearance(appearance: Any) -> Any:
        """Use the dark variant for Dark and vibrant-dark appearances."""
        matching: Any = appearance.bestMatchFromAppearancesWithNames_(
            (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua)
        )
        return dark if matching == AK.NSAppearanceNameDarkAqua else light

    return AK.NSColor.colorWithName_dynamicProvider_(f"Sudoku.{role}", color_for_appearance)


def _pressed_colors(palette: PalettePair) -> tuple[str, str]:
    """Tint pressed tiles toward the accent while preserving Warm Paper's old colors."""
    if palette.pressed is not None:
        return palette.pressed
    colors: list[str] = []
    for variant in (palette.light, palette.dark):
        channels: list[int] = [
            round(
                int(variant.control[i : i + 2], 16) * 0.82
                + int(variant.accent[i : i + 2], 16) * 0.18
            )
            for i in (0, 2, 4)
        ]
        colors.append("".join(f"{channel:02X}" for channel in channels))
    return colors[0], colors[1]


def palette_theme(name: str, palette: PalettePair) -> Theme:
    """Map one appearance pair into the shared semantic drawing and control roles."""

    def color(role: str) -> Any:
        """Create a named adaptive native color for a palette field."""
        return _adaptive_color(
            f"{name}.{role}", getattr(palette.light, role), getattr(palette.dark, role)
        )

    paper: Any = color("board")
    ink: Any = color("text")
    accent: Any = color("accent")
    contrast: bool = palette.high_contrast
    error: Any = color("incorrect_answer")
    evidence: Any = color("evidence")
    return Theme(
        text=ink,
        secondary_text=color("secondary_text"),
        accent=accent,
        board=BoardTheme(
            background=SolidBackground(paper),
            peer_fill=ColorToken(accent, 0.04 if contrast else 0.09),
            matching_answer_fill=ColorToken(accent, 0.14 if contrast else 0.24),
            matching_candidate_fill=ColorToken(accent, 0.14 if contrast else 0.28),
            major_grid=ColorToken(ink, 1.0 if contrast else 0.62),
            minor_grid=ColorToken(ink, 0.70 if contrast else 0.21),
            candidate_guides=ColorToken(accent, 0.75 if contrast else 0.48),
            cursor_fill=ink,
            cursor_outline=paper,
        ),
        controls=ControlTheme(
            background=color("control"),
            pressed_background=_adaptive_color(f"{name}.pressed", *_pressed_colors(palette)),
            border=color("border"),
            selected_text=color("selected_text"),
            active_menu_fill=ColorToken(accent, 0.14 if contrast else 0.27),
            dimmed_opacity=0.72 if contrast else 0.38,
        ),
        hints=HintTheme(
            focus_fill=ColorToken(evidence, 0.21),
            error_fill=ColorToken(error, 0.13),
            error_text=error,
            evidence_stroke=evidence,
            placement_stroke=_adaptive_color(
                f"{name}.placement",
                "005425" if contrast else "38734B",
                "97F5AF" if contrast else "8FD2A1",
            ),
            removal_stroke=error,
        ),
        annotations=DEFAULT_THEME.annotations,
        window_background=color("window"),
        high_contrast=contrast,
    )


def warm_paper_theme() -> Theme:
    """Build the original Warm Paper palette through the shared theme factory."""
    return palette_theme(WARM_PAPER_THEME_NAME, PALETTES[WARM_PAPER_THEME_NAME])


def accent_theme(name: str, colors: tuple[str, str]) -> Theme:
    """Replace Default's accent while retaining its native surfaces and drawing cues."""
    accent: Any = _adaptive_color(f"{name}.accent", *colors)
    board: BoardTheme = DEFAULT_THEME.board
    controls: ControlTheme = DEFAULT_THEME.controls
    return replace(
        DEFAULT_THEME,
        accent=accent,
        board=replace(
            board,
            peer_fill=replace(board.peer_fill, base=accent),
            matching_answer_fill=replace(board.matching_answer_fill, base=accent),
            matching_candidate_fill=replace(board.matching_candidate_fill, base=accent),
            candidate_guides=replace(board.candidate_guides, base=accent),
        ),
        controls=replace(
            controls,
            pressed_background=AK.NSColor.unemphasizedSelectedContentBackgroundColor(),
            selected_text=_adaptive_color(f"{name}.selected_text", "FFFFFF", "1E1E1E"),
            active_menu_fill=replace(controls.active_menu_fill, base=accent),
        ),
    )


THEMES: dict[str, Theme] = {DEFAULT_THEME_NAME: DEFAULT_THEME}
THEMES.update(
    {
        name: (
            accent_theme(name, ACCENT_PALETTES[name])
            if name in ACCENT_PALETTES
            else palette_theme(name, PALETTES[name])
        )
        for name in THEME_NAMES[1:]
    }
)
WARM_PAPER_THEME: Theme = THEMES[WARM_PAPER_THEME_NAME]


def theme_for_name(name: str) -> Theme:
    """Return a registered theme, falling back to the original appearance."""
    return THEMES.get(name, DEFAULT_THEME)
