# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Board input-policy tests."""

from sudoku.board import candidate_painting_enabled, cells_crossed_by_segment
from sudoku.model import Game, Preferences


def test_answer_mode_candidate_painting_follows_preference(game: Game) -> None:
    """Share the Answers-mode preference between pointer and Shift-arrow strokes."""
    game.note_mode = False
    assert candidate_painting_enabled(game, Preferences())
    assert not candidate_painting_enabled(game, Preferences(drag_answers_as_candidates=False))


def test_candidate_mode_always_allows_painting(game: Game) -> None:
    """Keep candidate strokes available even when the Answers-mode option is off."""
    game.note_mode = True
    assert candidate_painting_enabled(game, Preferences(drag_answers_as_candidates=False))


def cell_center(index: int, cell_size: float = 10.0) -> tuple[float, float]:
    """Return a test point at the center of one board cell."""
    return (
        1 + (index % 9 + 0.5) * cell_size,
        1 + (index // 9 + 0.5) * cell_size,
    )


def test_diagonal_stroke_only_crosses_diagonal_cells() -> None:
    """Do not include orthogonal neighbors when a stroke passes through grid corners."""
    assert cells_crossed_by_segment(cell_center(0), cell_center(20), 92.0) == [0, 10, 20]


def test_corner_graze_does_not_select_neighboring_cell() -> None:
    """Ignore a shallow clip through a cell corner while retaining intended endpoints."""
    near_second_center: tuple[float, float] = (16.0, 15.5)
    assert cells_crossed_by_segment(cell_center(0), near_second_center, 92.0) == [0, 10]


def test_straight_stroke_crosses_each_cell_in_order() -> None:
    """Retain all intentional cells along a horizontal candidate stroke."""
    assert cells_crossed_by_segment(cell_center(0), cell_center(2), 92.0) == [0, 1, 2]


def test_shift_digits_select_without_editing(game: Game) -> None:
    """Real macOS shifted number events choose tools without changing answers or notes."""
    from types import SimpleNamespace
    from typing import Any
    from unittest.mock import Mock

    import AppKit as AK

    from sudoku.board import SudokuBoard

    board: Any = SudokuBoard.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 590, 590))
    preferences: Preferences = Preferences()
    controller: Any = SimpleNamespace(
        game=game, preferences=preferences, save=Mock(), refresh=Mock(), changed=Mock()
    )
    board.controller = controller
    game.selected = 1
    game.mark(1, 8)
    before: object = game.snapshot()
    history: list[object] = list(game.undo_stack)
    key_codes: tuple[int, ...] = (18, 19, 20, 21, 23, 22, 26, 28, 25)
    make_event: Any = getattr(  # noqa: B009 - split the long Cocoa selector for readability.
        AK.NSEvent,
        "keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_"
        "characters_charactersIgnoringModifiers_isARepeat_keyCode_",
    )
    for order in ("Cell First", "Number First"):
        preferences.input_order = order
        for notes in (False, True):
            game.note_mode = notes
            for number, symbol, code in zip("123456789", "!@#$%^&*(", key_codes, strict=True):
                event: Any = make_event(
                    AK.NSEventTypeKeyDown,
                    (0, 0),
                    AK.NSEventModifierFlagShift,
                    0,
                    0,
                    None,
                    symbol,
                    symbol,
                    False,
                    code,
                )
                board.keyDown_(event)
                assert game.active_digit == int(number)
                assert game.snapshot() == before
                assert game.undo_stack == history
                assert game.selected == 1
                assert game.note_mode == notes
    controller.changed.assert_not_called()


def test_candidate_click_respects_entry_order(game: Game) -> None:
    """A cell-first click preserves notes, while number-first clicks toggle the active note."""
    from types import SimpleNamespace
    from typing import Any
    from unittest.mock import Mock

    import AppKit as AK

    from sudoku.board import SudokuBoard

    board: Any = SudokuBoard.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 590, 590))
    preferences: Preferences = Preferences(input_order="Cell First")
    board.controller = SimpleNamespace(game=game, preferences=preferences, changed=Mock())
    event: Any = Mock()
    event.modifierFlags.return_value = 0
    game.note_mode = True
    game.active_digit = 4
    game.mark(1, 4)
    before: object = game.snapshot()
    history: list[object] = list(game.undo_stack)
    for index in (1, 2):
        game.selected = index
        board.drag_origin = index
        game.begin_gesture()
        board.mouseUp_(event)
        assert game.snapshot() == before
        assert game.undo_stack == history
        assert game.selected == index
        assert not board.apply_active_digit(index)
    preferences.input_order = "Number First"
    board.drag_origin = 2
    game.begin_gesture()
    board.mouseUp_(event)
    assert game.notes[2] == {4}
    board.drag_origin = 2
    game.begin_gesture()
    board.mouseUp_(event)
    assert not game.notes[2]
