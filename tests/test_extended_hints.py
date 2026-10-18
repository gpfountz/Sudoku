# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Positive, broken-pattern, ordering, and soundness checks for extended hint families."""

import random
from collections.abc import Iterator
from itertools import chain

import pytest

from sudoku.engine import DIGITS
from sudoku.hint_chains import inference_chain_hints
from sudoku.hint_fish import complex_fish_hints, finned_complex_fish_hints, finned_fish_hints
from sudoku.hint_types import Hint
from sudoku.hint_uniqueness import (
    avoidable_rectangle_hints,
    bug_plus_one_hints,
    unique_rectangle_hints,
    uniqueness_hints,
)
from sudoku.hints import iter_hints, xy_chain_hints
from sudoku.model import Game, Puzzle


def grid() -> list[set[int]]:
    """Return unconstrained candidates for isolated pattern geometry."""
    return [set(DIGITS) for _ in range(81)]


def eliminated(hints: Iterator[Hint]) -> set[tuple[int, int]]:
    """Collect candidate removals from a search."""
    return {item for hint in hints for item in hint.eliminations}


@pytest.mark.parametrize("transpose", (False, True))
@pytest.mark.parametrize("sashimi", (False, True))
@pytest.mark.parametrize("size", (2, 3, 4))
def test_finned_and_sashimi_fish(transpose: bool, sashimi: bool, size: int) -> None:
    """A target must see every fin; test both orientations and a broken pattern."""
    options: list[set[int]] = grid()
    covers: set[int] = set((0, 3, 6, 8)[:size])
    patterns: list[tuple[int, set[int]]] = [(0, {0, 1} if sashimi else covers | {1})] + [
        (row, covers) for row in (3, 6, 8)[: size - 1]
    ]
    for row, columns in patterns:
        for column in range(9):
            if column not in columns:
                options[row * 9 + column].discard(1)
    if transpose:
        options = [options[cell % 9 * 9 + cell // 9] for cell in range(81)]
    target: int = 1 if transpose else 9
    fish: str = {2: "X-Wing", 3: "Swordfish", 4: "Jellyfish"}[size]
    name: str = f"Sashimi {fish}" if sashimi else f"Finned {fish}"
    assert any(
        h.technique == name and (target, 1) in h.eliminations
        for h in finned_fish_hints(options, size)
    )
    options[7 * 9 + 3 if transpose else 3 * 9 + 7].add(1)
    assert (target, 1) not in eliminated(finned_fish_hints(options, size))


def test_franken_fish() -> None:
    """Column and box bases covered by three rows form a Franken Swordfish."""
    options: list[set[int]] = grid()
    for row in range(9):
        if row not in (3, 5):
            options[row * 9 + 2].discard(1)
        if row not in (5, 8):
            options[row * 9 + 8].discard(1)
    for row in (6, 7, 8):
        for column in (3, 4, 5):
            if (row, column) not in ((8, 3), (8, 4)):
                options[row * 9 + column].discard(1)
    assert any(
        h.technique == "Franken Swordfish" and (27, 1) in h.eliminations
        for h in complex_fish_hints(options, 3)
    )


def test_mutant_fish() -> None:
    """Mixed row/column bases require the more general Mutant classification."""
    options: list[set[int]] = grid()
    for column in range(9):
        if column not in (3, 4):
            options[column].discard(1)
    for row in range(9):
        if row not in (3, 4):
            options[row * 9].discard(1)
    assert any(
        h.technique == "Mutant X-Wing" and (12, 1) in h.eliminations
        for h in complex_fish_hints(options, 2)
    )


def test_grouped_aic_and_broken_strong_link() -> None:
    """An OR group supplies a link unavailable to single-candidate inference chains."""
    options: list[set[int]] = grid()
    for row, columns in ((0, {0, 1, 3}), (3, {0, 3})):
        for column in range(9):
            if column not in columns:
                options[row * 9 + column].discard(1)
    assert (9, 1) not in eliminated(inference_chain_hints(options))
    hints: list[Hint] = list(inference_chain_hints(options, grouped=True))
    assert any(
        (9, 1) in hint.eliminations
        and any(len(node.cells) > 1 for link in hint.links for node in (link.start, link.end))
        for hint in hints
    )
    options[31].add(1)
    assert (9, 1) not in eliminated(inference_chain_hints(options, grouped=True))


def test_aic_uses_multi_digit_links() -> None:
    """Bivalue cell links and unit links form a multi-digit contradiction proof."""
    options: list[set[int]] = grid()
    options[0], options[3], options[27] = {1, 2}, {2, 3}, {1, 3}
    hints: list[Hint] = list(inference_chain_hints(options))
    assert any((30, 3) in hint.eliminations for hint in hints)
    assert all(
        any(link.strong for link in hint.links) and any(not link.strong for link in hint.links)
        for hint in hints
    )


def test_xy_chain_longer_than_eight_cells() -> None:
    """A nine-cell chain is found only when the old eight-cell cap is lifted."""
    options: list[set[int]] = grid()
    path: tuple[int, ...] = (0, 3, 30, 28, 55, 60, 78, 73, 10)
    for number, cell in enumerate(path, 1):
        options[cell] = {number, number % 9 + 1}
    assert (1, 1) not in eliminated(xy_chain_hints(options, max_cells=8))
    assert any(
        (1, 1) in hint.eliminations and len(hint.focus) == 9 for hint in xy_chain_hints(options)
    )


@pytest.mark.parametrize("kind", (1, 2, 3, 4))
def test_unique_rectangles(kind: int) -> None:
    """Exercise each supported unique rectangle proof and reject given corners."""
    options: list[set[int]] = grid()
    for cell in (0, 3, 9, 12):
        options[cell] = {1, 2}
    if kind == 1:
        options[12].add(3)
        expected: tuple[int, int] = (12, 1)
    else:
        options[9].add(3)
        options[12].add(3)
        expected = (10, 3)
        if kind == 3:
            options[9].add(4)
            options[12].add(4)
            options[10] = {3, 4}
            expected = (13, 3)
        elif kind == 4:
            for cell in range(9, 18):
                if cell not in (9, 12):
                    options[cell].discard(1)
            expected = (9, 2)
    givens: tuple[int, ...] = (0,) * 81
    assert any(
        h.technique == f"Unique Rectangle Type {kind}" and expected in h.eliminations
        for h in unique_rectangle_hints(options, givens)
    )
    protected: tuple[int, ...] = (1,) + (0,) * 80
    assert not any(
        set((0, 3, 9, 12)) <= set(h.focus) for h in unique_rectangle_hints(options, protected)
    )


def test_uniqueness_disabled_for_multiple_solutions() -> None:
    """A claimed saved solution must not authorize uniqueness deductions."""
    game: Game = Game(Puzzle("nonunique", (0,) * 81, (1,) * 81, 0, "Easy"))
    options: list[set[int]] = grid()
    for cell in (0, 3, 9):
        options[cell] = {1, 2}
    options[12] = {1, 2, 3}
    assert list(unique_rectangle_hints(options, game.puzzle.givens))
    assert not list(uniqueness_hints(game, options))


def test_bug_plus_one_and_near_miss() -> None:
    """The BUG exception must restore exactly zero or two occurrences in every unit."""
    solution: tuple[int, ...] = tuple(
        (r * 3 + r // 3 + c) % 9 + 1 for r in range(9) for c in range(9)
    )
    options: list[set[int]] = [{digit, digit % 9 + 1} for digit in solution]
    options[0].add(3)
    assert [hint.placements for hint in bug_plus_one_hints(options)] == [((0, 3),)]
    options[10].add(8)
    assert not list(bug_plus_one_hints(options))


def test_avoidable_rectangle_protects_givens() -> None:
    """Only a rectangle made entirely of player answers can be swapped."""
    game: Game = Game(Puzzle("rectangle", (0,) * 81, (1,) * 81, 0, "Easy"))
    game.values[0], game.values[3], game.values[9] = 1, 2, 2
    options: list[set[int]] = grid()
    options[0] = options[3] = options[9] = set()
    assert (12, 1) in eliminated(avoidable_rectangle_hints(game, options))
    game.puzzle = Puzzle("given", (1,) + (0,) * 80, (1,) * 81, 0, "Easy")
    assert (12, 1) not in eliminated(avoidable_rectangle_hints(game, options))


def test_extended_patterns_preserve_known_solutions() -> None:
    """Non-uniqueness proofs must preserve a solution on arbitrary compatible candidates."""
    rng: random.Random = random.Random(22981)
    solution: tuple[int, ...] = tuple(
        (r * 3 + r // 3 + c) % 9 + 1 for r in range(9) for c in range(9)
    )
    for _ in range(5):
        options: list[set[int]] = [
            {answer} | {digit for digit in DIGITS if rng.random() < 0.2} for answer in solution
        ]
        searches: Iterator[Hint] = chain(
            *(finned_fish_hints(options, size) for size in (2, 3, 4)),
            *(complex_fish_hints(options, size) for size in (2, 3, 4)),
            *(finned_complex_fish_hints(options, size) for size in (2, 3, 4)),
            inference_chain_hints(options),
            inference_chain_hints(options, grouped=True),
            xy_chain_hints(options),
        )
        for hint in searches:
            assert all(solution[cell] != digit for cell, digit in hint.eliminations), hint
            assert all(solution[cell] == digit for cell, digit in hint.placements), hint


def test_singles_precede_extended_techniques(game: Game) -> None:
    """The first available simple placement must not invoke advanced pattern searches."""
    from unittest.mock import patch

    game.values = list(game.puzzle.solution)
    game.values[0] = 0
    with patch("sudoku.hints.inference_chain_hints", side_effect=AssertionError("advanced search")):
        assert next(iter_hints(game)).technique == "Naked Single"


def test_aic_can_place_an_answer() -> None:
    """A false-to-true loop forces an answer rather than only eliminating a note."""
    options: list[set[int]] = grid()
    options[0], options[3], options[30], options[27] = {1, 2}, {2, 3}, {1, 3}, {1, 2}
    assert any((0, 1) in hint.placements for hint in inference_chain_hints(options))


def test_finned_mutant_fish() -> None:
    """An uncovered fin limits a mixed-base fish to targets that can see that fin."""
    from sudoku.hint_fish import finned_complex_fish_hints

    options: list[set[int]] = grid()
    for column in range(9):
        if column not in (1, 3, 4):
            options[column].discard(1)
    for row in range(9):
        if row not in (3, 4):
            options[row * 9].discard(1)
    assert any(
        hint.technique == "Finned Mutant X-Wing" and (28, 1) in hint.eliminations
        for hint in finned_complex_fish_hints(options, 2)
    )


def test_completed_removal_unlocks_single_before_advanced_search() -> None:
    """A completed deduction must expose a simpler placement before the next tier runs."""
    from unittest.mock import patch

    game: Game = Game(Puzzle("ordering", (0,) * 81, (1,) * 81, 0, "Easy"))
    game.notes[0] = {1}
    options: list[set[int]] = [set() for _ in range(81)]
    options[0] = {1, 2}

    def simple(current: list[set[int]]) -> Iterator[Hint]:
        """Model a naked single exposed by an independently proven removal."""
        if current[0] == {1}:
            yield Hint("Naked Single", "Look", "Only 1 remains", (0,), placements=((0, 1),))

    def completed(current: list[set[int]]) -> Iterator[Hint]:
        """Model a supported removal the player has already made."""
        if 2 in current[0]:
            yield Hint("Locked Candidates", "Look", "Proved absent", (0,), eliminations=((0, 2),))

    def advanced(current: list[set[int]]) -> Iterator[Hint]:
        """Fail if the search escalates before offering the exposed single."""
        raise AssertionError("Advanced search ran before a simple hint")
        yield from ()

    with (
        patch.object(Game, "logical_candidates", return_value=options),
        patch("sudoku.hints.hint_searches", return_value=(simple, completed, advanced)),
    ):
        hint: Hint = next(iter_hints(game))
    assert hint.technique == "Naked Single"
    assert hint.verified_eliminations == ((0, 2),)
    assert hint.prerequisites
