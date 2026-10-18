# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Reusable valid Sudoku fixtures."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts.prepare_puzzles import prepare
from sudoku.catalog import Catalog
from sudoku.model import Game, Puzzle
from sudoku.puzzle_import import ValidatedImport, validate_import

SOLUTION: tuple[int, ...] = tuple(
    ((row * 3 + row // 3 + column) % 9) + 1 for row in range(9) for column in range(9)
)


@pytest.fixture
def game() -> Game:
    """Provide an editable board with one protected given and a valid target solution."""
    givens: tuple[int, ...] = (1,) + (0,) * 80
    return Game(Puzzle("test-puzzle", givens, SOLUTION, 1.2, "Easy"))


@pytest.fixture
def unmatched_import(isolated_catalog: Catalog) -> ValidatedImport:
    """Add a valid clue to a catalog puzzle to create a distinct, uniquely solvable import."""
    puzzle: Puzzle = isolated_catalog["Hard"][0]
    givens: list[int] = list(puzzle.givens)
    empty: int = givens.index(0)
    givens[empty] = puzzle.solution[empty]
    assert isolated_catalog.find_givens(tuple(givens)) is None
    return validate_import(tuple(givens))


@pytest.fixture(scope="session", autouse=True)
def isolated_catalog(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Catalog]:
    """Prepare only twelve existing puzzles per band outside the working tree."""
    root: Path = Path(__file__).resolve().parents[1]
    directory: Path = tmp_path_factory.mktemp("catalog")
    source: Path = root / "sudoku/data/puzzles.json"
    if not source.exists():
        bundled: Catalog = Catalog(root / "sudoku/data/catalog")
        records: list[dict[str, Any]] = [
            {
                "id": puzzle.identifier,
                "givens": "".join(map(str, puzzle.givens)),
                "solution": "".join(map(str, puzzle.solution)),
                "rating": puzzle.rating,
                "level": puzzle.level,
            }
            for level in bundled
            for puzzle in bundled[level][:12]
        ]
        source = directory / "subset.json"
        source.write_text(
            json.dumps({"version": 1, "source": "bundled test subset", "puzzles": records})
        )
    prepare(source, directory / "output", limit_per_level=12)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SUDOKU_CATALOG_DIR", str(directory / "output"))
        yield Catalog(directory / "output")
