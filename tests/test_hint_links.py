# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Check diagram relationships against Sudoku constraints and progressive hint behavior."""

from collections.abc import Iterator
from itertools import chain

from scripts.preview_hint_links import preview_game, preview_hint
from sudoku.engine import DIGITS, PEERS, UNITS
from sudoku.hint_chains import inference_chain_hints
from sudoku.hint_types import Hint, HintLink
from sudoku.hints import (
    coloring_hints,
    hint_steps,
    iter_hints,
    turbot_chain_hints,
    w_wing_hints,
    xy_chain_hints,
    xy_wing_hints,
)
from sudoku.model import Game


def assert_link_sound(link: HintLink, options: list[set[int]]) -> None:
    """Independently verify exclusivity or complete occupancy of a cell or unit."""
    first, second = link.start, link.end
    assert all(first.digit in options[cell] for cell in first.cells)
    assert all(second.digit in options[cell] for cell in second.cells)
    same_cell: bool = len(first.cells) == len(second.cells) == 1 and first.cells == second.cells
    if link.strong:
        if same_cell:
            assert first.digit != second.digit
            assert options[first.cells[0]] == {first.digit, second.digit}
        else:
            assert first.digit == second.digit
            assert set(first.cells).isdisjoint(second.cells)
            assert any(
                {cell for cell in unit if first.digit in options[cell]}
                == set(first.cells + second.cells)
                for unit in UNITS
            )
    else:
        assert (same_cell and first.digit != second.digit) or (
            first.digit == second.digit
            and all(b in PEERS[a] for a in first.cells for b in second.cells)
        )


def test_screenshot_diagram_survives_filtering_and_has_exact_candidates() -> None:
    """Keep the seven-link proof through removal filtering without changing notes."""
    game: Game = preview_game()
    before: object = game.snapshot()
    hint: Hint = preview_hint(game)
    assert len(hint.links) == 7
    assert [link.strong for link in hint.links] == [False, True, False, True, False, True, False]
    assert hint.links[0].start.cells == (29,) and hint.links[0].start.digit == 2
    assert hint.links[-1].end == hint.links[0].start
    assert all(
        first.end == second.start for first, second in zip(hint.links, hint.links[1:], strict=False)
    )
    steps = hint_steps(game, hint)
    assert not steps[0].links and not steps[0].candidates
    assert steps[1].links == steps[2].links == hint.links
    assert set(steps[1].candidates) == {
        (29, 2),
        (29, 4),
        (30, 2),
        (30, 9),
        (31, 4),
        (49, 4),
        (49, 9),
    }
    assert not steps[1].eliminations and steps[2].eliminations == ((29, 2),)
    assert "Solid:" in steps[1].text and "Dotted:" in steps[1].text
    assert len(steps[1].text) < 350
    assert game.snapshot() == before


def test_missing_link_evidence_is_temporary_and_never_changes_notes() -> None:
    """Explain an established proof even when an endpoint is missing from manual notes."""
    game: Game = preview_game()
    hint: Hint = preview_hint(game)
    game.notes[49].discard(9)
    before: object = game.snapshot()
    steps = hint_steps(game, hint)
    assert (49, 9) in steps[1].candidates
    assert not game.notes[49] & {9}
    assert game.snapshot() == before


def test_every_screenshot_link_is_proved_on_its_verified_candidate_grid() -> None:
    """Check every offered diagram after the engine's independently proved exclusions."""
    game: Game = preview_game()
    linked: int = 0
    for hint in iter_hints(game):
        options: list[set[int]] = game.logical_candidates()
        for cell, digit in hint.verified_eliminations:
            options[cell].discard(digit)
        for link in hint.links:
            assert_link_sound(link, options)
            linked += 1
    assert linked > 7


def linked_patterns(options: list[set[int]]) -> Iterator[Hint]:
    """Exercise all individual-candidate diagram detectors on one constraint grid."""
    return chain(
        xy_wing_hints(options),
        w_wing_hints(options),
        coloring_hints(options),
        turbot_chain_hints(options),
        xy_chain_hints(options),
        inference_chain_hints(options),
    )


def test_individual_and_grouped_links_obey_constraints() -> None:
    """Ensure diagrams never promote a weak relationship or split a strong OR group."""
    options: list[set[int]] = [set(DIGITS) for _ in range(81)]
    options[0], options[3], options[27] = {1, 2}, {2, 3}, {1, 3}
    for hint in linked_patterns(options):
        assert hint.links
        for link in hint.links:
            assert_link_sound(link, options)
    options = [set(DIGITS) for _ in range(81)]
    for row, columns in ((0, {0, 1, 3}), (3, {0, 3})):
        for column in range(9):
            if column not in columns:
                options[row * 9 + column].discard(1)
    grouped_hint: Hint = next(
        hint for hint in inference_chain_hints(options, grouped=True) if (9, 1) in hint.eliminations
    )
    assert any(
        len(node.cells) > 1 for link in grouped_hint.links for node in (link.start, link.end)
    )
    for link in grouped_hint.links:
        assert_link_sound(link, options)
    game: Game = preview_game()
    assert "boxed group" in hint_steps(game, grouped_hint)[1].text
