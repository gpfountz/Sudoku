# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Uniqueness deductions, enabled only after the original clues pass a uniqueness check."""

from collections.abc import Iterator
from functools import lru_cache
from itertools import combinations

from sudoku.engine import DIGITS, PEERS, UNITS, cell_name, solve
from sudoku.hint_types import Hint, removal_hint
from sudoku.model import Game


@lru_cache(maxsize=128)
def uniquely_solvable(givens: tuple[int, ...]) -> bool:
    """Verify original clues, rather than trusting a saved answer or a puzzle label."""
    return len(solve(givens, limit=2)) == 1


def rectangles() -> Iterator[tuple[int, int, int, int]]:
    """Visit four corners in two rows, two columns, and exactly two boxes."""
    for r1, r2 in combinations(range(9), 2):
        for c1, c2 in combinations(range(9), 2):
            if (r1 // 3 == r2 // 3) != (c1 // 3 == c2 // 3):
                yield (r1 * 9 + c1, r1 * 9 + c2, r2 * 9 + c1, r2 * 9 + c2)


def rectangle_hint(
    name: str, rectangle: tuple[int, ...], reason: str, removals: list[tuple[int, int]]
) -> Hint:
    """Make the uniqueness assumption explicit in every rectangle explanation."""
    return removal_hint(
        name,
        "Look for a two-digit rectangle spanning exactly two boxes.",
        "The original clues have been verified to have exactly one solution. "
        "If this rectangle could use only the same two alternating digits, swapping "
        "those digits at all four corners would create another solution.\n\n" + reason,
        rectangle,
        removals,
    )


def unique_rectangle_hints(options: list[set[int]], givens: tuple[int, ...]) -> Iterator[Hint]:
    """Find unique rectangle types 1–4; callers must first verify uniqueness."""
    for rectangle in rectangles():
        if any(givens[cell] or not options[cell] for cell in rectangle):
            continue
        common: set[int] = set.intersection(*(options[cell] for cell in rectangle))
        for digits in combinations(sorted(common), 2):
            pair: set[int] = set(digits)
            roofs: tuple[int, ...] = tuple(cell for cell in rectangle if options[cell] != pair)
            if len(roofs) == 1:
                yield rectangle_hint(
                    "Unique Rectangle Type 1",
                    rectangle,
                    f"The other three corners contain only {digits}. "
                    f"Therefore {cell_name(roofs[0])} "
                    "must use a digit outside that pair.",
                    [(roofs[0], digit) for digit in digits],
                )
            if len(roofs) != 2:
                continue
            a, b = roofs
            extras: set[int] = (options[a] | options[b]) - pair
            if len(extras) == 1:
                digit: int = next(iter(extras))
                removals: list[tuple[int, int]] = [
                    (cell, digit)
                    for cell in sorted(PEERS[a] & PEERS[b])
                    if cell not in rectangle and digit in options[cell]
                ]
                if removals:
                    yield rectangle_hint(
                        "Unique Rectangle Type 2",
                        rectangle,
                        f"At least one of {cell_name(a)} and {cell_name(b)} must be {digit}. "
                        "A cell that sees both cannot contain it.",
                        removals,
                    )
            for unit in UNITS:
                if a not in unit or b not in unit:
                    continue
                for digit in digits:
                    if {cell for cell in unit if digit in options[cell]} == {a, b}:
                        other: int = next(iter(pair - {digit}))
                        yield rectangle_hint(
                            "Unique Rectangle Type 4",
                            rectangle,
                            f"Only the two roof cells can contain {digit} in their shared unit. "
                            f"If either roof contained {other}, the other would be {digit}, "
                            "leaving the forbidden two-digit rectangle.",
                            [(a, other), (b, other)],
                        )
                # The roof extras act as one virtual member of a naked subset.
                eligible: list[int] = [
                    cell for cell in unit if cell not in rectangle and options[cell]
                ]
                for count in range(1, 4):
                    for selected in combinations(eligible, count):
                        union: set[int] = extras.union(*(options[cell] for cell in selected))
                        if union & pair or len(union) != count + 1:
                            continue
                        removals = [
                            (cell, digit)
                            for cell in unit
                            if cell not in rectangle and cell not in selected
                            for digit in sorted(options[cell] & union)
                        ]
                        if removals:
                            hint: Hint = rectangle_hint(
                                "Unique Rectangle Type 3",
                                rectangle,
                                "At least one roof must use an extra digit. Those extras, together "
                                "with "
                                + "; ".join(map(cell_name, selected))
                                + f", occupy the {len(union)} digits {sorted(union)} "
                                "in their shared unit. "
                                "Those digits cannot occur elsewhere in that unit.",
                                removals,
                            )
                            yield Hint(
                                hint.technique,
                                hint.nudge,
                                hint.explanation,
                                rectangle + selected,
                                eliminations=hint.eliminations,
                            )


def avoidable_rectangle_hints(game: Game, options: list[set[int]]) -> Iterator[Hint]:
    """Prevent completing a swappable rectangle of three non-given answers (type 1)."""
    for rectangle in rectangles():
        if any(game.puzzle.givens[cell] for cell in rectangle):
            continue
        empty: list[int] = [
            position for position, cell in enumerate(rectangle) if not game.values[cell]
        ]
        if len(empty) != 1:
            continue
        position: int = empty[0]
        opposite: int = game.values[rectangle[3 - position]]
        adjacent: list[int] = [game.values[rectangle[position ^ offset]] for offset in (1, 2)]
        cell: int = rectangle[position]
        if adjacent[0] == adjacent[1] and opposite != adjacent[0] and opposite in options[cell]:
            yield rectangle_hint(
                "Avoidable Rectangle",
                rectangle,
                "None of these corners is an original clue. Placing "
                f"{opposite} at {cell_name(cell)} would complete the swappable rectangle.",
                [(cell, opposite)],
            )


def bug_plus_one_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find the extra digit whose removal would leave a pure BUG candidate grid."""
    unsolved: list[int] = [cell for cell, digits in enumerate(options) if digits]
    triples: list[int] = [cell for cell in unsolved if len(options[cell]) == 3]
    if len(triples) != 1 or any(
        len(options[cell]) != 2 for cell in unsolved if cell not in triples
    ):
        return
    cell: int = triples[0]
    for digit in sorted(options[cell]):
        if all(
            sum(value in options[index] for index in unit) - int(cell in unit and value == digit)
            in (0, 2)
            for unit in UNITS
            for value in DIGITS
        ):
            yield Hint(
                "BUG+1",
                "Inspect the only cell with three candidates.",
                "The original clues have exactly one solution. Every other unsolved cell has two "
                f"candidates. Removing {digit} at {cell_name(cell)} would leave every digit "
                "with either zero or two positions in each unit: a BUG pattern, which cannot "
                "have exactly one solution. The extra candidate must therefore be true.",
                tuple(unsolved),
                placements=((cell, digit),),
            )


def uniqueness_hints(game: Game, options: list[set[int]]) -> Iterator[Hint]:
    """Gate all uniqueness assumptions on an independently verified unique puzzle."""
    if not uniquely_solvable(game.puzzle.givens):
        return
    yield from unique_rectangle_hints(options, game.puzzle.givens)
    yield from avoidable_rectangle_hints(game, options)
    yield from bug_plus_one_hints(options)
