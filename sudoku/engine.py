# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Sudoku constraints, validation, and uniqueness checking."""

from collections.abc import Callable, Sequence

DIGITS: frozenset[int] = frozenset(range(1, 10))
ROWS: tuple[tuple[int, ...], ...] = tuple(tuple(r * 9 + c for c in range(9)) for r in range(9))
COLUMNS: tuple[tuple[int, ...], ...] = tuple(tuple(r * 9 + c for r in range(9)) for c in range(9))
BOXES: tuple[tuple[int, ...], ...] = tuple(
    tuple((br + r) * 9 + bc + c for r in range(3) for c in range(3))
    for br in (0, 3, 6)
    for bc in (0, 3, 6)
)
UNITS: tuple[tuple[int, ...], ...] = ROWS + COLUMNS + BOXES
PEERS: tuple[frozenset[int], ...] = tuple(
    frozenset(j for unit in UNITS if i in unit for j in unit if j != i) for i in range(81)
)


def cell_name(index: int) -> str:
    """Return the human-readable coordinate of a cell."""
    return f"row {index // 9 + 1}, column {index % 9 + 1}"


def candidates(values: Sequence[int]) -> list[set[int]]:
    """Find candidates permitted by entered values, independent of player notes."""
    return [
        set(DIGITS - {values[j] for j in PEERS[i]}) if not value else set()
        for i, value in enumerate(values)
    ]


def conflicts(values: Sequence[int]) -> set[int]:
    """Identify every filled cell involved in a duplicate constraint violation."""
    return {
        i for i, value in enumerate(values) if value and any(values[j] == value for j in PEERS[i])
    }


def solve(
    values: Sequence[int], limit: int = 2, *, should_stop: Callable[[], bool] | None = None
) -> list[tuple[int, ...]]:
    """Find at most limit solutions with minimum-candidate backtracking."""
    if len(values) != 81 or any(type(value) is not int or not 0 <= value <= 9 for value in values):
        return []
    if conflicts(values):
        return []
    board: list[int] = list(values)
    solutions: list[tuple[int, ...]] = []

    def search() -> None:
        """Explore the most constrained empty cell and stop at the requested limit."""
        if should_stop is not None and should_stop():
            raise TimeoutError("Validation took too long. Check the clues and try again.")
        if len(solutions) >= limit:
            return
        best: int = -1
        options: set[int] = set(range(1, 11))
        for index, value in enumerate(board):
            if value:
                continue
            available: set[int] = set(DIGITS - {board[j] for j in PEERS[index]})
            if not available:
                return
            if len(available) < len(options):
                best, options = index, available
                if len(options) == 1:
                    break
        if best == -1:
            solutions.append(tuple(board))
            return
        for digit in sorted(options):
            board[best] = digit
            search()
            if len(solutions) >= limit:
                break
        board[best] = 0

    search()
    return solutions
