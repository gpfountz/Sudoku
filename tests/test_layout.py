# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Adaptive arrangements, containment, hysteresis, and screen restoration checks."""

import pytest

from sudoku.layout import GAP, fit_window_frame, layout_plan


@pytest.mark.parametrize(
    ("width", "height", "mode"),
    [
        (1088, 632, "wide"),
        (668, 812, "narrow-split"),
        (668, 532, "narrow-split"),
        (1168, 452, "short-wide"),
        (488, 414, "narrow-stack"),
        (688, 552, "wide"),
    ],
)
def test_arrangements_fit_readable_panels(width: float, height: float, mode: str) -> None:
    """Contain all three panels horizontally, allowing vertical compact scrolling."""
    plan = layout_plan(width, height)
    assert plan.mode == mode
    assert 0 < plan.board <= height - 24
    assert plan.width + 24 <= width
    assert plan.panel_width >= 220
    assert plan.hint_height >= 224
    support_width = 2 * plan.panel_width + GAP if plan.split_support else plan.panel_width
    support_height = (
        max(plan.keypad_height, plan.hint_height)
        if plan.split_support
        else plan.keypad_height + GAP + plan.hint_height
    )
    if mode in ("wide", "short-wide"):
        assert plan.width == plan.board + GAP + support_width
        assert plan.height >= plan.board
        assert plan.height <= height - 24
    else:
        assert plan.height <= plan.board + GAP + support_height
        assert plan.height - plan.board - GAP >= 120
        assert plan.width >= max(plan.board, support_width)


@pytest.mark.parametrize(
    ("previous", "width", "height", "expected"),
    [
        ("wide", 840, 540, "wide"),
        ("wide", 659, 600, "narrow-split"),
        ("wide", 1088, 525, "short-wide"),
        ("short-wide", 1088, 570, "short-wide"),
        ("short-wide", 1088, 582, "wide"),
        ("narrow-split", 550, 800, "narrow-split"),
        ("narrow-split", 479, 800, "narrow-stack"),
        ("narrow-stack", 490, 800, "narrow-stack"),
    ],
)
def test_transition_exit_band(previous: str, width: float, height: float, expected: str) -> None:
    """Retain the arrangement near a boundary instead of flickering between modes."""
    assert layout_plan(width, height, previous).mode == expected


def test_continuous_resize_contains_panels() -> None:
    """Sweep both dimensions through transitions without horizontal overflow."""
    previous: str = ""
    for height in range(350, 1000, 37):
        for width in [*range(368, 1500, 11), *range(1500, 368, -11)]:
            plan = layout_plan(width, height, previous)
            assert plan.width + 24 <= width
            assert 0 < plan.board <= height - 24
            previous = plan.mode


@pytest.mark.parametrize(
    ("frame", "visible", "expected"),
    [
        ((100, 100, 900, 700), (0, 25, 1440, 850), (100, 100, 900, 700)),
        ((2000, -100, 1600, 1000), (0, 25, 1440, 850), (0, 25, 1440, 850)),
        ((-1800, 100, 600, 700), (-1440, 25, 1440, 850), (-1440, 100, 600, 700)),
    ],
)
def test_restoration_stays_on_available_screen(
    frame: tuple[float, float, float, float],
    visible: tuple[float, float, float, float],
    expected: tuple[float, float, float, float],
) -> None:
    """Retain usable saved geometry and recover from disconnected or smaller screens."""
    assert fit_window_frame(frame, visible) == expected


@pytest.mark.parametrize("height", [300, 600, 900, 1200])
def test_vertical_board_uses_full_width(height: float) -> None:
    """Use full width only when the complete board also fits above the controls."""
    plan = layout_plan(488, height)
    assert plan.board == min(464, height - 24 - GAP - 120)
    assert plan.width >= plan.board


def test_keypad_scales_with_board_and_controls_narrow() -> None:
    """Shrink tiles proportionally without tying control text to the board scale."""
    large = layout_plan(1168, 600)
    small = layout_plan(1168, 310)
    assert small.board == 286
    assert small.panel_width == 220
    assert small.panel_width < large.panel_width
    assert small.keypad_scale / large.keypad_scale == pytest.approx(small.board / large.board)
    assert small.keypad_height < large.keypad_height
