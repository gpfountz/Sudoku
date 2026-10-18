# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Behavioral checks for reversible entry, checking, and candidate maintenance."""

import pytest

from sudoku.engine import candidates, conflicts, solve
from sudoku.model import Game, Preferences, Puzzle, Snapshot


def game_with_blanks(game: Game, blanks: set[int]) -> Game:
    """Create a nearly completed fixture with editable cells at the requested indexes."""
    solution: tuple[int, ...] = game.puzzle.solution
    givens: list[int] = list(solution)
    for index in blanks:
        givens[index] = 0
    return Game(Puzzle("singles-test", tuple(givens), solution, 1.0, "Easy"))


@pytest.mark.parametrize("digit", range(10))
def test_solution_checking_blocks_changes_to_correct_answers(game: Game, digit: int) -> None:
    """Rejected edits preserve notes, eliminations, history, and mistake tracking."""
    game.set_value(7, 8)
    game.mark(8, 3)
    game.undo()
    game.excluded[8] = {3}
    before: Snapshot = game.snapshot()
    history: list[Snapshot] = list(game.undo_stack)
    redo: list[Snapshot] = list(game.redo_stack)
    assert not game.can_edit_answer(7, "Against Solution")
    assert not game.set_value(7, digit, error_check="Against Solution")
    assert not game.clear(7, error_check="Against Solution")
    assert game.snapshot() == before
    assert game.undo_stack == history
    assert game.redo_stack == redo
    assert not game.incorrect_entries


def test_solution_protection_allows_corrections_and_explicit_undo(game: Game) -> None:
    """Empty and incorrect cells stay editable, with reversible correct placements."""
    assert game.can_edit_answer(7, "Against Solution")
    assert game.set_value(7, 3, error_check="Against Solution")
    assert game.clear(7, error_check="Against Solution")
    assert game.set_value(7, 3, error_check="Against Solution")
    assert game.set_value(7, 8, error_check="Against Solution")
    assert not game.can_edit_answer(7, "Against Solution")
    assert game.undo()
    assert game.values[7] == 3
    assert game.redo()
    assert game.values[7] == 8
    game.active_color = 2
    assert game.paint_color(7)
    assert game.values[7] == 8
    assert game.colors[7] == 2


@pytest.mark.parametrize("error_check", ["Off", "Rule Conflicts"])
def test_leaving_solution_checking_allows_answer_edits(game: Game, error_check: str) -> None:
    """The current setting determines protection without storing permanent cell locks."""
    game.set_value(7, 8, error_check="Against Solution")
    assert game.can_edit_answer(7, error_check)
    assert game.set_value(7, 3, error_check=error_check)
    game.set_value(7, 8)
    assert game.clear(7, error_check=error_check)


def test_givens_and_filled_cells_are_protected(game: Game) -> None:
    """Never modify givens or add pencil marks inside filled cells."""
    assert not game.set_value(0, 8)
    assert not game.clear(0)
    assert not game.mark(0, 3)
    game.set_value(1, 2)
    assert not game.mark(1, 3)


def test_answer_cleanup_is_atomic_and_reversible(game: Game) -> None:
    """Undo restores every peer note removed by one answer placement."""
    game.mark(2, 2)
    game.mark(10, 2)
    game.mark(80, 2)
    before: Snapshot = game.snapshot()
    assert game.set_value(1, 2)
    assert 2 not in game.notes[2] and 2 not in game.notes[10]
    assert 2 in game.notes[80]
    assert game.undo()
    assert game.snapshot() == before
    assert game.redo()
    assert game.values[1] == 2


def test_cleanup_can_be_disabled(game: Game) -> None:
    """Keep manually maintained peer notes when cleanup is off."""
    game.mark(2, 2)
    game.set_value(1, 2, cleanup=False)
    assert game.notes[2] == {2}


def test_painting_is_idempotent_and_one_undo_action(game: Game) -> None:
    """A gesture visiting a cell repeatedly adds a note only once."""
    game.begin_gesture()
    for index in (0, 1, 2, 2, 3):
        game.mark(index, 5, "add")
    assert game.end_gesture()
    assert len(game.undo_stack) == 1
    assert game.notes[1:4] == [{5}, {5}, {5}]
    assert not game.notes[0]
    game.undo()
    assert not any(game.notes)
    game.redo()
    game.begin_gesture()
    for index in (1, 2, 3):
        game.mark(index, 5, "remove")
    game.end_gesture()
    assert not any(game.notes)
    game.undo()
    assert game.notes[1:4] == [{5}, {5}, {5}]


def test_color_strokes_include_givens_and_undo_together(game: Game) -> None:
    """Color and clear strokes work on every cell and remain reversible."""
    game.active_color = 3
    assert game.color_stroke_operation(0) == "add"
    game.begin_gesture()
    for index in (0, 1, 2, 2):
        game.paint_color(index, "add")
    assert game.end_gesture()
    assert game.colors[:3] == [3, 3, 3]
    assert len(game.undo_stack) == 1
    assert game.color_stroke_operation(0) == "remove"
    game.active_color = 9
    assert game.color_stroke_operation(1) == "remove"
    assert game.paint_color(1)
    assert game.colors[1] == 0
    assert game.undo()
    assert game.colors[:3] == [3, 3, 3]
    assert game.undo()
    assert game.colors[:3] == [0, 0, 0]
    assert game.redo()
    assert game.colors[:3] == [3, 3, 3]


def test_clear_all_colors_is_one_reversible_edit(game: Game) -> None:
    """A confirmed board-wide clear preserves other content and one undo step."""
    game.active_color = 4
    game.paint_color(0)
    game.paint_color(1)
    before: Snapshot = game.snapshot()
    history_length: int = len(game.undo_stack)
    assert game.clear_all_colors()
    assert not any(game.colors)
    assert len(game.undo_stack) == history_length + 1
    assert game.undo()
    assert game.snapshot() == before


def test_new_edit_clears_redo_but_navigation_does_not(game: Game) -> None:
    """Only changed board content invalidates redo history."""
    game.mark(1, 2)
    game.undo()
    game.move(1, 0)
    assert game.redo_stack
    game.mark(2, 3)
    assert not game.redo_stack


@pytest.mark.parametrize(
    "start,delta,expected",
    [(0, (-1, 0), 0), (8, (0, 1), 8), (80, (1, 0), 80), (9, (0, -1), 9), (40, (-1, 0), 31)],
)
def test_movement_clamps_without_wrapping(
    game: Game, start: int, delta: tuple[int, int], expected: int
) -> None:
    """Board navigation respects every edge."""
    game.selected = start
    assert game.move(*delta) == expected


def test_error_modes_distinguish_wrong_answers_from_conflicts(game: Game) -> None:
    """A legal-looking wrong answer is flagged only by solution checking."""
    game.set_value(1, 3)
    assert game.errors("Rule Conflicts") == set()
    assert game.errors("Against Solution") == {1}
    assert game.errors("Off") == set()
    game.set_value(2, 3)
    assert game.errors("Rule Conflicts") == {1, 2}


def test_fill_candidates_uses_entries_and_is_undoable(game: Game) -> None:
    """Fill derives legal options without consulting the stored answer."""
    game.mark(1, 8)
    before: Snapshot = game.snapshot()
    game.set_value(20, 4)
    game.fill_candidates()
    assert game.notes == candidates(game.values)
    assert 1 not in game.notes[1]
    assert len(game.notes[1]) > 1
    game.undo()
    game.undo()
    assert game.snapshot() == before


def test_auto_complete_cascades_and_undoes_as_one_action(game: Game) -> None:
    """Recompute forced singles until solved and retain one history entry for the cascade."""
    blanks: set[int] = {6, 10, 16, 20, 22, 37, 44, 54, 58, 63, 64, 66, 68, 72, 78}
    singles_game: Game = game_with_blanks(game, blanks)
    before: Snapshot = singles_game.snapshot()
    assert len(singles_game.forced_single_placements()) == 14
    assert singles_game.auto_complete_singles() == 15
    assert singles_game.complete
    assert len(singles_game.undo_stack) == 1
    assert singles_game.undo()
    assert singles_game.snapshot() == before
    assert singles_game.redo()
    assert singles_game.complete


def test_auto_complete_includes_hidden_singles(game: Game) -> None:
    """Recognize a unit's sole position even when that cell has several legal digits."""
    blanks: set[int] = {
        6,
        12,
        13,
        19,
        24,
        25,
        29,
        39,
        42,
        51,
        58,
        60,
        61,
        62,
        66,
        72,
        74,
        76,
        77,
        80,
    }
    singles_game: Game = game_with_blanks(game, blanks)
    assert singles_game.logical_candidates()[24] == {4, 5}
    assert singles_game.forced_single_placements()[24] == 4


def test_auto_complete_prefers_legal_single_over_incorrect_note(game: Game) -> None:
    """Fill a rule-based single even when its pencil mark contains the wrong digit."""
    singles_game: Game = game_with_blanks(game, {1})
    singles_game.mark(1, 9)
    singles_game.undo_stack.clear()
    assert singles_game.auto_complete_singles() == 1
    assert singles_game.values[1] == singles_game.puzzle.solution[1]
    assert not singles_game.notes[1]


def test_auto_complete_fills_reported_manual_single_and_undoes() -> None:
    """Fill the reported r8c1=7 despite legal options {4, 7}, preserving undo and redo."""
    givens: tuple[int, ...] = tuple(
        map(
            int, "043000610106000502500000009001020700050000020090705060600402003000080000030609070"
        )
    )
    solution: tuple[int, ...] = tuple(
        map(
            int, "943258617186947532572361489361824795857196324294735861618472953729583146435619278"
        )
    )
    values: list[int] = list(
        map(
            int, "943258617186007502572000009061024705050000020290735061610472053020583106035619270"
        )
    )
    game: Game = Game(
        Puzzle("manual-single-regression", givens, solution, 5.6, "Expert"),
        values=values,
        notes=candidates(values),
    )
    game.notes[63] = {7}
    assert game.logical_candidates()[63] == {4, 7}
    assert not game.forced_single_placements()
    before: Snapshot = game.snapshot()

    assert game.auto_complete_singles() > 0
    assert game.values[63] == 7
    assert not game.wrong_answers()
    assert len(game.undo_stack) == 1
    after: Snapshot = game.snapshot()
    assert game.undo()
    assert game.snapshot() == before
    assert game.redo()
    assert game.snapshot() == after


@pytest.mark.parametrize("cleanup", [True, False])
def test_auto_complete_cascades_manual_singles_and_respects_cleanup(
    game: Game, cleanup: bool
) -> None:
    """Cascade correct pencil singles only when peer cleanup exposes the next lone mark."""
    game.notes[1] = {2}
    game.notes[2] = {2, 3}
    game.notes[10] = {2, 5}
    game.notes[80] = {8, 9}
    before: Snapshot = game.snapshot()

    assert game.auto_complete_singles(cleanup) == (3 if cleanup else 1)
    assert game.values[1] == 2
    if cleanup:
        assert game.values[2] == 3 and game.values[10] == 5
        assert not game.notes[2] and not game.notes[10]
    else:
        assert game.values[2] == game.values[10] == 0
        assert game.notes[2] == {2, 3} and game.notes[10] == {2, 5}
    assert game.notes[80] == {8, 9}
    assert len(game.undo_stack) == 1
    assert game.undo()
    assert game.snapshot() == before


@pytest.mark.parametrize("notes", [{3}, {2, 3}])
def test_auto_complete_skips_incorrect_or_incomplete_manual_notes(
    game: Game, notes: set[int]
) -> None:
    """Leave wrong lone marks and partial multi-digit notes unchanged without revealing answers."""
    game.notes[1] = notes
    assert notes <= game.logical_candidates()[1]
    before: Snapshot = game.snapshot()
    assert game.auto_complete_singles() == 0
    assert game.snapshot() == before
    assert not game.undo_stack


def test_auto_complete_stops_without_forced_singles(game: Game) -> None:
    """Leave the board and history unchanged when no forced placement exists."""
    before: Snapshot = game.snapshot()
    assert game.auto_complete_singles() == 0
    assert game.snapshot() == before
    assert not game.undo_stack


def test_auto_complete_refuses_incorrect_answers(game: Game) -> None:
    """Do not derive placements from a board containing an incorrect answer."""
    game.set_value(1, 3)
    game.mark(2, game.puzzle.solution[2])
    before: Snapshot = game.snapshot()
    assert game.auto_complete_singles() == 0
    assert game.snapshot() == before


def test_pause_blocks_edits(game: Game) -> None:
    """Pausing prevents direct changes and undo/redo."""
    game.mark(1, 8)
    game.mark(2, game.puzzle.solution[2])
    game.paused = True
    before: Snapshot = game.snapshot()
    assert not game.set_value(1, 2)
    assert not game.mark(1, 4)
    assert not game.clear(1)
    assert not game.fill_candidates()
    assert game.auto_complete_singles() == 0
    assert not game.undo()
    assert game.snapshot() == before


def test_complete_requires_correct_solution(game: Game) -> None:
    """A filled board is complete only if its values solve the puzzle."""
    game.values = list(game.puzzle.solution)
    assert game.complete
    game.values[1] = 1
    assert not game.complete


def test_solver_detects_no_solution_and_multiple_solutions(game: Game) -> None:
    """The catalog validator distinguishes invalid, unique, and ambiguous boards."""
    values: list[int] = list(game.puzzle.solution)
    values[1] = 0
    assert solve(values) == [game.puzzle.solution]
    values[1] = 1
    assert conflicts(values)
    assert solve(values) == []
    assert len(solve([0] * 81)) == 2
    assert solve([0] * 80) == []


def test_preferences_validate_values() -> None:
    """Ignore malformed settings while preserving recognized choices."""
    prefs: Preferences = Preferences.from_dict(
        {
            "appearance": "Dark",
            "theme": "Warm Paper",
            "error_check": "bad",
            "highlight_digits": "false",
        }
    )
    assert prefs.appearance == "Dark"
    assert prefs.theme == "Warm Paper"
    assert prefs.error_check == "Rule Conflicts"
    assert prefs.highlight_digits is True
    assert Preferences.from_dict({}).theme == "Default"
    assert Preferences.from_dict({"theme": "Unknown"}).theme == "Default"


def test_candidate_stroke_repeats_as_removal(game: Game) -> None:
    """Choose one stroke action from its first cell so repeating a drag erases it."""
    cells: tuple[int, ...] = (1, 2)
    game.begin_gesture()
    operation: str = game.candidate_stroke_operation(cells[0], 4)
    for index in cells:
        game.mark(index, 4, operation)
    assert game.end_gesture()
    assert all(4 in game.notes[index] for index in cells)

    game.begin_gesture()
    operation = game.candidate_stroke_operation(cells[0], 4)
    for index in cells:
        game.mark(index, 4, operation)
    assert game.end_gesture()
    assert all(4 not in game.notes[index] for index in cells)
    assert game.undo()
    assert all(4 in game.notes[index] for index in cells)


def test_candidate_stroke_can_force_removal(game: Game) -> None:
    """Let Option request an idempotent removal stroke from an unmarked cell."""
    assert game.candidate_stroke_operation(1, 7, force_remove=True) == "remove"


def test_completed_digits_follow_answers_and_undo(game: Game) -> None:
    """Count givens and answers, ignore notes, and update completion after erase or undo."""
    positions: list[int] = [i for i, digit in enumerate(game.puzzle.solution) if digit == 1]
    for index in positions[1:-1]:
        game.set_value(index, 1)
    game.mark(positions[-1], 1)
    assert 1 not in game.completed_digits
    game.set_value(positions[-1], 1)
    assert 1 in game.completed_digits
    game.undo()
    assert 1 not in game.completed_digits
    game.redo()
    assert 1 in game.completed_digits
    game.clear(positions[-1])
    assert 1 not in game.completed_digits


def test_completed_digits_do_not_reveal_solution_correctness(game: Game) -> None:
    """Dimming is a visible-entry count even when duplicate answers are incorrect."""
    for index in range(1, 10):
        game.set_value(index, 2)
    assert game.wrong_answers()
    assert 2 in game.completed_digits


def test_completed_digit_preference_supports_old_saves_and_opt_out() -> None:
    """Enable dimming for older settings while honoring a saved opt-out."""
    assert Preferences.from_dict({}).dim_completed_digits
    assert not Preferences.from_dict({"dim_completed_digits": False}).dim_completed_digits


def test_answer_drag_preference_supports_old_saves_and_opt_out() -> None:
    """Enable candidate painting for older settings while honoring a saved opt-out."""
    assert Preferences.from_dict({}).drag_answers_as_candidates
    assert not Preferences.from_dict(
        {"drag_answers_as_candidates": False}
    ).drag_answers_as_candidates
