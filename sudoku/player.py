# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Transactional per-difficulty player history, sparse selection, and JSON migration."""

import json
import random
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sudoku.catalog import Catalog, DifficultyCatalog, level_filename
from sudoku.model import LEVELS, Game, Puzzle
from sudoku.storage import SaveError, Store, game_data, game_from_data

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS games(
    id TEXT NOT NULL, cycle INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('unknown','started','completed')),
    started_at TEXT, last_played_at TEXT, completed_at TEXT, state TEXT,
    PRIMARY KEY(id,cycle));
CREATE TABLE IF NOT EXISTS replays(
    attempt_id TEXT PRIMARY KEY, id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('started','completed')),
    started_at TEXT NOT NULL, last_played_at TEXT NOT NULL,
    completed_at TEXT, state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS games_cycle ON games(cycle);
CREATE TABLE IF NOT EXISTS rotation(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    cycle INTEGER NOT NULL, remaining INTEGER NOT NULL, generation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS swaps(position INTEGER PRIMARY KEY,ordinal INTEGER NOT NULL UNIQUE);
"""


def now() -> str:
    """Return a UTC timestamp only for events actually observed by the app."""
    return datetime.now(UTC).isoformat()


class PlayerStore:
    """Keep regular progress separate from read-only resources and daily JSON data."""

    def __init__(self, store: Store, catalog: Catalog) -> None:
        """Retain injected paths without opening any database until needed."""
        self.store: Store = store
        self.catalog: Catalog = catalog

    @contextmanager
    def transaction(self, level: str) -> Iterator[sqlite3.Connection]:
        """Open a versioned player database and commit or roll back one operation."""
        connection: sqlite3.Connection | None = None
        try:
            path: Path = self.store.directory / "players" / level_filename(level)
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=10)
            version: int = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise SaveError(f"Unsupported player schema in {path}")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            if version == 0:
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("INSERT INTO metadata VALUES ('level',?)", (level,))
                connection.execute("PRAGMA user_version=2")
            elif version == 1:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS replays("
                    "attempt_id TEXT PRIMARY KEY,id TEXT NOT NULL,"
                    "status TEXT NOT NULL CHECK(status IN ('started','completed')),"
                    "started_at TEXT NOT NULL,last_played_at TEXT NOT NULL,"
                    "completed_at TEXT,state TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version=2")
            saved_level: Any = connection.execute(
                "SELECT value FROM metadata WHERE key='level'"
            ).fetchone()
            if not saved_level or saved_level[0] != level:
                raise SaveError(f"Wrong difficulty in {path}")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError, ValueError) as error:
            raise SaveError(f"Player storage failed for {level}: {error}") from error
        finally:
            if connection is not None:
                connection.close()

    def read_index(self) -> dict[str, Any] | None:
        """Read the small active pointer and stop on an unrecoverable index."""
        path: Path = self.store.directory / "regular-index.json"
        if not path.exists() and path.with_suffix(".backup.json").exists():
            raise SaveError(
                "Regular-game index is missing; restore its retained backup before launch."
            )
        index: dict[str, Any] | None = self.store.read("regular-index.json")
        if "regular-index.json" in self.store.blocked:
            raise SaveError("Regular-game index needs recovery; files were preserved.")
        if index is not None:
            active: Any = index.get("active")
            if index.get("migration_complete") is not True or "active" not in index:
                raise SaveError("Invalid regular-game index; restore a backup before launch.")
            if active is not None:
                if (
                    not isinstance(active, dict)
                    or active.get("level") not in LEVELS
                    or not isinstance(active.get("id"), str)
                    or not active.get("id")
                ):
                    raise SaveError("Invalid active regular-game pointer; data was preserved.")
                replay_id: Any = active.get("replay_id")
                if replay_id is None:
                    if type(active.get("cycle")) is not int or active["cycle"] < 1:
                        raise SaveError("Invalid active regular-game pointer; data was preserved.")
                elif (
                    not isinstance(replay_id, str)
                    or len(replay_id) != 32
                    or any(character not in "0123456789abcdef" for character in replay_id)
                ):
                    raise SaveError("Invalid active replay pointer; data was preserved.")
        return index

    def write_index(self, level: str, identifier: str, cycle: int) -> None:
        """Publish the active pointer only after its game transaction commits."""
        self.store.write(
            "regular-index.json",
            {
                "migration_complete": True,
                "display_daily_date": None,
                "active": {"level": level, "id": identifier, "cycle": cycle},
            },
        )

    def write_replay_index(self, game: Game) -> None:
        """Publish a replay pointer after its initial state is committed."""
        self.store.write(
            "regular-index.json",
            {
                "migration_complete": True,
                "display_daily_date": None,
                "active": {
                    "level": game.puzzle.level,
                    "id": game.puzzle.identifier,
                    "replay_id": game.attempt_id,
                },
            },
        )

    def migrate(self) -> None:
        """Validate first, import idempotently per difficulty, then publish the marker."""
        index: dict[str, Any] | None = self.read_index()
        if index and index.get("migration_complete") is True:
            return
        primary: Path = self.store.directory / "game.json"
        backup: Path = self.store.directory / "game.backup.json"
        if not primary.exists() and not backup.exists():
            self.store.write("regular-index.json", {"migration_complete": True, "active": None})
            return
        errors: list[str] = []
        for path in (primary, backup):
            try:
                data: dict[str, Any] = json.loads(path.read_text())
                current, history = self.validate_legacy(data)
            except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                errors.append(f"{path.name}: {error}")
                continue
            if path == backup:
                self.store.warnings.append(
                    "Recovered regular save from game.backup.json. " + "; ".join(errors)
                )
            self.import_legacy(current, history)
            self.write_index(current.puzzle.level, current.puzzle.identifier, 1)
            self.store.warnings.append("Regular saves migrated to SQLite; original JSON retained.")
            return
        raise SaveError("Cannot migrate regular saves; originals preserved. " + "; ".join(errors))

    def validate_legacy(self, data: dict[str, Any]) -> tuple[Game, dict[str, set[str]]]:
        """Resolve all legacy IDs before changing any player database."""
        if data.get("version") != 1:
            raise ValueError("Unsupported legacy save version")
        puzzle: Puzzle | None = self.catalog.find(data["puzzle_id"])
        if puzzle is None:
            raise SaveError(f"Missing active puzzle ID: {data['puzzle_id']}")
        current: Game = game_from_data(data, puzzle)
        played: Any = data.get("played", {})
        if not isinstance(played, dict):
            raise ValueError("Invalid played history")
        history: dict[str, set[str]] = {level: set() for level in LEVELS}
        missing: list[str] = []
        for identifiers in played.values():
            if not isinstance(identifiers, list):
                raise ValueError("Invalid played IDs")
            for identifier in identifiers:
                if not isinstance(identifier, str):
                    raise ValueError("Invalid played ID")
                entry: Puzzle | None = self.catalog.find(identifier)
                if entry is None:
                    missing.append(identifier)
                else:
                    history[entry.level].add(identifier)
        if missing:
            raise SaveError(f"Missing {len(missing)} played IDs: {', '.join(missing[:20])}")
        history[current.puzzle.level].add(current.puzzle.identifier)
        return current, history

    def import_legacy(self, current: Game, history: dict[str, set[str]]) -> None:
        """Use insert-only history and state-if-absent so interrupted imports can retry."""
        for level in LEVELS:
            with self.transaction(level) as connection:
                connection.executemany(
                    "INSERT OR IGNORE INTO games(id,cycle,status) VALUES (?,1,'unknown')",
                    ((identifier,) for identifier in history[level]),
                )
                if level == current.puzzle.level:
                    connection.execute(
                        "UPDATE games SET status=?,state=? "
                        "WHERE id=? AND cycle=1 AND state IS NULL",
                        (
                            "completed" if current.complete else "started",
                            json.dumps(game_data(current), allow_nan=False),
                            current.puzzle.identifier,
                        ),
                    )
                # A retry rebuilds the sparse pool from the imported IDs, without changing state.
                connection.execute("DELETE FROM rotation")
                connection.execute("DELETE FROM swaps")

    @staticmethod
    def remove_position(connection: sqlite3.Connection, position: int, remaining: int) -> int:
        """Pop a sparse Fisher-Yates position in indexed constant-size database work."""
        row: Any = connection.execute(
            "SELECT ordinal FROM swaps WHERE position=?", (position,)
        ).fetchone()
        ordinal: int = int(row[0]) if row else position
        last: Any = connection.execute(
            "SELECT ordinal FROM swaps WHERE position=?", (remaining,)
        ).fetchone()
        last_ordinal: int = int(last[0]) if last else remaining
        connection.execute("DELETE FROM swaps WHERE position IN (?,?)", (position, remaining))
        if position != remaining and last_ordinal != position:
            connection.execute("INSERT INTO swaps VALUES (?,?)", (position, last_ordinal))
        connection.execute("UPDATE rotation SET remaining=? WHERE singleton=1", (remaining - 1,))
        return ordinal

    def rotation(self, connection: sqlite3.Connection, level: str) -> tuple[int, int]:
        """Initialize or reconcile the sparse pool once per catalog generation."""
        row: Any = connection.execute(
            "SELECT cycle,remaining,generation FROM rotation WHERE singleton=1"
        ).fetchone()
        if row and row[2] == self.catalog.generation:
            return int(row[0]), int(row[1])
        group: DifficultyCatalog = self.catalog[level]
        cycle: int = int(
            connection.execute("SELECT coalesce(max(cycle),1) FROM games").fetchone()[0]
        )
        remaining: int = len(group)
        connection.execute("DELETE FROM swaps")
        connection.execute(
            "INSERT OR REPLACE INTO rotation VALUES (1,?,?,?)",
            (cycle, remaining, self.catalog.generation),
        )
        for (identifier,) in connection.execute("SELECT id FROM games WHERE cycle=?", (cycle,)):
            ordinal: int | None = group.ordinal(identifier)
            if ordinal is None:
                raise SaveError(f"Catalog no longer contains previously selected ID {identifier}")
            mapped: Any = connection.execute(
                "SELECT position FROM swaps WHERE ordinal=?", (ordinal,)
            ).fetchone()
            position: int = int(mapped[0]) if mapped else ordinal
            self.remove_position(connection, position, remaining)
            remaining -= 1
        return cycle, remaining

    def start_game(self, level: str) -> Game:
        """Select and save one unplayed puzzle atomically, retaining every earlier attempt."""
        return self.select_game(level, regular=True)

    def remaining_games(self, level: str) -> int:
        """Count unused slots in the current rotation without selecting another puzzle."""
        with self.transaction(level) as connection:
            _, remaining = self.rotation(connection, level)
            return remaining

    def select_game(self, level: str, *, regular: bool = False) -> Game:
        """Use the shared unplayed rotation for a regular or daily game."""
        with self.transaction(level) as connection:
            cycle, remaining = self.rotation(connection, level)
            if remaining == 0:
                cycle += 1
                remaining = len(self.catalog[level])
                connection.execute("DELETE FROM swaps")
                connection.execute("UPDATE rotation SET cycle=?,remaining=?", (cycle, remaining))
            position: int = random.SystemRandom().randint(1, remaining)
            ordinal: int = self.remove_position(connection, position, remaining)
            game: Game = Game(self.catalog[level].by_ordinal(ordinal))
            timestamp: str = now()
            connection.execute(
                "INSERT INTO games VALUES (?,?,'started',?,?,NULL,?)",
                (
                    game.puzzle.identifier,
                    cycle,
                    timestamp,
                    timestamp,
                    json.dumps(game_data(game), allow_nan=False),
                ),
            )
        if regular:
            self.write_index(level, game.puzzle.identifier, cycle)
        return game

    def start_replay(self, identifier: str, *, activate: bool = True) -> Game:
        """Start the exact catalog puzzle as a separate regular attempt."""
        puzzle: Puzzle | None = self.catalog.find(identifier)
        if puzzle is None:
            raise SaveError(f"Puzzle {identifier} is no longer in the catalog")
        game: Game = Game(puzzle)
        timestamp: str = now()
        with self.transaction(puzzle.level) as connection:
            connection.execute(
                "INSERT INTO replays VALUES (?,?, 'started',?,?,NULL,?)",
                (
                    game.attempt_id,
                    identifier,
                    timestamp,
                    timestamp,
                    json.dumps(game_data(game), allow_nan=False),
                ),
            )
        if activate:
            self.write_replay_index(game)
        return game

    def has_played(self, puzzle: Puzzle) -> bool:
        """Include started, completed, replayed, daily, and migrated catalog selections."""
        if not (self.store.directory / "players" / level_filename(puzzle.level)).exists():
            return False
        with self.transaction(puzzle.level) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM games WHERE id=? UNION ALL "
                    "SELECT 1 FROM replays WHERE id=? LIMIT 1",
                    (puzzle.identifier, puzzle.identifier),
                ).fetchone()
                is not None
            )

    def discard_replay(self, game: Game) -> None:
        """Remove an unpublished fresh attempt after History or pointer publication fails."""
        with self.transaction(game.puzzle.level) as connection:
            connection.execute("DELETE FROM replays WHERE attempt_id=?", (game.attempt_id,))

    def load_game(self) -> Game | None:
        """Migrate once and resume the indexed active attempt, never scanning history."""
        self.migrate()
        index: dict[str, Any] = self.read_index() or {}
        active: Any = index.get("active")
        if active is None:
            return None
        from sudoku.imported import is_imported

        if is_imported(active["id"]):
            game: Game = self.store.imported.load(active["id"], active.get("replay_id", ""))
            if game.puzzle.level != active["level"]:
                raise SaveError("Imported difficulty does not match the active pointer")
            return game
        try:
            puzzle: Puzzle | None = self.catalog[active["level"]].find(active["id"])
            if puzzle is None:
                raise ValueError(f"Missing active puzzle {active['id']}")
            with self.transaction(puzzle.level) as connection:
                if "replay_id" in active:
                    row: Any = connection.execute(
                        "SELECT state FROM replays WHERE attempt_id=? AND id=?",
                        (active["replay_id"], puzzle.identifier),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT state FROM games WHERE id=? AND cycle=?",
                        (puzzle.identifier, active["cycle"]),
                    ).fetchone()
            if not row or row[0] is None:
                raise ValueError("Active game state is missing")
            return game_from_data(json.loads(row[0]), puzzle)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            raise SaveError(f"Cannot resume regular game; data preserved: {error}") from error

    def save_game(self, game: Game) -> None:
        """Update only the active regular attempt, retaining other games and timestamps."""
        index: dict[str, Any] = self.read_index() or {}
        active: Any = index.get("active")
        if (
            not active
            or active["id"] != game.puzzle.identifier
            or active["level"] != game.puzzle.level
        ):
            raise SaveError("Active regular-game pointer does not match the game")
        payload: str = json.dumps(game_data(game), allow_nan=False)
        game_from_data(json.loads(payload), game.puzzle)
        timestamp: str = now()
        with self.transaction(game.puzzle.level) as connection:
            if "replay_id" in active:
                cursor: sqlite3.Cursor = connection.execute(
                    "UPDATE replays SET state=?,status=?,last_played_at=?,"
                    "completed_at=CASE WHEN ? AND status!='completed' "
                    "THEN coalesce(completed_at,?) ELSE completed_at END "
                    "WHERE attempt_id=? AND id=?",
                    (
                        payload,
                        "completed" if game.complete else "started",
                        timestamp,
                        game.complete,
                        timestamp,
                        active["replay_id"],
                        game.puzzle.identifier,
                    ),
                )
                if cursor.rowcount != 1:
                    raise SaveError("Active replay record is missing")
                return
            cursor = connection.execute(
                "UPDATE games SET state=?,status=?,last_played_at=?,"
                "completed_at=CASE WHEN ? AND status!='completed' "
                "THEN coalesce(completed_at,?) ELSE completed_at END "
                "WHERE id=? AND cycle=?",
                (
                    payload,
                    "completed" if game.complete else "started",
                    timestamp,
                    game.complete,
                    timestamp,
                    game.puzzle.identifier,
                    active["cycle"],
                ),
            )
            if cursor.rowcount != 1:
                raise SaveError("Active regular-game record is missing")
