# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify logical patterns and solution-preserving deduction sequences."""

import pytest

from sudoku.catalog import load_catalog
from sudoku.engine import DIGITS
from sudoku.hints import Hint, locked_candidates, next_hint, singles, subsets, x_wing, xy_wing
from sudoku.model import LEVELS, Game, Puzzle


def options_grid() -> list[set[int]]:
    """Start a synthetic pencil-mark grid for isolated pattern fixtures."""
    return [set(DIGITS) for _ in range(81)]


def test_naked_and_hidden_singles() -> None:
    """Singles identify exact placements with distinct explanations."""
    options: list[set[int]] = options_grid()
    options[0] = {7}
    hint: Hint | None = singles(options)
    assert hint and hint.placements == ((0, 7),)
    options = options_grid()
    for index in range(9):
        if index != 4:
            options[index].discard(1)
    hint = singles(options)
    assert hint and hint.technique == "Hidden Single" and hint.placements == ((4, 1),)


def test_locked_candidates() -> None:
    """Pointing candidates exclude a digit outside the originating box."""
    options: list[set[int]] = options_grid()
    for index in (9, 10, 11, 18, 19, 20):
        options[index].discard(1)
    hint: Hint | None = locked_candidates(options)
    assert hint and (3, 1) in hint.eliminations
    assert all(index not in (0, 1, 2) for index, _ in hint.eliminations)


@pytest.mark.parametrize("size", [2, 3])
@pytest.mark.parametrize("hidden", [False, True])
def test_pair_and_triple_eliminations(size: int, hidden: bool) -> None:
    """Pairs and triples remove only candidates outside their occupancy set."""
    options: list[set[int]] = options_grid()
    digits: set[int] = set(range(1, size + 1))
    if hidden:
        for index in range(size, 9):
            options[index] -= digits
    else:
        for index in range(size):
            options[index] = digits.copy()
    hint: Hint | None = subsets(options, size, hidden)
    assert hint and hint.eliminations
    assert all(
        (index < size and digit not in digits) if hidden else (index >= size and digit in digits)
        for index, digit in hint.eliminations
    )


@pytest.mark.parametrize("transpose", [False, True])
def test_x_wing_in_both_orientations(transpose: bool) -> None:
    """Matching pairs of lines eliminate from the two crossing lines."""
    options: list[set[int]] = options_grid()
    for row in (0, 3):
        for column in range(9):
            if column not in (2, 7):
                index: int = column * 9 + row if transpose else row * 9 + column
                options[index].discard(1)
    hint: Hint | None = x_wing(options)
    assert hint and len(hint.eliminations) == 14
    assert all(digit == 1 for _, digit in hint.eliminations)


def test_xy_wing() -> None:
    """Both possible pivot values force one wing's shared digit."""
    options: list[set[int]] = options_grid()
    options[0], options[1], options[9] = {1, 2}, {1, 3}, {2, 3}
    hint: Hint | None = xy_wing(options)
    assert hint and (10, 3) in hint.eliminations
    assert not any(index in (0, 1, 9) for index, _ in hint.eliminations)


def test_manual_notes_are_never_used_as_proof(game: Game) -> None:
    """A false single in the player's notes cannot manufacture a deduction."""
    game.mark(1, 9)
    hint: Hint | None = next_hint(game)
    assert hint and hint.technique == "Candidate Review"
    assert hint.placements == ((1, game.puzzle.solution[1]),)


def test_wrong_answers_and_pause_stop_logical_hints(game: Game) -> None:
    """Offer no deduction from an incorrect or hidden board."""
    game.set_value(1, 3)
    assert next_hint(game) is None
    game.values = list(game.puzzle.solution)
    game.values[1] = 0
    game.paused = True
    assert next_hint(game) is None


@pytest.mark.parametrize("level", LEVELS)
def test_catalog_hint_paths_preserve_solutions(level: str) -> None:
    """Exercise real puzzles until solved or explicit technique coverage exhaustion."""
    puzzles: list[Puzzle] = load_catalog()[level][:12]
    for puzzle in puzzles:
        game: Game = Game(puzzle)
        game.fill_candidates()
        for _ in range(400):
            hint: Hint | None = next_hint(game)
            if hint is None:
                break
            before: object = game.snapshot()
            for index, digit in hint.placements:
                assert digit == puzzle.solution[index], (puzzle.identifier, hint)
                game.set_value(index, digit)
            for index, digit in hint.eliminations:
                assert digit != puzzle.solution[index], (puzzle.identifier, hint)
            if hint.eliminations:
                game.eliminate(hint.eliminations)
            assert game.snapshot() != before
        else:
            pytest.fail("Hint sequence did not terminate")
        if level in ("Easy", "Medium"):
            assert game.complete


def test_hint_eliminations_have_undo_history(game: Game) -> None:
    """Applying a deduction updates verified exclusions and restores them on undo."""
    before: object = game.snapshot()
    game.eliminate(((1, 8),))
    assert 8 not in game.logical_candidates()[1]
    assert game.notes[1]
    game.undo()
    assert game.snapshot() == before
    with pytest.raises(ValueError):
        game.eliminate(((1, game.puzzle.solution[1]),))


def test_alternative_hints_are_distinct_and_sound() -> None:
    """Check every offered alternative against real puzzle solutions without changing notes."""
    from sudoku.hints import hint_steps, iter_hints

    for level in LEVELS:
        game: Game = Game(load_catalog()[level][0])
        game.fill_candidates()
        before: object = game.snapshot()
        hints: list[Hint] = list(iter_hints(game))
        actions = [(hint.placements, hint.eliminations) for hint in hints]
        assert len(actions) == len(set(actions))
        for hint in hints:
            assert all(game.puzzle.solution[index] == digit for index, digit in hint.placements)
            assert all(game.puzzle.solution[index] != digit for index, digit in hint.eliminations)
            stages = hint_steps(game, hint)
            assert not stages[0].placements and not stages[0].eliminations
            assert not stages[1].placements and not stages[1].eliminations
            assert stages[2].placements == hint.placements
            assert stages[2].eliminations == hint.eliminations
        assert game.snapshot() == before


def test_alternatives_include_multiple_cells(game: Game) -> None:
    """Offer a different forced cell instead of repeating another explanation of the same move."""
    from sudoku.hints import iter_hints

    game.values = list(game.puzzle.solution)
    game.values[1] = game.values[2] = 0
    hints: list[Hint] = list(iter_hints(game))
    assert {hint.placements for hint in hints} == {
        ((1, game.puzzle.solution[1]),),
        ((2, game.puzzle.solution[2]),),
    }


def test_elimination_hints_only_remove_existing_notes() -> None:
    """Hide completed eliminations and trim mixed hints to notes still on the board."""
    from sudoku.hints import iter_hints

    game: Game = Game(load_catalog()["Hard"][0])
    game.fill_candidates()
    original: Hint = next(hint for hint in iter_hints(game) if len(hint.eliminations) > 1)
    retained: tuple[int, int] = original.eliminations[0]
    game.notes = [set() for _ in range(81)]
    game.notes[retained[0]].update((retained[1], game.puzzle.solution[retained[0]]))
    before: object = game.snapshot()
    filtered: list[Hint] = [hint for hint in iter_hints(game) if hint.eliminations]
    assert filtered
    assert all(hint.eliminations == (retained,) for hint in filtered)
    assert game.snapshot() == before
    game.notes[retained[0]].clear()
    assert not any(hint.eliminations for hint in iter_hints(game))


def test_candidate_review_stages_and_undo(game: Game) -> None:
    """Review only marked empty cells, reveal on step two, and undo all repairs together."""
    from sudoku.hints import candidate_review, hint_steps, iter_hints

    game.mark(1, 9)
    game.mark(2, 9)
    game.mark(3, game.puzzle.solution[3])
    before = game.snapshot()
    hint: Hint | None = next_hint(game)
    assert hint and hint.technique == "Candidate Review"
    assert [step.technique for step in iter_hints(game)] == ["Candidate Review"]
    assert hint.placements == ((1, game.puzzle.solution[1]), (2, game.puzzle.solution[2]))
    stages = hint_steps(game, hint)
    assert len(stages) == 2
    assert not stages[0].focus and not stages[0].placements
    assert stages[1].placements == hint.placements
    assert "saved solution" in stages[1].text
    assert game.snapshot() == before
    game.begin_gesture()
    for index, digit in hint.placements:
        game.set_value(index, digit, False)
    game.end_gesture()
    assert candidate_review(game) is None
    game.undo()
    assert game.snapshot() == before


def game_with_one_in_r2c7() -> Game:
    """Build a valid board where 1 at r5c7 would contradict a filled column peer."""
    solution: tuple[int, ...] = tuple(
        (row * 3 + row // 3 + column) % 9 + 1 for row in range(9) for column in range(9)
    )
    givens: tuple[int, ...] = tuple(1 if index == 15 else 0 for index in range(81))
    return Game(Puzzle("invalid-note", givens, solution, 5.6, "Expert"))


def test_invalid_note_precedes_xy_chain_and_can_be_undone() -> None:
    """A filled 1 at r2c7 makes the marked 1 at r5c7 the next useful hint."""
    from sudoku.hints import candidate_review, hint_steps, iter_hints

    game: Game = game_with_one_in_r2c7()
    target: int = 42
    game.notes[target] = {1, 7, game.puzzle.solution[target]}
    before: object = game.snapshot()

    hint: Hint | None = next_hint(game)
    assert hint and hint.technique == "Candidate Review"
    assert hint.eliminations == ((target, 1),)
    assert hint.placements == ()
    assert [item.technique for item in iter_hints(game)] == ["Candidate Review"]
    steps = hint_steps(game, hint)
    assert len(steps) == 2
    assert "row 5, column 7" in steps[0].text
    assert "row 2, column 7" in steps[1].text
    assert "same column" in steps[1].text
    assert steps[1].eliminations == ((target, 1),)
    assert not steps[0].eliminations
    assert game.snapshot() == before

    assert game.eliminate(hint.eliminations)
    assert game.notes[target] == {7, game.puzzle.solution[target]}
    assert candidate_review(game) is None
    assert game.undo()
    assert game.snapshot() == before


def test_candidate_review_prioritizes_invalid_mark_over_missing_answer() -> None:
    """Resolve a demonstrable contradiction before a separate answer-based review."""
    from sudoku.hints import candidate_review

    game: Game = game_with_one_in_r2c7()
    game.notes[42] = {1, 7}
    first: Hint | None = candidate_review(game)
    assert first and first.eliminations == ((42, 1),)
    assert game.eliminate(first.eliminations)
    second: Hint | None = candidate_review(game)
    assert second and second.placements == ((42, game.puzzle.solution[42]),)


def test_reintroduced_verified_exclusion_gets_candidate_review(game: Game) -> None:
    """A note restored after an applied hint is reviewed before new logic."""
    from sudoku.hints import hint_steps

    game.notes[1] = {game.puzzle.solution[1], 8}
    game.excluded[1].add(8)
    hint: Hint | None = next_hint(game)
    assert hint and hint.technique == "Candidate Review"
    assert hint.eliminations == ((1, 8),)
    assert "earlier applied hint" in hint_steps(game, hint)[1].text


def test_manual_elimination_unlocks_xy_chain_without_mutating_game() -> None:
    """Carry proven r1c2≠1 forward to find the reported r1c6≠3 XY-Chain."""
    import json
    from pathlib import Path
    from typing import Any

    from sudoku.hints import hint_steps, iter_hints
    from sudoku.storage import parse_snapshot

    data: dict[str, Any] = json.loads(
        (Path(__file__).parent / "fixtures/xy_chain_after_manual_elimination.json").read_text()
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
    before: object = game.snapshot()
    assert 1 in game.logical_candidates()[1] and 1 not in game.notes[1]
    hint: Hint = next(
        hint
        for hint in iter_hints(game)
        if hint.technique == "XY-Chain" and (5, 3) in hint.eliminations
    )
    assert (1, 1) in hint.verified_eliminations
    assert hint.prerequisites
    assert (1, 1) not in hint.eliminations
    assert all(digit in game.notes[index] for index, digit in hint.eliminations)
    stages = hint_steps(game, hint)
    assert (1, 1) not in stages[1].candidates
    assert "independently verified removals" not in stages[1].text
    assert "Locked Candidates:" not in stages[1].text
    assert "Suppose" in stages[1].text
    assert all(digit in game.notes[index] for stage in stages for index, digit in stage.candidates)
    assert game.snapshot() == before and not game.undo_stack and not game.redo_stack
    # Entering an absent mark makes it actionable again, rather than silently assuming it removed.
    game.notes[1].add(1)
    assert any((1, 1) in candidate.eliminations for candidate in iter_hints(game))


def test_hint_evidence_does_not_recreate_unmarked_candidates(game: Game) -> None:
    """Annotations show existing notes, even when more logical candidates are possible."""
    from sudoku.hints import hint_steps

    game.notes[1] = {2, 3}
    assert {4, 5}.issubset(game.logical_candidates()[1] - game.notes[1])
    hint: Hint = Hint(
        "XY-Chain",
        "Look here",
        "Follow these two candidates.",
        (1,),
        eliminations=((1, 3),),
        prerequisites=("An earlier removal was already made.",),
    )
    stages = hint_steps(game, hint)
    assert set(stages[1].candidates) == {(1, 2), (1, 3)}
    assert set(stages[2].candidates) == {(1, 2), (1, 3)}
    assert "earlier removal" not in stages[1].text
    assert "Follow these two candidates." in stages[1].text
