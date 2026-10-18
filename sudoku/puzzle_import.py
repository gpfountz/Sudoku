# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Parse and validate imported Sudoku clues independently of recognition and UI."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from sudoku.engine import conflicts, solve


@dataclass(frozen=True)
class ValidatedImport:
    """Retain the reviewed clues and unique solution without exposing answers in review."""

    givens: tuple[int, ...]
    solution: tuple[int, ...]


def parse_grid(text: str) -> tuple[int, ...]:
    """Accept exactly 81 ASCII digits or dots, with optional whitespace between cells."""
    compact: str = "".join(text.split())
    if len(compact) != 81 or any(character not in "0123456789." for character in compact):
        raise ValueError("Copy an image or a grid of 81 digits, using 0 or . for empty cells.")
    return tuple(0 if character == "." else int(character) for character in compact)


def validate_import(
    givens: tuple[int, ...],
    timeout: float = 10.0,
    cancelled: Callable[[], bool] | None = None,
) -> ValidatedImport:
    """Reject conflicting, unsolvable, or nonunique clues within a bounded solve time."""
    if len(givens) != 81 or any(type(value) is not int or not 0 <= value <= 9 for value in givens):
        raise ValueError("A puzzle must contain 81 cells with digits from 1 to 9 or blanks.")
    if conflicts(givens):
        raise ValueError("Some clues repeat in a row, column, or box. Correct the marked cells.")
    if sum(bool(value) for value in givens) < 17:
        raise ValueError("Too few clues for a unique classic Sudoku. Check for missed digits.")
    deadline: float = time.monotonic() + timeout
    solutions: list[tuple[int, ...]] = solve(
        givens,
        should_stop=lambda: time.monotonic() >= deadline or (cancelled is not None and cancelled()),
    )
    if not solutions:
        raise ValueError("These clues have no solution. Compare them with the source image.")
    if len(solutions) != 1:
        raise ValueError("Multiple solutions. Check for missed or incorrect clues.")
    return ValidatedImport(givens, solutions[0])
