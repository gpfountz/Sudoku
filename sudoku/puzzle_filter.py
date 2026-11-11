# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Screen new puzzles using the same deductions as the hint system."""

from collections.abc import Callable, Iterator
from functools import lru_cache

from sudoku.hint_types import Hint
from sudoku.hints import hint_searches
from sudoku.model import Game, Puzzle

SHORT_CHAIN_MAX_LINKS: int = 5


@lru_cache(maxsize=4096)
def solves_without_long_chains(puzzle: Puzzle) -> bool:
    """Find a full logical solve from the givens with general chains capped at five links."""
    game: Game = Game(puzzle)
    searches: tuple[Callable[[list[set[int]]], Iterator[Hint]], ...] = hint_searches(
        game, max_chain_links=SHORT_CHAIN_MAX_LINKS
    )
    while not game.complete:
        options: list[set[int]] = game.logical_candidates()
        deductions: list[Hint] = next(
            (found for search in searches if (found := list(search(options)))), []
        )
        if not deductions:
            return False
        # These deductions all apply to the same candidate state. Keep their exclusions
        # across placements, independently of how the interactive board manages notes.
        for hint in deductions:
            for index, digit in hint.placements:
                if digit != puzzle.solution[index]:
                    return False
                game.values[index] = digit
            for index, digit in hint.eliminations:
                if digit == puzzle.solution[index]:
                    return False
                game.excluded[index].add(digit)
    return True
