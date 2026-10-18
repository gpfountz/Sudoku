# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Durable imported puzzle definitions and independently saved play attempts."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sudoku.model import LEVELS, Game, Puzzle
from sudoku.puzzle_import import ValidatedImport
from sudoku.storage import SaveError, game_data, game_from_data

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS puzzles(
    number INTEGER PRIMARY KEY AUTOINCREMENT,
    givens TEXT NOT NULL UNIQUE, solution TEXT NOT NULL,
    level TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(
    attempt_id TEXT PRIMARY KEY, puzzle_number INTEGER NOT NULL REFERENCES puzzles(number),
    state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def is_imported(identifier: str) -> bool:
    """Distinguish imported IDs from the bundled catalog's namespace."""
    return identifier.startswith("IMP-")


class ImportedStore:
    """Keep imported clues immutable and progress independent from bundled selection."""

    def __init__(self, directory: Path) -> None:
        """Retain the injectable data directory without opening a database."""
        self.path: Path = directory / "imported.sqlite3"

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit a versioned transaction or roll back without replacing damaged data."""
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            version: int = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise SaveError("Unsupported imported puzzle database version")
            connection.execute("BEGIN IMMEDIATE")
            if version == 0:
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
            yield connection
            connection.commit()
        except (
            OSError,
            sqlite3.Error,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
        ) as error:
            raise SaveError(f"Imported puzzle storage failed: {error}") from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def puzzle(row: tuple[Any, ...]) -> Puzzle:
        """Decode a stored definition while rejecting malformed immutable fields."""
        number, givens, solution, level = row
        if (
            type(number) is not int
            or number < 1
            or level not in LEVELS
            or not isinstance(givens, str)
            or len(givens) != 81
            or any(digit not in "0123456789" for digit in givens)
            or not isinstance(solution, str)
            or len(solution) != 81
            or any(digit not in "123456789" for digit in solution)
        ):
            raise SaveError("Invalid imported puzzle definition; database preserved")
        from sudoku.engine import conflicts

        values: tuple[int, ...] = tuple(map(int, givens))
        answer: tuple[int, ...] = tuple(map(int, solution))
        if conflicts(answer) or any(value and value != answer[i] for i, value in enumerate(values)):
            raise SaveError("Invalid imported puzzle solution; database preserved")
        return Puzzle(f"IMP-{number:06d}", values, answer, None, level)

    def find(self, identifier: str) -> Puzzle | None:
        """Resolve a saved import without consulting an external source or image."""
        if (
            not is_imported(identifier)
            or not identifier[4:].isascii()
            or not identifier[4:].isdigit()
        ):
            return None
        if not self.path.exists():
            return None
        with self.transaction() as connection:
            row: Any = connection.execute(
                "SELECT number,givens,solution,level FROM puzzles WHERE number=?",
                (int(identifier[4:]),),
            ).fetchone()
            return self.puzzle(row) if row else None

    def start(self, validated: ValidatedImport, level: str) -> Game:
        """Deduplicate clues, retain the chosen level, and save a fresh attempt."""
        if level not in LEVELS:
            raise ValueError("Choose a difficulty")
        timestamp: str = datetime.now(UTC).isoformat()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO puzzles(givens,solution,level,created_at) VALUES (?,?,?,?) "
                "ON CONFLICT(givens) DO UPDATE SET level=excluded.level",
                (
                    "".join(map(str, validated.givens)),
                    "".join(map(str, validated.solution)),
                    level,
                    timestamp,
                ),
            )
            row: Any = connection.execute(
                "SELECT number,givens,solution,level FROM puzzles WHERE givens=?",
                ("".join(map(str, validated.givens)),),
            ).fetchone()
            game: Game = Game(self.puzzle(row))
            self.write_attempt(connection, game, timestamp)
        return game

    def find_givens(self, givens: tuple[int, ...]) -> Puzzle | None:
        """Check for an existing import without creating a database for unplayed review data."""
        if not self.path.exists():
            return None
        with self.transaction() as connection:
            row: Any = connection.execute(
                "SELECT number,givens,solution,level FROM puzzles WHERE givens=?",
                ("".join(map(str, givens)),),
            ).fetchone()
            return self.puzzle(row) if row else None

    @staticmethod
    def write_attempt(connection: sqlite3.Connection, game: Game, timestamp: str) -> None:
        """Persist full progress, including undo and counters, without modifying clues."""
        connection.execute(
            "INSERT INTO attempts VALUES (?,?,?,?,?) ON CONFLICT(attempt_id) "
            "DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
            (
                game.attempt_id,
                int(game.puzzle.identifier[4:]),
                json.dumps(game_data(game), allow_nan=False),
                timestamp,
                timestamp,
            ),
        )

    def save(self, game: Game) -> None:
        """Save an existing import's current attempt, including a restarted attempt."""
        with self.transaction() as connection:
            self.write_attempt(connection, game, datetime.now(UTC).isoformat())

    def load(self, identifier: str, attempt_id: str) -> Game:
        """Restore only the exact attempt selected by the active session pointer."""
        puzzle: Puzzle | None = self.find(identifier)
        if puzzle is None:
            raise SaveError(f"Missing imported puzzle {identifier}")
        with self.transaction() as connection:
            row: Any = connection.execute(
                "SELECT state FROM attempts WHERE attempt_id=? AND puzzle_number=?",
                (attempt_id, int(identifier[4:])),
            ).fetchone()
            if row is None:
                raise SaveError("Missing imported attempt; existing data preserved")
            game: Game = game_from_data(json.loads(row[0]), puzzle)
            if game.attempt_id != attempt_id:
                raise SaveError("Imported attempt ID does not match its saved state")
            return game

    def discard(self, game: Game) -> None:
        """Remove a staged attempt after failed activation, retaining previously played imports."""
        with self.transaction() as connection:
            connection.execute("DELETE FROM attempts WHERE attempt_id=?", (game.attempt_id,))
            connection.execute(
                "DELETE FROM puzzles WHERE number=? AND NOT EXISTS "
                "(SELECT 1 FROM attempts WHERE puzzle_number=puzzles.number)",
                (int(game.puzzle.identifier[4:]),),
            )
