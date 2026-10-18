# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""SQLite migration, state retention, isolation, transactions, and selection cycles."""

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sudoku.catalog import Catalog, load_catalog, read_database
from sudoku.model import LEVELS, Game, Preferences, Puzzle
from sudoku.player import PlayerStore
from sudoku.storage import SaveError, Store, game_data, game_from_data


@pytest.mark.parametrize("level", LEVELS)
def test_catalog_matches_exact_givens_in_every_band(isolated_catalog: Catalog, level: str) -> None:
    """Find identical clues across all difficulties without relying on puzzle ID format."""
    puzzle: Puzzle = isolated_catalog[level][-1]
    assert isolated_catalog.find_givens(puzzle.givens) == puzzle
    changed: list[int] = list(puzzle.givens)
    empty: int = changed.index(0)
    changed[empty] = puzzle.solution[empty]
    assert isolated_catalog.find_givens(tuple(changed)) is None


def test_catalog_match_scan_can_be_cancelled(isolated_catalog: Catalog) -> None:
    """Stop cancelled review work before reading catalog rows, including cached matches."""
    with pytest.raises(ValueError, match="cancelled"):
        isolated_catalog.find_givens(isolated_catalog["Easy"][0].givens, lambda: True)


@pytest.mark.parametrize("source", ["regular", "daily", "replay", "legacy"])
def test_catalog_match_prior_play_includes_all_saved_sources(
    tmp_path: Path, isolated_catalog: Catalog, source: str
) -> None:
    """Recognize old and unfinished play without requiring a completion in History."""
    store: Store = Store(tmp_path)
    store.load_game(isolated_catalog)
    assert store.players is not None
    puzzle: Puzzle = isolated_catalog["Extreme"][0]
    assert not store.players.has_played(puzzle)
    if source == "regular":
        puzzle = store.start_game("Extreme").puzzle
    elif source == "daily":
        puzzle = store.start_daily_game("2026-10-15", "Extreme").puzzle
    elif source == "replay":
        store.start_replay(puzzle.identifier)
    else:
        with store.players.transaction(puzzle.level) as connection:
            connection.execute(
                "INSERT INTO games(id,cycle,status) VALUES (?,1,'unknown')", (puzzle.identifier,)
            )
    assert store.players.has_played(puzzle)
    assert not store.players.has_played(isolated_catalog["Hard"][0])


def legacy_save(path: Path, game: Game, played: dict[str, list[str]]) -> None:
    """Write an isolated old-format save for migration and recovery tests."""
    path.write_text(json.dumps({"version": 1, **game_data(game), "played": played}))


def test_save_roundtrip_includes_history_and_preferences(tmp_path: Path) -> None:
    """Resume the full board, redo history, timer and input tools from SQLite."""
    store: Store = Store(tmp_path)
    catalog: Catalog = load_catalog()
    assert store.load_game(catalog) is None
    game: Game = store.start_game("Easy")
    empty: int = next(i for i, value in enumerate(game.values) if not value)
    game.mark(empty, game.puzzle.solution[empty])
    game.set_value(empty, game.puzzle.solution[empty])
    game.undo()
    game.active_color = 6
    game.paint_color(empty)
    game.color_mode = True
    game.elapsed = 123.5
    game.active_digit = 7
    game.note_mode = True
    game.paused = True
    prefs: Preferences = Preferences(
        appearance="Dark", theme="Warm Paper", cleanup_notes=False, window_full_screen=True
    )
    store.save_preferences(prefs)
    store.save_game(game)
    restored: Game | None = Store(tmp_path).load_game(catalog)
    assert restored and restored.snapshot() == game.snapshot()
    assert restored.undo_stack == game.undo_stack and restored.redo_stack == game.redo_stack
    assert restored.elapsed == 123.5 and restored.active_digit == 7 and restored.note_mode
    assert restored.color_mode and restored.active_color == 6
    assert restored.colors[empty] == 6
    assert restored.paused and store.load_preferences() == prefs
    assert not (tmp_path / "game.json").exists()


def test_old_save_without_colors_loads_and_invalid_colors_are_rejected(game: Game) -> None:
    """Older board histories begin uncolored while corrupt new colors fail validation."""
    game.mark(1, 2)
    data: dict[str, Any] = game_data(game)
    for snapshot in (data["board"], *data["undo"], *data["redo"]):
        snapshot.pop("colors")
    data.pop("color_mode")
    data.pop("active_color")
    restored: Game = game_from_data(data, game.puzzle)
    assert restored.colors == [0] * 81
    assert not restored.color_mode and restored.active_color == 1
    data["board"]["colors"] = [0] * 80 + [9]
    with pytest.raises(ValueError, match="Invalid cell colors"):
        game_from_data(data, game.puzzle)


def test_migration_preserves_state_and_unknown_history(tmp_path: Path) -> None:
    """Import matching difficulties without inventing timestamps or historical progress."""
    catalog: Catalog = load_catalog()
    game: Game = Game(catalog["Easy"][0])
    empty: int = next(i for i, value in enumerate(game.values) if not value)
    game.mark(empty, 9)
    game.elapsed = 42
    legacy_save(
        tmp_path / "game.json",
        game,
        {
            "old-label": [game.puzzle.identifier, catalog["Hard"][0].identifier],
        },
    )
    original: bytes = (tmp_path / "game.json").read_bytes()
    store: Store = Store(tmp_path)
    restored: Game | None = store.load_game(catalog)
    assert restored and restored.snapshot() == game.snapshot() and restored.elapsed == 42
    assert store.players is not None
    with store.players.transaction("Hard") as connection:
        assert connection.execute(
            "SELECT status,started_at,last_played_at,completed_at,state FROM games"
        ).fetchone() == ("unknown", None, None, None, None)
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT started_at,completed_at FROM games").fetchone() == (
            None,
            None,
        )
    restored.elapsed = 99
    store.save_game(restored)
    again: Game | None = Store(tmp_path).load_game(catalog)
    assert again and again.elapsed == 99
    assert (tmp_path / "game.json").read_bytes() == original


@pytest.mark.parametrize("damage", ["syntax", "givens", "version", "missing-primary"])
def test_migration_uses_valid_backup(tmp_path: Path, damage: str) -> None:
    """Recover a semantically valid backup without renaming or overwriting either file."""
    catalog: Catalog = load_catalog()
    game: Game = Game(catalog["Easy"][0])
    legacy_save(tmp_path / "game.backup.json", game, {})
    payload: dict[str, Any] = {"version": 1, **game_data(game)}
    if damage == "givens":
        index: int = next(i for i, value in enumerate(game.values) if value)
        payload["board"]["values"][index] = 0
    if damage == "version":
        payload["version"] = 99
    if damage != "missing-primary":
        (tmp_path / "game.json").write_text("bad" if damage == "syntax" else json.dumps(payload))
    before: dict[Path, bytes] = {path: path.read_bytes() for path in tmp_path.glob("game*.json")}
    store: Store = Store(tmp_path)
    assert store.load_game(catalog) is not None
    assert any("backup" in warning for warning in store.warnings)
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("missing", [False, True])
def test_invalid_migration_stops_without_creating_history(tmp_path: Path, missing: bool) -> None:
    """Damaged saves and unresolved IDs remain actionable, never silently dropped."""
    catalog: Catalog = load_catalog()
    if missing:
        legacy_save(tmp_path / "game.json", Game(catalog["Easy"][0]), {"Easy": ["missing-id"]})
    else:
        (tmp_path / "game.json").write_text("broken")
    with pytest.raises(SaveError, match="Missing|Cannot migrate"):
        Store(tmp_path).load_game(catalog)
    assert not (tmp_path / "regular-index.json").exists()
    assert not (tmp_path / "players").exists()


def test_interrupted_migration_retries_without_duplicates(tmp_path: Path) -> None:
    """Retry after some difficulty commits, then repeat after the completion marker."""
    catalog: Catalog = load_catalog()
    legacy_save(
        tmp_path / "game.json",
        Game(catalog["Easy"][0]),
        {
            "Easy": [catalog["Easy"][1].identifier],
            "Hard": [catalog["Hard"][0].identifier],
        },
    )
    original = PlayerStore.transaction
    calls: int = 0

    def interrupted(self: PlayerStore, level: str) -> Any:
        """Inject interruption before a later difficulty transaction begins."""
        nonlocal calls
        calls += 1
        if calls == 3:
            raise SaveError("Interrupted migration")
        return original(self, level)

    with patch.object(PlayerStore, "transaction", interrupted):
        with pytest.raises(SaveError, match="Interrupted"):
            Store(tmp_path).load_game(catalog)
    assert not (tmp_path / "regular-index.json").exists()
    store: Store = Store(tmp_path)
    assert store.load_game(catalog) is not None
    assert store.load_game(catalog) is not None
    assert store.players is not None
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT count(*) FROM games").fetchone()[0] == 2
    choices: list[str] = [store.start_game("Easy").puzzle.identifier for _ in range(10)]
    assert len(set(choices)) == 10
    assert catalog["Easy"][0].identifier not in choices
    assert catalog["Easy"][1].identifier not in choices


def test_cycles_preserve_attempts_and_unfinished_games(tmp_path: Path) -> None:
    """Exhaust a band without repeats, retain attempts, and leave other bands untouched."""
    store: Store = Store(tmp_path)
    catalog: Catalog = load_catalog()
    store.load_game(catalog)
    games: list[Game] = [store.start_game("Easy") for _ in range(len(catalog["Easy"]))]
    assert len({game.puzzle.identifier for game in games}) == len(games)
    store.start_game("Easy")
    assert store.players is not None
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT count(*) FROM games").fetchone()[0] == len(games) + 1
        assert (
            connection.execute("SELECT count(*) FROM games WHERE state IS NOT NULL").fetchone()[0]
            == len(games) + 1
        )
        assert connection.execute("SELECT max(cycle) FROM games").fetchone()[0] == 2
    assert not (tmp_path / "players/hard.sqlite").exists()


def test_completion_and_transaction_rollback(tmp_path: Path) -> None:
    """Completion records known time; a failing transaction leaves prior progress intact."""
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    game: Game = store.start_game("Easy")
    for index, digit in enumerate(game.puzzle.solution):
        if not game.values[index]:
            game.set_value(index, digit)
    store.save_game(game)
    assert store.players is not None
    with store.players.transaction("Easy") as connection:
        row: Any = connection.execute("SELECT status,started_at,completed_at FROM games").fetchone()
        assert row[0] == "completed" and row[1] and row[2]
    with pytest.raises(RuntimeError):
        with store.players.transaction("Easy") as connection:
            connection.execute("DELETE FROM games")
            raise RuntimeError("rollback")
    assert Store(tmp_path).load_game(load_catalog()).complete  # type: ignore[union-attr]


def test_readonly_resources_and_writable_player_files(tmp_path: Path) -> None:
    """Catalog SQL cannot mutate resources, and every player write uses the injected root."""
    catalog: Catalog = load_catalog()
    path: Path = catalog["Easy"].path
    before: bytes = path.read_bytes()
    with read_database(path) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM puzzles")
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    store.start_game("Easy")
    assert (tmp_path / "players/easy.sqlite").is_file()
    assert path.read_bytes() == before


def test_write_failure_is_visible(tmp_path: Path) -> None:
    """Report unwritable player directories instead of returning an unsaved puzzle."""
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    (tmp_path / "players").write_text("obstruction")
    with pytest.raises(SaveError):
        store.start_game("Easy")


def test_selection_insert_failure_restores_pool_and_pointer(tmp_path: Path) -> None:
    """A failed new-game insert rolls back the draw instead of consuming a puzzle."""
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    store.start_game("Easy")
    assert store.players is not None
    pointer: bytes = (tmp_path / "regular-index.json").read_bytes()
    with store.players.transaction("Easy") as connection:
        before: tuple[Any, ...] = connection.execute("SELECT * FROM rotation").fetchone()
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON games "
            "BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END"
        )
    with pytest.raises(SaveError, match="simulated"):
        store.start_game("Easy")
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT * FROM rotation").fetchone() == before
        assert connection.execute("SELECT count(*) FROM games").fetchone()[0] == 1
    assert (tmp_path / "regular-index.json").read_bytes() == pointer


def test_migrated_completion_time_stays_unknown(tmp_path: Path) -> None:
    """Opening a formerly completed JSON game does not invent its completion date."""
    catalog: Catalog = load_catalog()
    game: Game = Game(catalog["Easy"][0])
    for index, digit in enumerate(game.puzzle.solution):
        if not game.values[index]:
            game.set_value(index, digit)
    legacy_save(tmp_path / "game.json", game, {})
    store: Store = Store(tmp_path)
    restored: Game | None = store.load_game(catalog)
    assert restored and restored.complete
    store.save_game(restored)
    assert store.players is not None
    with store.players.transaction("Easy") as connection:
        row: Any = connection.execute("SELECT status,started_at,completed_at FROM games").fetchone()
        assert row == ("completed", None, None)


def test_new_catalog_generation_preserves_cycle(tmp_path: Path) -> None:
    """Reconcile ordinals by stable ID when catalog resources are rebuilt."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    previous: set[str] = {store.start_game("Easy").puzzle.identifier for _ in range(4)}
    catalog.generation = "testrebuiltgeneration"
    upcoming: set[str] = {store.start_game("Easy").puzzle.identifier for _ in range(8)}
    assert len(upcoming) == 8 and not previous & upcoming


def test_verified_eliminations_survive_migration(tmp_path: Path) -> None:
    """Retain solution-safe exclusions along with their undo and redo state."""
    catalog: Catalog = load_catalog()
    game: Game = Game(catalog["Easy"][0])
    index: int = next(i for i, value in enumerate(game.values) if not value)
    digit: int = next(d for d in range(1, 10) if d != game.puzzle.solution[index])
    game.mark(index, digit)
    game.eliminate(((index, digit),))
    legacy_save(tmp_path / "game.json", game, {})
    restored: Game | None = Store(tmp_path).load_game(catalog)
    assert restored and restored.snapshot() == game.snapshot()
    assert restored.undo_stack == game.undo_stack


def test_resume_across_process_restarts(tmp_path: Path) -> None:
    """A second process using the same data directory restores edits and selected cell."""
    import os
    import subprocess
    import sys

    script: str = """
import json
import os
from pathlib import Path
from sudoku.catalog import load_catalog
from sudoku.storage import Store
store = Store(Path(os.environ['SUDOKU_DATA_DIR']))
game = store.load_game(load_catalog())
if game is None:
    game = store.start_game('Medium')
    index = next(i for i, value in enumerate(game.values) if not value)
    game.set_value(index, game.puzzle.solution[index])
    game.selected = index
    game.elapsed = 25.5
    store.save_game(game)
print(json.dumps({'id': game.puzzle.identifier, 'values': game.values,
                  'selected': game.selected, 'elapsed': game.elapsed,
                  'undo': len(game.undo_stack)}))
"""
    environment: dict[str, str] = {**os.environ, "SUDOKU_DATA_DIR": str(tmp_path)}
    first: str = subprocess.check_output([sys.executable, "-c", script], env=environment, text=True)
    second: str = subprocess.check_output(
        [sys.executable, "-c", script], env=environment, text=True
    )
    assert json.loads(first) == json.loads(second)
    assert json.loads(second)["undo"] == 1


def test_catalog_readonly_uri_does_not_depend_on_sqlite_defaults(tmp_path: Path) -> None:
    """Open read-only resources even when SQLite's global URI default is disabled."""
    import subprocess
    import sys

    path: Path = tmp_path / "catalog space # é.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=1")
        connection.execute("CREATE TABLE marker(value INTEGER)")
        connection.execute("INSERT INTO marker VALUES (42)")
    before: bytes = path.read_bytes()
    script: str = """
import ctypes
import sqlite3
import _sqlite3
import sys
from pathlib import Path
from sudoku.catalog import read_database

# Change the global default only inside this fresh subprocess, with no live connections.
library = ctypes.CDLL(_sqlite3.__file__)
assert library.sqlite3_shutdown() == 0
assert library.sqlite3_config(17, 0) == 0  # SQLITE_CONFIG_URI = 17
assert library.sqlite3_initialize() == 0
with read_database(Path(sys.argv[1])) as connection:
    assert connection.execute('SELECT value FROM marker').fetchone() == (42,)
    connection.execute('PRAGMA query_only=OFF')
    try:
        connection.execute('INSERT INTO marker VALUES (99)')
    except sqlite3.OperationalError as error:
        assert 'readonly' in str(error)
    else:
        raise AssertionError('Catalog connection was not opened read-only')
"""
    subprocess.run([sys.executable, "-c", script, str(path)], check=True)
    assert path.read_bytes() == before
