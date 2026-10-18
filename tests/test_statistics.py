# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Weighted ended-attempt summaries, import filtering, and rotation availability."""

from dataclasses import replace
from pathlib import Path

import pytest

from sudoku.catalog import Catalog, load_catalog
from sudoku.history import HistoryStore
from sudoku.model import LEVELS, Game
from sudoku.statistics import StatisticsRow, load_statistics
from sudoku.statistics_ui import statistic_text
from sudoku.storage import SaveError, Store


@pytest.fixture
def recorded_history(tmp_path: Path, game: Game) -> HistoryStore:
    """Record unequal level populations, repeated IDs, imports, and all outcomes."""
    history: HistoryStore = HistoryStore(tmp_path / "history.sqlite3")
    records: tuple[tuple[str, str, str, int, int, int, int], ...] = (
        ("Easy", "regular", "Completed", 60, 2, 1, 3),
        ("Easy", "regular", "Restarted", 120, 4, 0, 1),
        ("Easy", "daily", "Abandoned", 180, 0, 2, 2),
        ("Hard", "hard", "Completed", 600, 10, 4, 8),
        ("Easy", "IMP-000001", "Completed", 300, 6, 3, 4),
        ("Hard", "IMP-000002", "Abandoned", 900, 2, 2, 6),
    )
    for level, identifier, status, seconds, hints, reveals, incorrect in records:
        attempt: Game = Game(replace(game.puzzle, identifier=identifier, level=level))
        attempt.elapsed = seconds
        attempt.viewed_hint_stages = {str(index) for index in range(hints)}
        attempt.revealed_cells = set(range(reveals))
        attempt.incorrect_entries = {(index, 9) for index in range(incorrect)}
        history.record_outcome(
            attempt,
            status,
            "2026-10-15T12:00:00+00:00",
            "2026-10-15" if identifier == "daily" else None,
        )
    return history


def test_summaries_count_attempts_and_weight_every_total_average(
    tmp_path: Path, recorded_history: HistoryStore
) -> None:
    """Count repeated and daily attempts and divide total sums by total games."""
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    assert store.players is not None
    rows: list[StatisticsRow] = load_statistics(
        recorded_history, store.players, include_imported=False
    )
    assert [row.level for row in rows] == [*LEVELS, "Total"]
    easy: StatisticsRow = rows[0]
    assert easy.games_played == 3
    assert easy.average(easy.elapsed_seconds) == 120
    assert easy.average(easy.hints) == 2
    assert easy.average(easy.reveals) == 1
    assert easy.average(easy.incorrect) == 2
    assert easy.average(easy.restarts) == pytest.approx(1 / 3)
    assert easy.average(easy.abandons) == pytest.approx(1 / 3)
    total: StatisticsRow = rows[-1]
    assert total.games_played == 4
    assert total.average(total.elapsed_seconds) == 240
    assert total.average(total.hints) == 4
    assert total.average(total.reveals) == 1.75
    assert total.average(total.incorrect) == 3.5
    assert total.average(total.restarts) == 0.25
    assert total.average(total.abandons) == 0.25
    assert total.remaining_games == sum(len(store.players.catalog[level]) for level in LEVELS)


def test_import_filter_changes_all_measurements_but_not_availability(
    tmp_path: Path, recorded_history: HistoryStore
) -> None:
    """Apply the imported-ID filter to counts, sums, and total denominators together."""
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    assert store.players is not None
    included: list[StatisticsRow] = load_statistics(recorded_history, store.players)
    excluded: list[StatisticsRow] = load_statistics(
        recorded_history, store.players, include_imported=False
    )
    assert [row.remaining_games for row in included] == [row.remaining_games for row in excluded]
    assert included[0].games_played == 4 and included[2].games_played == 2
    total: StatisticsRow = included[-1]
    assert total.games_played == 6
    assert total.average(total.elapsed_seconds) == 360
    assert total.average(total.hints) == 4
    assert total.average(total.reveals) == 2
    assert total.average(total.incorrect) == 4
    assert total.average(total.restarts) == pytest.approx(1 / 6)
    assert total.average(total.abandons) == pytest.approx(2 / 6)
    assert recorded_history.count() == 6


def test_empty_history_has_all_levels_and_undefined_averages(tmp_path: Path) -> None:
    """Show remaining puzzles even when no ended attempt exists for any difficulty."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    assert store.players is not None
    rows: list[StatisticsRow] = load_statistics(
        HistoryStore(tmp_path / "history.sqlite3"), store.players
    )
    for row in rows:
        assert row.games_played == 0
        assert statistic_text(row, "games_played") == "0"
        for key in ("elapsed_seconds", "hints", "reveals", "incorrect", "restarts", "abandons"):
            assert statistic_text(row, key) == "—"
    assert rows[0].remaining_games == len(catalog["Easy"])
    assert rows[-1].remaining_games == sum(len(catalog[level]) for level in LEVELS)


def test_statistics_reads_do_not_consume_regular_daily_or_replay_slots(tmp_path: Path) -> None:
    """Read the actual shared rotation repeatedly without changing selection or progress."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    regular: Game = store.start_game("Easy")
    store.start_daily_game("2026-10-15", "Easy")
    store.start_replay(regular.puzzle.identifier)
    assert store.players is not None
    before_index: bytes = (tmp_path / "regular-index.json").read_bytes()
    with store.players.transaction("Easy") as connection:
        before_rotation: list[tuple[object, ...]] = connection.execute(
            "SELECT * FROM rotation"
        ).fetchall()
        before_swaps: list[tuple[object, ...]] = connection.execute(
            "SELECT * FROM swaps ORDER BY position"
        ).fetchall()
    for _ in range(2):
        rows: list[StatisticsRow] = load_statistics(
            HistoryStore(tmp_path / "history.sqlite3"), store.players
        )
        assert rows[0].games_played == 0
        assert rows[0].remaining_games == len(catalog["Easy"]) - 2
    assert (tmp_path / "regular-index.json").read_bytes() == before_index
    with store.players.transaction("Easy") as connection:
        assert connection.execute("SELECT * FROM rotation").fetchall() == before_rotation
        assert (
            connection.execute("SELECT * FROM swaps ORDER BY position").fetchall() == before_swaps
        )


def test_remaining_games_handles_exhaustion_and_catalog_reconciliation(tmp_path: Path) -> None:
    """Keep exhausted pools at zero and reconcile a generation without consuming a slot."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    assert store.players is not None
    for _ in range(len(catalog["Easy"])):
        store.start_game("Easy")
    assert store.players.remaining_games("Easy") == 0
    catalog.generation = "statistics-test-generation"
    assert store.players.remaining_games("Easy") == 0
    store.start_game("Easy")
    assert store.players.remaining_games("Easy") == len(catalog["Easy"]) - 1


@pytest.mark.parametrize(
    ("row", "key", "expected"),
    [
        (StatisticsRow("Easy", 2, 119), "elapsed_seconds", "1:00"),
        (StatisticsRow("Easy", 1, 3661), "elapsed_seconds", "1:01:01"),
        (StatisticsRow("Easy", 3, hints=1), "hints", "0.33"),
        (StatisticsRow("Total", remaining_games=1234567), "remaining_games", "1,234,567"),
    ],
)
def test_statistic_text_formats_averages_and_large_counts(
    row: StatisticsRow, key: str, expected: str
) -> None:
    """Round average durations and retain readable decimal averages and catalog counts."""
    assert statistic_text(row, key) == expected


def test_statistics_database_errors_are_reported(tmp_path: Path) -> None:
    """Report damaged history rather than replacing it with a plausible zero summary."""
    path: Path = tmp_path / "history.sqlite3"
    path.write_bytes(b"invalid database")
    store: Store = Store(tmp_path)
    store.load_game(load_catalog())
    assert store.players is not None
    with pytest.raises(SaveError, match="history"):
        load_statistics(HistoryStore(path), store.players)
    assert path.read_bytes() == b"invalid database"
