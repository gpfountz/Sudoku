# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Validate advanced patterns and the user's previously unsupported puzzle position."""

import pytest

from sudoku.engine import DIGITS, solve
from sudoku.hints import Hint, iter_hints, swordfish_hints, turbot_chain_hints, xy_chain_hints
from sudoku.model import Game, Puzzle

SCREENSHOT_ROWS: tuple[str, ...] = (
    "008000504",
    "750240000",
    "940815067",
    "520963008",
    "800521006",
    "100784052",
    "380050040",
    "000092005",
    "095008600",
)
SCREENSHOT_NOTES: tuple[str, ...] = (
    "26 16 - 36 37 679 - 129 -",
    "- - 136 - - 69 1389 1389 139",
    "- - 23 - - - 23 - -",
    "- - 47 - - - 147 17 -",
    "- 37 479 - - - 349 379 -",
    "- 36 69 - - - 39 - -",
    "- - 1267 16 - 67 1279 - 19",
    "46 167 167 1346 - - 1378 1378 -",
    "24 - - 134 37 - - 1237 13",
)


def screenshot_game() -> Game:
    """Reconstruct the reported board and manual notes without deriving hints from notes."""
    values: tuple[int, ...] = tuple(int(digit) for row in SCREENSHOT_ROWS for digit in row)
    solutions: list[tuple[int, ...]] = solve(values)
    assert len(solutions) == 1
    game: Game = Game(Puzzle("advanced-hint-regression", values, solutions[0], 3.0, "Hard"))
    game.notes = [
        {int(digit) for digit in cell} if cell != "-" else set()
        for row in SCREENSHOT_NOTES
        for cell in row.split()
    ]
    return game


@pytest.mark.parametrize("transpose", (False, True))
def test_swordfish_in_both_orientations(transpose: bool) -> None:
    """Three rows or columns confine a digit and remove it only outside those lines."""
    options: list[set[int]] = [set(DIGITS) for _ in range(81)]
    for row, columns in ((0, {1, 4}), (3, {4, 7}), (6, {1, 7})):
        for column in range(9):
            if column not in columns:
                index: int = column * 9 + row if transpose else row * 9 + column
                options[index].discard(1)
    hints: list[Hint] = list(swordfish_hints(options))
    assert hints
    assert len(hints[0].eliminations) == 18
    assert all(digit == 1 for _, digit in hints[0].eliminations)
    assert not any(index in hints[0].focus for index, _ in hints[0].eliminations)
    options = [set(DIGITS) for _ in range(81)]
    assert not list(swordfish_hints(options))


def test_skyscraper_and_two_string_kite() -> None:
    """Two linked forced pairs produce the expected common-peer elimination."""
    options: list[set[int]] = [set(DIGITS) for _ in range(81)]
    for row, columns in ((0, {0, 3}), (4, {0, 5})):
        for column in range(9):
            if column not in columns:
                options[row * 9 + column].discard(1)
    assert any(
        hint.technique == "Skyscraper" and (14, 1) in hint.eliminations
        for hint in turbot_chain_hints(options)
    )
    options = [set(DIGITS) for _ in range(81)]
    for column in range(9):
        if column not in (0, 4):
            options[column].discard(1)
    for row in range(9):
        if row not in (1, 5):
            options[row * 9 + 1].discard(1)
    assert any(
        hint.technique == "Two-String Kite" and (49, 1) in hint.eliminations
        for hint in turbot_chain_hints(options)
    )
    assert not list(turbot_chain_hints([set(DIGITS) for _ in range(81)]))


def test_reported_position_has_useful_explained_chain() -> None:
    """The reported puzzle yields a sound new removal, with reversible application."""
    game: Game = screenshot_game()
    before: object = game.snapshot()
    hints: list[Hint] = list(iter_hints(game))
    assert hints
    chain_hint: Hint = next(
        hint for hint in xy_chain_hints(game.logical_candidates()) if (17, 9) in hint.eliminations
    )
    assert len(chain_hint.focus) >= 4
    assert "Then" in chain_hint.explanation
    for hint in hints:
        assert all(digit in game.notes[index] for index, digit in hint.eliminations)
        assert all(digit != game.puzzle.solution[index] for index, digit in hint.eliminations)
        assert all(digit == game.puzzle.solution[index] for index, digit in hint.placements)
    assert game.snapshot() == before
    assert game.eliminate(chain_hint.eliminations)
    assert 9 not in game.notes[17]
    assert game.undo()
    assert game.snapshot() == before


def test_chain_does_not_reoffer_completed_removal() -> None:
    """Advanced hints retain the rule that absent pencil marks are never removal targets."""
    game: Game = screenshot_game()
    game.notes[17].discard(9)
    assert all((17, 9) not in hint.eliminations for hint in iter_hints(game))


def test_reported_position_can_be_completed_with_hints() -> None:
    """Advanced deductions unlock the reported board all the way to a correct solution."""
    from sudoku.hints import next_hint

    game: Game = screenshot_game()
    for _ in range(100):
        if game.complete:
            break
        hint: Hint | None = next_hint(game)
        assert hint is not None
        for index, digit in hint.placements:
            assert digit == game.puzzle.solution[index]
            game.set_value(index, digit)
        if hint.eliminations:
            assert all(digit != game.puzzle.solution[index] for index, digit in hint.eliminations)
            game.eliminate(hint.eliminations)
    assert game.complete
