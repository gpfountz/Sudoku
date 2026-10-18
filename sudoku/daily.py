# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Choose a daily difficulty in proportion to bundled puzzle counts."""

import random
from collections.abc import Mapping, Sized

from sudoku.model import LEVELS


def choose_daily_level(catalog: Mapping[str, Sized], minimum: str, maximum: str) -> str:
    """Select an in-range level with one ticket per catalog puzzle."""
    first: int = LEVELS.index(minimum)
    last: int = LEVELS.index(maximum)
    if first > last:
        raise ValueError("Daily difficulty range is reversed")
    levels: tuple[str, ...] = LEVELS[first : last + 1]
    counts: tuple[int, ...] = tuple(len(catalog[level]) for level in levels)
    total: int = sum(counts)
    if total < 1:
        raise ValueError("No puzzles are available in the daily difficulty range")
    ticket: int = random.SystemRandom().randrange(total)
    for level, count in zip(levels, counts, strict=True):
        if ticket < count:
            return level
        ticket -= count
    raise AssertionError("Daily level ticket was not assigned")
