# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Bounded SQLite history for completed games and stable hint identities."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from sudoku.hint_types import Hint
from sudoku.model import Game
from sudoku.storage import SaveError

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS game_attempts (
    attempt_id TEXT PRIMARY KEY,
    ended_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Completed','Restarted','Abandoned')),
    puzzle_id TEXT NOT NULL,
    level TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL,
    hint_count INTEGER NOT NULL,
    reveal_count INTEGER NOT NULL,
    incorrect_count INTEGER NOT NULL,
    daily_date TEXT
);
CREATE INDEX IF NOT EXISTS game_attempts_newest
ON game_attempts(ended_at DESC, attempt_id DESC);
"""


@dataclass(frozen=True)
class GameHistoryEntry:
    """One ended attempt with its outcome and requested measurements."""

    attempt_id: str
    ended_at: str
    status: str
    puzzle_id: str
    level: str
    elapsed_seconds: float
    hint_count: int
    reveal_count: int
    incorrect_count: int
    daily_date: str | None


def hint_stage_key(game: Game, hint: Hint, stage: int) -> str:
    """Identify one deduction stage on one logical board state."""
    state: dict[str, object] = {
        "hint": asdict(hint),
        "stage": stage,
        "values": game.values,
        "notes": [sorted(notes) for notes in game.notes],
        "excluded": [sorted(excluded) for excluded in game.excluded],
    }
    payload: str = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class HistoryStore:
    """Store ended attempts and retrieve only requested history pages."""

    def __init__(self, path: Path) -> None:
        """Keep the database path without loading any history rows."""
        self.path: Path = path
        self.initialized: bool = False

    def migrate_legacy_database(self) -> None:
        """Move or merge records from the former database filename once."""
        legacy_path: Path = self.path.with_name("statistics.sqlite3")
        if not legacy_path.exists():
            return
        if not self.path.exists():
            legacy_path.replace(self.path)
            return
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.executescript(SCHEMA)
            connection.execute("ATTACH DATABASE ? AS legacy_history", (str(legacy_path),))
            try:
                with connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO game_attempts "
                        "SELECT attempt_id,ended_at,status,puzzle_id,level,elapsed_seconds,"
                        "hint_count,reveal_count,incorrect_count,daily_date "
                        "FROM legacy_history.game_attempts"
                    )
            finally:
                connection.execute("DETACH DATABASE legacy_history")
        legacy_path.unlink()

    def connect(self) -> sqlite3.Connection:
        """Open the database and install its small idempotent schema."""
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.initialized:
                self.migrate_legacy_database()
            connection = sqlite3.connect(self.path, timeout=10)
            if not self.initialized:
                connection.executescript(SCHEMA)
                self.initialized = True
            return connection
        except (OSError, sqlite3.Error) as error:
            if connection is not None:
                connection.close()
            raise SaveError(f"Could not open game history: {error}") from error

    def ensure_ready(self) -> None:
        """Create the history database and migrate any prior records at launch."""
        with closing(self.connect()):
            pass

    def record_outcome(
        self, game: Game, status: str, ended_at: str, daily_date: str | None = None
    ) -> bool:
        """Insert an ended attempt once and report whether a row was added."""
        if status not in ("Completed", "Restarted", "Abandoned"):
            raise ValueError("Unknown game outcome")
        try:
            with closing(self.connect()) as connection:
                with connection:
                    cursor: sqlite3.Cursor = connection.execute(
                        "INSERT OR IGNORE INTO game_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            game.attempt_id,
                            ended_at,
                            status,
                            game.puzzle.identifier,
                            game.puzzle.level,
                            game.elapsed,
                            len(game.viewed_hint_stages),
                            len(game.revealed_cells),
                            len(game.incorrect_entries),
                            daily_date,
                        ),
                    )
                    return cursor.rowcount == 1
        except sqlite3.Error as error:
            raise SaveError(f"Could not save game history: {error}") from error

    def record_completion(self, game: Game, daily_date: str | None = None) -> None:
        """Retry a newly solved game's idempotent history insert."""
        if game.complete and game.solved_at is not None:
            self.record_outcome(game, "Completed", game.solved_at, daily_date)

    def remove_outcome(self, attempt_id: str, status: str = "Abandoned") -> None:
        """Compensate an ended row when starting its replacement fails."""
        if status not in ("Abandoned", "Restarted"):
            raise ValueError("Only replacement outcomes can be compensated")
        try:
            with closing(self.connect()) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM game_attempts WHERE attempt_id=? AND status=?",
                        (attempt_id, status),
                    )
        except sqlite3.Error as error:
            raise SaveError(f"Could not restore game history: {error}") from error

    def count(self) -> int:
        """Return the number of completed rows without loading them."""
        try:
            with closing(self.connect()) as connection:
                row: tuple[int] = connection.execute(
                    "SELECT count(*) FROM game_attempts"
                ).fetchone()
            return row[0]
        except sqlite3.Error as error:
            raise SaveError(f"Could not count game history: {error}") from error

    def has_outcome(self, attempt_id: str) -> bool:
        """Prevent an ended daily attempt from being resumed under its old identity."""
        try:
            with closing(self.connect()) as connection:
                return (
                    connection.execute(
                        "SELECT 1 FROM game_attempts WHERE attempt_id=?", (attempt_id,)
                    ).fetchone()
                    is not None
                )
        except sqlite3.Error as error:
            raise SaveError(f"Could not check ended attempt: {error}") from error

    def page(self, offset: int, limit: int = 64) -> list[GameHistoryEntry]:
        """Read a bounded newest-first page for visible table rows."""
        if offset < 0 or not 1 <= limit <= 128:
            raise ValueError("Invalid history page")
        try:
            with closing(self.connect()) as connection:
                rows: list[tuple[str, str, str, str, str, float, int, int, int, str | None]] = (
                    connection.execute(
                        "SELECT attempt_id,ended_at,status,puzzle_id,level,elapsed_seconds,"
                        "hint_count,reveal_count,incorrect_count,daily_date "
                        "FROM game_attempts ORDER BY ended_at DESC,attempt_id DESC "
                        "LIMIT ? OFFSET ?",
                        (limit, offset),
                    ).fetchall()
                )
            return [GameHistoryEntry(*row) for row in rows]
        except sqlite3.Error as error:
            raise SaveError(f"Could not load game history: {error}") from error
