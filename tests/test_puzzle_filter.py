# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Regression coverage for the Expert puzzles used to calibrate the chain limit."""

from pathlib import Path

import pytest

from sudoku.catalog import Catalog
from sudoku.model import Puzzle
from sudoku.puzzle_filter import solves_without_long_chains


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [("1d0d329e9f551650", False), ("a51200baa647c437", False), ("67b996db6e9ecc49", True)],
)
def test_short_chain_screen_on_reviewed_expert_puzzles(identifier: str, expected: bool) -> None:
    """Reject the two long-chain attempts and still accept an Expert puzzle solved with wings."""
    catalog: Catalog = Catalog(Path(__file__).resolve().parents[1] / "sudoku/data/catalog")
    puzzle: Puzzle | None = catalog["Expert"].find(identifier)
    assert puzzle is not None
    assert solves_without_long_chains(puzzle) is expected
