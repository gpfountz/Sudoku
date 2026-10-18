# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Indexed, read-only puzzle resources with bounded-memory access."""

import json
import os
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, overload

from sudoku.model import LEVELS, Puzzle


def level_filename(level: str) -> str:
    """Return a safe stable filename for a recognized difficulty."""
    if level not in LEVELS:
        raise ValueError(f"Unknown difficulty: {level}")
    return f"{level.lower()}.sqlite"


@contextmanager
def read_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open an existing catalog without creating files, journals, or write access."""
    connection: sqlite3.Connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError(f"Unsupported catalog schema: {path}")
        yield connection
    finally:
        connection.close()


def puzzle_from_row(row: tuple[Any, ...]) -> Puzzle:
    """Decode one indexed immutable puzzle row."""
    return Puzzle(str(row[0]), tuple(map(int, row[1])), tuple(map(int, row[2])), row[3], row[4])


class DifficultyCatalog(Sequence[Puzzle]):
    """Expose bounded slices for tooling while runtime uses indexed IDs and ordinals."""

    def __init__(self, path: Path, level: str) -> None:
        """Read only small catalog metadata at startup."""
        self.path: Path = path
        self.level: str = level
        with read_database(path) as connection:
            metadata: dict[str, str] = dict(connection.execute("SELECT key,value FROM metadata"))
        if metadata["level"] != level:
            raise ValueError(f"Catalog difficulty mismatch: {path}")
        self.row_count: int = int(metadata["count"])
        if self.row_count < 1:
            raise ValueError(f"Empty catalog: {level}")

    def __len__(self) -> int:
        """Return the prepared row count without scanning puzzle rows."""
        return self.row_count

    @overload
    def __getitem__(self, index: int) -> Puzzle: ...

    @overload
    def __getitem__(self, index: slice) -> list[Puzzle]: ...

    def __getitem__(self, index: int | slice) -> Puzzle | list[Puzzle]:
        """Retrieve an ordinal or explicitly requested bounded slice."""
        if isinstance(index, slice):
            return [self[position] for position in range(*index.indices(self.row_count))]
        position: int = index + self.row_count if index < 0 else index
        if not 0 <= position < self.row_count:
            raise IndexError(index)
        return self.by_ordinal(position + 1)

    def by_ordinal(self, ordinal: int) -> Puzzle:
        """Fetch one row by its dense integer primary key."""
        with read_database(self.path) as connection:
            row: Any = connection.execute(
                "SELECT id,givens,solution,rating,level FROM puzzles WHERE ordinal=?", (ordinal,)
            ).fetchone()
        if row is None:
            raise KeyError(ordinal)
        return puzzle_from_row(row)

    def ordinal(self, identifier: str) -> int | None:
        """Resolve a stable ID using the unique ID index."""
        with read_database(self.path) as connection:
            row: Any = connection.execute(
                "SELECT ordinal FROM puzzles WHERE id=?", (identifier,)
            ).fetchone()
        return int(row[0]) if row else None

    def find(self, identifier: str) -> Puzzle | None:
        """Retrieve one stable ID without materializing a difficulty."""
        with read_database(self.path) as connection:
            row: Any = connection.execute(
                "SELECT id,givens,solution,rating,level FROM puzzles WHERE id=?", (identifier,)
            ).fetchone()
        return puzzle_from_row(row) if row else None


class Catalog(Mapping[str, DifficultyCatalog]):
    """Hold six small resource descriptors, never the catalog's puzzle rows."""

    def __init__(self, directory: Path) -> None:
        """Resolve the atomically published catalog generation."""
        manifest: dict[str, Any] = json.loads((directory / "manifest.json").read_text())
        generation: str = manifest["generation"]
        if manifest.get("version") != 1 or not generation.isalnum():
            raise ValueError("Invalid catalog manifest")
        self.generation: str = generation
        self.given_matches: dict[tuple[int, ...], Puzzle | None] = {}
        self.groups: dict[str, DifficultyCatalog] = {
            level: DifficultyCatalog(directory / generation / level_filename(level), level)
            for level in LEVELS
        }

    def __getitem__(self, level: str) -> DifficultyCatalog:
        """Return one lazy difficulty descriptor."""
        return self.groups[level]

    def __len__(self) -> int:
        """Return the number of difficulty bands."""
        return len(self.groups)

    def __iter__(self) -> Iterator[str]:
        """Iterate difficulty names without reading puzzles."""
        return iter(self.groups)

    def find(self, identifier: str) -> Puzzle | None:
        """Resolve a legacy ID through at most six indexed lookups."""
        for group in self.groups.values():
            puzzle: Puzzle | None = group.find(identifier)
            if puzzle:
                return puzzle
        return None

    def find_givens(
        self, givens: tuple[int, ...], cancelled: Callable[[], bool] | None = None
    ) -> Puzzle | None:
        """Match exact clues across every band, retaining only eight recent scan results."""
        if cancelled is not None and cancelled():
            raise ValueError("Import cancelled")
        if givens in self.given_matches:
            return self.given_matches[givens]
        digits: str = "".join(map(str, givens))
        match: Puzzle | None = None
        for group in self.groups.values():
            if cancelled is not None and cancelled():
                raise ValueError("Import cancelled")
            with read_database(group.path) as connection:
                row: Any = connection.execute(
                    "SELECT id,givens,solution,rating,level FROM puzzles WHERE givens=? LIMIT 1",
                    (digits,),
                ).fetchone()
            if row is not None:
                match = puzzle_from_row(row)
                break
        if len(self.given_matches) >= 8:
            self.given_matches.clear()
        self.given_matches[givens] = match
        return match


def load_catalog(directory: Path | None = None) -> Catalog:
    """Open actual database resources from a source checkout or standalone app."""
    if directory is None and os.environ.get("SUDOKU_CATALOG_DIR"):
        directory = Path(os.environ["SUDOKU_CATALOG_DIR"])
    if directory is None:
        directory = (
            Path(
                os.environ.get(
                    "RESOURCEPATH", str(Path(sys.executable).parent.parent / "Resources")
                )
            )
            / "catalog"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent / "data" / "catalog"
        )
    return Catalog(directory)
