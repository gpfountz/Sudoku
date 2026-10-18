# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Versioned atomic local persistence with recovery and strict save validation."""

import json
import math
import os
import shutil
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sudoku.model import Game, Preferences, Puzzle, Snapshot

if TYPE_CHECKING:
    from sudoku.catalog import Catalog
    from sudoku.imported import ImportedStore
    from sudoku.player import PlayerStore


class SaveError(Exception):
    """Describe an unreadable or unwritable local save without destroying it."""


def snapshot_data(snapshot: Snapshot) -> dict[str, Any]:
    """Convert one immutable board snapshot into JSON-compatible data."""
    return {
        "values": list(snapshot.values),
        "notes": [sorted(n) for n in snapshot.notes],
        "excluded": [sorted(n) for n in snapshot.excluded],
        "colors": list(snapshot.colors),
    }


def parse_snapshot(data: dict[str, Any], puzzle: Puzzle) -> Snapshot:
    """Validate persisted content, including immutable givens and sound exclusions."""
    values: list[int] = data["values"]
    if len(values) != 81 or any(type(v) is not int or not 0 <= v <= 9 for v in values):
        raise ValueError("Invalid board values")
    if any(given and values[i] != given for i, given in enumerate(puzzle.givens)):
        raise ValueError("Saved game modifies givens")
    groups: list[tuple[frozenset[int], ...]] = []
    for key in ("notes", "excluded"):
        entries: list[list[int]] = data[key]
        if len(entries) != 81 or any(
            type(d) is not int or not 1 <= d <= 9 for entry in entries for d in entry
        ):
            raise ValueError("Invalid candidates")
        if any(values[i] and entry for i, entry in enumerate(entries)):
            raise ValueError("Filled cell contains candidates")
        if key == "excluded" and any(
            puzzle.solution[i] in entry for i, entry in enumerate(entries)
        ):
            raise ValueError("Saved exclusion removes a solution digit")
        groups.append(tuple(frozenset(entry) for entry in entries))
    colors: Any = data.get("colors", [0] * 81)
    if (
        not isinstance(colors, list)
        or len(colors) != 81
        or any(type(color) is not int or not 0 <= color <= 8 for color in colors)
    ):
        raise ValueError("Invalid cell colors")
    return Snapshot(tuple(values), groups[0], groups[1], tuple(colors))


def game_data(game: Game) -> dict[str, Any]:
    """Convert a complete game into validated persistence fields."""
    return {
        "puzzle_id": game.puzzle.identifier,
        "board": snapshot_data(game.snapshot()),
        "undo": [snapshot_data(snapshot) for snapshot in game.undo_stack],
        "redo": [snapshot_data(snapshot) for snapshot in game.redo_stack],
        "elapsed": game.elapsed,
        "selected": game.selected,
        "active_digit": game.active_digit,
        "note_mode": game.note_mode,
        "color_mode": game.color_mode,
        "active_color": game.active_color,
        "paused": game.paused,
        "attempt_id": game.attempt_id,
        "viewed_hint_stages": sorted(game.viewed_hint_stages),
        "revealed_cells": sorted(game.revealed_cells),
        "incorrect_entries": [list(entry) for entry in sorted(game.incorrect_entries)],
        "solved_at": game.solved_at,
    }


def game_from_data(data: dict[str, Any], puzzle: Puzzle) -> Game:
    """Restore one game against the exact immutable puzzle supplied by its cache."""
    if data.get("puzzle_id") != puzzle.identifier:
        raise ValueError("Saved game references the wrong puzzle")
    game: Game = Game(puzzle)
    game.restore(parse_snapshot(data["board"], puzzle))
    game.undo_stack = [parse_snapshot(snapshot, puzzle) for snapshot in data["undo"][-200:]]
    game.redo_stack = [parse_snapshot(snapshot, puzzle) for snapshot in data["redo"][-200:]]
    game.elapsed = float(data["elapsed"])
    if not math.isfinite(game.elapsed) or game.elapsed < 0:
        raise ValueError("Invalid timer")
    game.selected = int(data["selected"])
    game.active_digit = int(data["active_digit"])
    if not 0 <= game.selected < 81 or not 1 <= game.active_digit <= 9:
        raise ValueError("Invalid selection")
    game.note_mode = bool(data["note_mode"])
    game.color_mode = bool(data.get("color_mode", False))
    game.active_color = data.get("active_color", 1)
    if type(game.active_color) is not int or not 1 <= game.active_color <= 9:
        raise ValueError("Invalid active color")
    game.paused = bool(data.get("paused", False))
    attempt_id: Any = data.get("attempt_id", game.attempt_id)
    if (
        not isinstance(attempt_id, str)
        or len(attempt_id) != 32
        or any(character not in "0123456789abcdef" for character in attempt_id)
    ):
        raise ValueError("Invalid game attempt ID")
    game.attempt_id = attempt_id
    viewed: Any = data.get("viewed_hint_stages", [])
    if (
        not isinstance(viewed, list)
        or len(viewed) > 10000
        or any(
            not isinstance(key, str)
            or len(key) != 64
            or any(character not in "0123456789abcdef" for character in key)
            for key in viewed
        )
    ):
        raise ValueError("Invalid viewed hint stages")
    game.viewed_hint_stages = set(viewed)
    revealed: Any = data.get("revealed_cells", [])
    if not isinstance(revealed, list) or any(
        type(index) is not int or not 0 <= index < 81 for index in revealed
    ):
        raise ValueError("Invalid revealed cells")
    game.revealed_cells = set(revealed)
    incorrect: Any = data.get("incorrect_entries", [])
    if not isinstance(incorrect, list) or any(
        not isinstance(entry, list)
        or len(entry) != 2
        or type(entry[0]) is not int
        or type(entry[1]) is not int
        or not 0 <= entry[0] < 81
        or not 1 <= entry[1] <= 9
        or entry[1] == puzzle.solution[entry[0]]
        for entry in incorrect
    ):
        raise ValueError("Invalid incorrect answers")
    game.incorrect_entries = {(index, digit) for index, digit in incorrect}
    solved_at: Any = data.get("solved_at")
    if solved_at is not None:
        try:
            if not isinstance(solved_at, str) or datetime.fromisoformat(solved_at).tzinfo is None:
                raise ValueError("Missing timezone")
        except ValueError as error:
            raise ValueError("Invalid solved timestamp") from error
    game.solved_at = solved_at
    return game


class Store:
    """Persist app data in an injectable directory, retaining last-good copies."""

    def __init__(self, directory: Path | None = None) -> None:
        """Use Application Support normally or an isolated path for testing."""
        self.directory: Path = directory or Path.home() / "Library/Application Support/Sudoku"
        self.blocked: set[str] = set()
        self.warnings: list[str] = []
        self.players: PlayerStore | None = None
        self._imported: ImportedStore | None = None

    @property
    def imported(self) -> ImportedStore:
        """Open the imported backend lazily, avoiding module initialization cycles."""
        from sudoku.imported import ImportedStore

        if self._imported is None:
            self._imported = ImportedStore(self.directory)
        return self._imported

    def read(self, name: str) -> dict[str, Any] | None:
        """Read a supported JSON document or recover its backup without overwriting damage."""
        path: Path = self.directory / name
        if not path.exists():
            return None
        for candidate in (path, path.with_suffix(".backup.json")):
            try:
                data: Any = json.loads(candidate.read_text())
                if not isinstance(data, dict) or data.get("version") != 1:
                    raise ValueError("Unsupported save version")
                if candidate != path:
                    self.warnings.append(
                        f"Recovered {name} from its backup. The unreadable file was preserved."
                    )
                    self.blocked.add(name)
                return data
            except (OSError, ValueError, TypeError):
                continue
        self.blocked.add(name)
        self.warnings.append(
            f"Could not read {name}. It has been preserved; "
            "automatic saving to that file is disabled."
        )
        return None

    def write(self, name: str, data: dict[str, Any]) -> None:
        """Write atomically and retain a previous version, protecting damaged originals."""
        if name in self.blocked:
            raise SaveError(
                f"Saving {name} is paused to preserve an unreadable file. "
                "Use Recover Saving in the Game menu to preserve it under a new name and resume."
            )
        path: Path = self.directory / name
        temporary: Path = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w") as stream:
                json.dump({"version": 1, **data}, stream, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                shutil.copy2(path, path.with_suffix(".backup.json"))
            temporary.replace(path)
        except (OSError, ValueError) as error:
            raise SaveError(f"Could not save {name}: {error}") from error

    def recover(self) -> None:
        """Preserve damaged originals under unique names before enabling new saves."""
        import time

        for name in list(self.blocked):
            path: Path = self.directory / name
            if path.exists():
                path.rename(path.with_name(f"{path.stem}.unreadable-{time.time_ns()}.json"))
            self.blocked.remove(name)

    def load_preferences(self) -> Preferences:
        """Load recognized preferences with defaults for missing settings."""
        data: dict[str, Any] = self.read("preferences.json") or {}
        return Preferences.from_dict(data)

    def save_preferences(self, preferences: Preferences) -> None:
        """Persist preferences independently of puzzle progress."""
        self.write("preferences.json", asdict(preferences))

    def save_game(self, game: Game) -> None:
        """Save regular progress exclusively in the initialized player database."""
        if self.players is None:
            raise SaveError("Regular storage has not been initialized")
        from sudoku.imported import is_imported

        if is_imported(game.puzzle.identifier):
            self.imported.save(game)
            index: dict[str, Any] = self.players.read_index() or {}
            active: dict[str, Any] = index.get("active") or {}
            if active.get("replay_id") != game.attempt_id:
                self.players.write_replay_index(game)
        else:
            self.players.save_game(game)

    def load_game(self, catalog: Catalog) -> Game | None:
        """Initialize SQLite storage and migrate or restore regular progress."""
        from sudoku.player import PlayerStore

        self.players = PlayerStore(self, catalog)
        return self.players.load_game()

    def start_game(self, level: str) -> Game:
        """Persist a newly selected puzzle without replacing earlier unfinished games."""
        if self.players is None:
            raise SaveError("Regular storage has not been initialized")
        return self.players.start_game(level)

    def start_replay(self, identifier: str, *, activate: bool = True) -> Game:
        """Start a fresh regular attempt on an exact previously solved puzzle."""
        if self.players is None:
            raise SaveError("Regular storage has not been initialized")
        from sudoku.imported import is_imported
        from sudoku.puzzle_import import ValidatedImport

        if is_imported(identifier):
            puzzle: Puzzle | None = self.imported.find(identifier)
            if puzzle is None:
                raise SaveError(f"Imported puzzle {identifier} is missing")
            game: Game = self.imported.start(
                ValidatedImport(puzzle.givens, puzzle.solution), puzzle.level
            )
            if activate:
                self.players.write_replay_index(game)
            return game
        return self.players.start_replay(identifier, activate=activate)

    def activate_replay(self, game: Game) -> None:
        """Publish one durable pointer after the staged attempt and History succeed."""
        if self.players is None:
            raise SaveError("Player storage has not been initialized")
        self.players.write_replay_index(game)

    def daily_game_exists(self, day: str) -> bool:
        """Report whether this local date already has an assigned puzzle."""
        return (self.directory / "catalog-daily-games" / f"{day}.json").exists()

    def start_daily_game(self, day: str, level: str) -> Game:
        """Assign one catalog puzzle to a date using the regular selection rotation."""
        if date.fromisoformat(day).isoformat() != day:
            raise SaveError("Invalid daily game date")
        if self.players is None:
            raise SaveError("Player storage has not been initialized")
        if self.daily_game_exists(day):
            raise SaveError("A daily puzzle has already been assigned for this date")
        game: Game = self.players.select_game(level)
        self.save_daily_game(day, game)
        return game

    def save_daily_game(self, day: str, game: Game) -> None:
        """Persist a dated catalog game and its full editable state."""
        if date.fromisoformat(day).isoformat() != day:
            raise SaveError("Invalid daily game date")
        self.write(f"catalog-daily-games/{day}.json", {"date": day, "game": game_data(game)})

    def load_daily_game(self, day: str, catalog: Catalog) -> Game | None:
        """Restore a day's assigned game from its stable catalog puzzle ID."""
        name: str = f"catalog-daily-games/{day}.json"
        data: dict[str, Any] | None = self.read(name)
        if data is None:
            if self.daily_game_exists(day):
                raise SaveError(f"The daily game for {day} is unreadable; its file was preserved")
            return None
        try:
            if data["date"] != day:
                raise ValueError("Daily game date does not match its file")
            game_state: dict[str, Any] = data["game"]
            puzzle: Puzzle | None = catalog.find(game_state["puzzle_id"])
            if puzzle is None:
                raise ValueError("Daily puzzle is missing from the catalog")
            return game_from_data(game_state, puzzle)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            self.blocked.add(name)
            raise SaveError(
                f"The daily game for {day} is invalid; its file was preserved: {error}"
            ) from error

    def save_active_daily_date(self, active_date: str | None) -> None:
        """Remember whether the app was showing a daily game at last save."""
        self.write("catalog-daily-index.json", {"active_date": active_date})
        if self.players is not None:
            index: dict[str, Any] = self.players.read_index() or {}
            if index.get("display_daily_date", object()) != active_date:
                self.write("regular-index.json", {**index, "display_daily_date": active_date})

    def load_active_daily_date(self) -> str | None:
        """Restore the active daily date when its game file is present."""
        data: dict[str, Any] | None = self.read("catalog-daily-index.json")
        if self.players is not None:
            index: dict[str, Any] = self.players.read_index() or {}
            if "display_daily_date" in index:
                data = {"active_date": index["display_daily_date"]}
        if data is None:
            return None
        active_date: Any = data.get("active_date")
        if active_date is None:
            return None
        try:
            if (
                not isinstance(active_date, str)
                or date.fromisoformat(active_date).isoformat() != active_date
            ):
                raise ValueError("Invalid active daily date")
        except ValueError as error:
            raise SaveError("The active daily index is invalid; its file was preserved") from error
        return active_date if self.daily_game_exists(active_date) else None
