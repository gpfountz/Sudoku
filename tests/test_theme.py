# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Check named themes and their adaptive text contrast without opening windows."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import pytest

from sudoku.app import AppController
from sudoku.model import Preferences
from sudoku.storage import Store
from sudoku.theme import (
    DEFAULT_THEME,
    THEMES,
    WARM_PAPER_THEME,
    SolidBackground,
    Theme,
    theme_for_name,
)
from sudoku.theme_names import THEME_NAMES
from sudoku.theme_palettes import ACCENT_PALETTES, PALETTES


def _relative_luminance(color: Any) -> float:
    """Calculate sRGB luminance for readable foreground/background checks."""
    rgb: Any = color.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
    channels: tuple[float, ...] = (
        float(rgb.redComponent()),
        float(rgb.greenComponent()),
        float(rgb.blueComponent()),
    )
    linear: tuple[float, ...] = tuple(
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: Any, second: Any) -> float:
    """Compare two opaque sRGB colors using their luminance ratio."""
    brighter: float = max(_relative_luminance(first), _relative_luminance(second))
    darker: float = min(_relative_luminance(first), _relative_luminance(second))
    return (brighter + 0.05) / (darker + 0.05)


def test_named_themes_fall_back_to_existing_default() -> None:
    """Keep unknown saved names safe and preserve the original theme identity."""
    assert THEME_NAMES == (
        "Default",
        "Default Teal",
        "Default Forest",
        "Default Plum",
        "Default Bronze",
        "Default Olive",
        "Default Espresso",
        "Default Graphite",
        "Default Orchid",
        "Warm Paper",
        "Sage Linen",
        "Coastal Mist",
        "Lavender Slate",
        "Tangerine Cream",
        "Rose Clay",
        "Peony Pink",
        "High Contrast",
        "Autumn Harvest",
        "Winter Frost",
    )
    assert tuple(THEMES) == THEME_NAMES
    assert theme_for_name("Default") is DEFAULT_THEME
    assert theme_for_name("Warm Paper") is WARM_PAPER_THEME
    assert theme_for_name("Unrecognized") is DEFAULT_THEME


@pytest.mark.parametrize("name", THEME_NAMES[1:])
def test_theme_setting_updates_runtime_palette_without_changing_appearance(name: str) -> None:
    """Keep theme selection independent and persist it through the existing save path."""
    preferences: Preferences = Preferences(appearance="Dark")
    controller: Any = AppController.alloc().init()
    controller.preferences = preferences
    controller.theme = DEFAULT_THEME
    controller.apply_appearance = Mock()
    controller.save = Mock()
    controller.refresh = Mock()
    sender: Any = SimpleNamespace(
        identifier=lambda: "theme",
        titleOfSelectedItem=lambda: name,
    )

    AppController.preferenceChanged_(controller, sender)

    assert preferences.theme == name
    assert preferences.appearance == "Dark"
    assert controller.theme is THEMES[name]
    controller.apply_appearance.assert_called_once()
    controller.save.assert_called_once()


@pytest.mark.parametrize("name", tuple(PALETTES))
@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_named_palettes_keep_board_and_control_text_readable(name: str, appearance: str) -> None:
    """Check real adaptive colors for text, selected controls, and highlighted candidates."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
        theme: Theme = THEMES[name]
        background: Any = theme.board.background
        assert isinstance(background, SolidBackground)
        assert _contrast_ratio(theme.text, background.color) >= 7.0
        minimum: float = 7.0 if theme.high_contrast else 4.5
        assert _contrast_ratio(theme.controls.selected_text, theme.accent) >= minimum
        assert _contrast_ratio(theme.secondary_text, theme.window_background) >= minimum
        assert _contrast_ratio(theme.text, theme.controls.background) >= minimum
        assert _contrast_ratio(theme.text, theme.controls.pressed_background) >= minimum
        candidate_fill: Any = background.color.blendedColorWithFraction_ofColor_(
            theme.board.matching_candidate_fill.opacity, theme.accent
        )
        assert _contrast_ratio(theme.text, candidate_fill) >= minimum
        if theme.high_contrast:
            assert _contrast_ratio(theme.accent, background.color) >= minimum
            assert theme.board.major_grid.opacity == 1.0
            assert theme.board.minor_grid.opacity >= 0.7
        assert theme.annotations is DEFAULT_THEME.annotations
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


@pytest.mark.parametrize("name", tuple(PALETTES))
@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_incorrect_answer_palette_is_red_readable_and_distinct(name: str, appearance: str) -> None:
    """Keep error ink unmistakably red, readable on paper, and distinct from valid answers."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
        theme: Theme = THEMES[name]
        palette: Any = (
            PALETTES[name].light if appearance == AK.NSAppearanceNameAqua else PALETTES[name].dark
        )
        error: Any = theme.hints.error_text.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
        channels: tuple[float, ...] = (
            error.redComponent(),
            error.greenComponent(),
            error.blueComponent(),
        )
        expected: tuple[float, ...] = tuple(
            int(palette.incorrect_answer[offset : offset + 2], 16) / 255 for offset in (0, 2, 4)
        )
        assert channels == pytest.approx(expected)
        red: float = channels[0]
        green: float = channels[1]
        blue: float = channels[2]
        assert red >= 0.7
        assert red - max(green, blue) >= 0.55
        assert abs(green - blue) <= 0.08
        background: Any = theme.board.background
        assert isinstance(background, SolidBackground)
        paper: Any = background.color.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
        accent: Any = theme.accent.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
        # Bold answer digits favor a clear red error signal over muted high-contrast ink.
        assert _contrast_ratio(error, paper) >= (4.5 if theme.high_contrast else 3.0)
        accent_channels: tuple[float, ...] = (
            accent.redComponent(),
            accent.greenComponent(),
            accent.blueComponent(),
        )
        # Contrast with paper alone cannot ensure an error differs from a valid answer.
        assert (
            sum(
                (first - second) ** 2
                for first, second in zip(channels, accent_channels, strict=True)
            )
            ** 0.5
            >= 0.3
        )
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


@pytest.mark.parametrize("name", THEME_NAMES[1:])
def test_named_palettes_change_with_mac_appearance(name: str) -> None:
    """System appearance switches the same saved theme between its two palettes."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        colors: list[float] = []
        for appearance in (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua):
            AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
            background: Any = THEMES[name].board.background
            assert isinstance(background, SolidBackground)
            colors.append(_relative_luminance(background.color))
        assert colors[0] > colors[1]
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


@pytest.mark.parametrize("name", tuple(ACCENT_PALETTES))
@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_default_accent_themes_preserve_native_surfaces_and_contrast(
    name: str, appearance: str
) -> None:
    """Keep Default's native cues and readable accent digits across both appearances."""
    original: Any = AK.NSAppearance.currentAppearance()
    try:
        AK.NSAppearance.setCurrentAppearance_(AK.NSAppearance.appearanceNamed_(appearance))
        theme: Theme = theme_for_name(name)
        background: Any = theme.board.background
        assert isinstance(background, SolidBackground)
        assert background is DEFAULT_THEME.board.background
        assert theme.text is DEFAULT_THEME.text
        assert theme.secondary_text is DEFAULT_THEME.secondary_text
        assert theme.window_background is DEFAULT_THEME.window_background
        assert theme.hints is DEFAULT_THEME.hints
        assert theme.annotations is DEFAULT_THEME.annotations
        assert theme.board.major_grid is DEFAULT_THEME.board.major_grid
        assert theme.board.minor_grid is DEFAULT_THEME.board.minor_grid
        assert theme.controls.background is DEFAULT_THEME.controls.background
        assert theme.controls.border is DEFAULT_THEME.controls.border
        accent: Any = theme.accent.colorUsingColorSpace_(AK.NSColorSpace.sRGBColorSpace())
        expected_hex: str = ACCENT_PALETTES[name][0 if appearance == AK.NSAppearanceNameAqua else 1]
        assert (accent.redComponent(), accent.greenComponent(), accent.blueComponent()) == (
            pytest.approx(
                tuple(int(expected_hex[index : index + 2], 16) / 255 for index in (0, 2, 4))
            )
        )
        for role in (
            "peer_fill",
            "matching_answer_fill",
            "matching_candidate_fill",
            "candidate_guides",
        ):
            token: Any = getattr(theme.board, role)
            assert token.base is theme.accent
            assert token.opacity == getattr(DEFAULT_THEME.board, role).opacity
        assert theme.controls.active_menu_fill.base is theme.accent
        assert _contrast_ratio(theme.accent, background.color) >= 4.5
        assert _contrast_ratio(theme.controls.selected_text, theme.accent) >= 4.5
        assert _contrast_ratio(theme.text, theme.controls.pressed_background) >= 4.5
        matching_fill: Any = background.color.blendedColorWithFraction_ofColor_(
            theme.board.matching_answer_fill.opacity, theme.accent
        )
        # AppKit's native blending differs from the sRGB preview; large digits need 3:1.
        assert _contrast_ratio(theme.accent, matching_fill) >= 3.0
        peer_fill: Any = background.color.blendedColorWithFraction_ofColor_(
            theme.board.peer_fill.opacity, theme.accent
        )
        combined_fill: Any = peer_fill.blendedColorWithFraction_ofColor_(
            theme.board.matching_answer_fill.opacity, theme.accent
        )
        # Large answer digits must also stay readable where both overlays are painted.
        assert _contrast_ratio(theme.accent, combined_fill) >= 3.0
        candidate_fill: Any = peer_fill.blendedColorWithFraction_ofColor_(
            theme.board.matching_candidate_fill.opacity, theme.accent
        )
        assert _contrast_ratio(theme.text, candidate_fill) >= 4.5
    finally:
        AK.NSAppearance.setCurrentAppearance_(original)


@pytest.mark.parametrize("name", THEME_NAMES)
def test_theme_names_roundtrip_through_existing_preferences(tmp_path: Path, name: str) -> None:
    """Keep new and legacy theme names in the same backward-compatible preference schema."""
    store: Store = Store(tmp_path)
    preferences: Preferences = Preferences(
        appearance="Dark", theme=name, daily_enabled=True, input_order="Number First"
    )
    store.save_preferences(preferences)
    assert Store(tmp_path).load_preferences() == preferences
