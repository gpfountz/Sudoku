# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Positive, near-miss, and solution-preservation checks for common advanced patterns."""

import random
from collections.abc import Iterator
from itertools import chain
from typing import Any

import pytest

from sudoku.engine import COLUMNS, DIGITS, ROWS
from sudoku.hints import (
    Hint,
    HintStep,
    coloring_hints,
    jellyfish_hints,
    subsets_hints,
    w_wing_hints,
    xyz_wing_hints,
)
from sudoku.model import Game, Preferences, Puzzle


def options_grid() -> list[set[int]]:
    """Leave unrelated candidates unconstrained for isolated geometry checks."""
    return [set(DIGITS) for _ in range(81)]


def removals(hints: Iterator[Hint]) -> set[tuple[int, int]]:
    """Collect exact proposed candidate removals without applying them."""
    return {removal for hint in hints for removal in hint.eliminations}


def orient(options: list[set[int]], transpose: bool) -> list[set[int]]:
    """Transpose a candidate grid to exercise both row and column orientations."""
    return [set(options[i % 9 * 9 + i // 9] if transpose else options[i]) for i in range(81)]


def position(index: int, transpose: bool) -> int:
    """Translate an expected cell into the chosen orientation."""
    return index % 9 * 9 + index // 9 if transpose else index


@pytest.mark.parametrize("transpose", [False, True])
def test_xyz_wing_requires_visibility_of_all_three_cells(transpose: bool) -> None:
    """Two wings alone cannot eliminate the pivot's shared candidate."""
    options: list[set[int]] = options_grid()
    options[76], options[40], options[75] = {1, 5, 9}, {1, 5}, {5, 9}
    options[67] = options[39] = {5, 7}
    found: set[tuple[int, int]] = removals(xyz_wing_hints(orient(options, transpose)))
    assert (position(67, transpose), 5) in found
    assert (position(39, transpose), 5) not in found
    options[40].add(8)
    assert not removals(xyz_wing_hints(orient(options, transpose)))


@pytest.mark.parametrize("transpose", [False, True])
def test_w_wing_requires_a_strong_link(transpose: bool) -> None:
    """Identical pairs force their other digit only through a genuine two-position link."""
    options: list[set[int]] = options_grid()
    options[30] = {5, 9}
    options[71] = {5, 9}
    for index in COLUMNS[7]:
        if index not in (34, 70):
            options[index].discard(9)
    assert (position(35, transpose), 5) in removals(w_wing_hints(orient(options, transpose)))
    options[7].add(9)
    assert (position(35, transpose), 5) not in removals(w_wing_hints(orient(options, transpose)))


@pytest.mark.parametrize("transpose", [False, True])
def test_jellyfish_and_extra_cover_near_miss(transpose: bool) -> None:
    """Four base lines must fit exactly four cover lines, never five."""
    options: list[set[int]] = options_grid()
    for row, columns in ((0, {0, 2}), (2, {2, 4}), (4, {4, 6}), (6, {0, 6})):
        for column in range(9):
            if column not in columns:
                options[row * 9 + column].discard(7)
    found: set[tuple[int, int]] = removals(jellyfish_hints(orient(options, transpose)))
    assert (position(9, transpose), 7) in found
    assert (position(10, transpose), 7) not in found
    options[8].add(7)
    assert not removals(jellyfish_hints(orient(options, transpose)))


@pytest.mark.parametrize("hidden", [False, True])
@pytest.mark.parametrize("transpose", [False, True])
def test_quads_and_near_misses(hidden: bool, transpose: bool) -> None:
    """Quad occupancy supports both variants without accepting a fifth candidate or cell."""
    options: list[set[int]] = options_grid()
    options[:4] = [{1, 2}, {2, 3}, {3, 4}, {1, 4}]
    if hidden:
        for index in range(4):
            options[index].add(index + 5)
        for index in range(4, 9):
            options[index] -= {1, 2, 3, 4}
    expected: tuple[int, int] = (
        (position(0, transpose), 5) if hidden else (position(4, transpose), 1)
    )
    hints: list[Hint] = list(subsets_hints(orient(options, transpose), 4, hidden))
    assert any(hint.technique == ("Hidden Quad" if hidden else "Naked Quad") for hint in hints)
    assert expected in removals(iter(hints))
    if hidden:
        options[4].add(1)
    else:
        options[3].add(5)
    assert expected not in removals(subsets_hints(orient(options, transpose), 4, hidden))


def test_color_trap_requires_both_groups_in_one_component() -> None:
    """A target must see opposite alternatives in a single linked component."""
    options: list[set[int]] = options_grid()
    for unit, keep in ((ROWS[0], {0, 4}), (COLUMNS[4], {4, 40}), (ROWS[4], {37, 40})):
        for index in unit:
            if index not in keep:
                options[index].discard(1)
    hints: list[Hint] = [hint for hint in coloring_hints(options) if hint.technique == "Color Trap"]
    assert (19, 1) in removals(iter(hints))
    assert (80, 1) not in removals(iter(hints))
    assert all("Group A:" in hint.explanation and "Group B:" in hint.explanation for hint in hints)
    options[22].add(1)
    assert (19, 1) not in removals(coloring_hints(options))


def test_color_wrap_uses_same_group_conflict() -> None:
    """Two same-group candidates seeing each other invalidate that whole group."""
    options: list[set[int]] = options_grid()
    for unit, keep in ((COLUMNS[0], {0, 9}), (ROWS[1], {9, 10})):
        for index in unit:
            if index not in keep:
                options[index].discard(8)
    hints: list[Hint] = [hint for hint in coloring_hints(options) if hint.technique == "Color Wrap"]
    assert {(0, 8), (10, 8)} <= removals(iter(hints))
    assert (9, 8) not in removals(iter(hints))
    options[11].add(8)
    assert not any(hint.technique == "Color Wrap" for hint in coloring_hints(options))


def common_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Exercise every added detector independently of the normal simplest-first ordering."""
    return chain(
        subsets_hints(options, 4, False),
        subsets_hints(options, 4, True),
        xyz_wing_hints(options),
        w_wing_hints(options),
        jellyfish_hints(options),
        coloring_hints(options),
    )


def test_common_patterns_preserve_a_solution_without_requiring_uniqueness() -> None:
    """Every proof must hold on solution-compatible candidates even without a unique puzzle."""
    rng: random.Random = random.Random(83147)
    solution: tuple[int, ...] = tuple(
        (row * 3 + row // 3 + column) % 9 + 1 for row in range(9) for column in range(9)
    )
    for _ in range(40):
        options: list[set[int]] = [
            {answer} | {digit for digit in DIGITS if rng.random() < 0.23} for answer in solution
        ]
        before: list[set[int]] = [set(available) for available in options]
        for hint in common_hints(options):
            assert all(solution[index] != digit for index, digit in hint.eliminations), hint
            assert all(digit in options[index] for index, digit in hint.eliminations), hint
        assert options == before


def current_xyz_game() -> Game:
    """Restore the reported XYZ-Wing position from a fixed, isolated regression fixture."""
    import json
    from pathlib import Path

    from sudoku.storage import parse_snapshot

    data: dict[str, Any] = json.loads(
        (Path(__file__).parent / "fixtures/xyz_wing_after_manual_eliminations.json").read_text()
    )
    record: dict[str, Any] = data["puzzle"]
    puzzle: Puzzle = Puzzle(
        record["id"],
        tuple(record["givens"]),
        tuple(record["solution"]),
        record["rating"],
        record["level"],
    )
    game: Game = Game(puzzle)
    game.restore(parse_snapshot(data["board"], puzzle))
    return game


def test_reported_xyz_wing_stages_apply_and_undo() -> None:
    """Find the real missing hint, apply through the controller, and restore it with Undo."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    from sudoku.app import AppController
    from sudoku.hints import hint_steps, iter_hints

    game: Game = current_xyz_game()
    before: object = game.snapshot()
    hint: Hint = next(
        hint
        for hint in iter_hints(game)
        if hint.technique == "XYZ-Wing" and (67, 5) in hint.eliminations
    )
    assert set(hint.focus) == {76, 40, 75}
    assert not game.wrong_answers()
    assert all(game.puzzle.solution[index] != digit for index, digit in hint.eliminations)
    stages: tuple[HintStep, ...] = hint_steps(game, hint)
    assert len(stages) == 3
    assert not stages[0].eliminations and not stages[1].eliminations
    assert stages[2].eliminations == hint.eliminations
    assert game.snapshot() == before
    state: SimpleNamespace = SimpleNamespace(
        current_hint=hint,
        hint_stage=2,
        game=game,
        preferences=Preferences(),
        changed=Mock(),
        window=Mock(),
        board=Mock(),
    )
    controller: Any = AppController.alloc().init()
    for name, value in vars(state).items():
        setattr(controller, name, value)
    controller.applyHint_(None)
    assert game.snapshot() == before
    controller.hint_stage = 3
    controller.applyHint_(None)
    assert 5 not in game.notes[67] and game.logical_candidates()[67] == {7}
    assert len(game.undo_stack) == 1
    assert any((67, 7) in hint.placements for hint in iter_hints(game))
    game.undo()
    assert game.snapshot() == before


def test_already_removed_xyz_candidate_is_carried_forward() -> None:
    """Suppress the redundant wing hint while still discovering its resulting single."""
    from sudoku.hints import iter_hints

    game: Game = current_xyz_game()
    game.notes[67].discard(5)
    before: object = game.snapshot()
    hints: list[Hint] = list(iter_hints(game))
    assert not any((67, 5) in hint.eliminations for hint in hints)
    assert any(
        (67, 7) in hint.placements and (67, 5) in hint.verified_eliminations for hint in hints
    )
    assert all(digit in game.notes[index] for hint in hints for index, digit in hint.eliminations)
    assert game.snapshot() == before and not game.undo_stack
