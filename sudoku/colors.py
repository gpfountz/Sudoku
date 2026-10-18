# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Names and compatibility access for persistent annotation colors."""

from typing import Any

from sudoku.theme import DEFAULT_THEME

COLOR_NAMES: tuple[str, ...] = DEFAULT_THEME.annotations.names


def highlight_color(index: int) -> Any:
    """Return the original palette color for older callers."""
    return DEFAULT_THEME.annotations.color(index)
