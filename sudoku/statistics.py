# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Per-level summaries of ended attempts and the shared puzzle rotation."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace

from sudoku.history import HistoryStore
from sudoku.model import LEVELS
from sudoku.player import PlayerStore
from sudoku.storage import SaveError


@dataclass(frozen=True)
class StatisticsRow:
    """Retain sums so every average, including the total, uses its own game count."""

    level: str
    games_played: int = 0
    elapsed_seconds: float = 0.0
    hints: int = 0
    reveals: int = 0
    incorrect: int = 0
    restarts: int = 0
    abandons: int = 0
    remaining_games: int = 0

    def average(self, total: float) -> float | None:
        """Return a per-attempt average, or no value for an unplayed difficulty."""
        return total / self.games_played if self.games_played else None


def total_row(rows: list[StatisticsRow]) -> StatisticsRow:
    """Sum measurements before averaging so busy levels receive their correct weight."""
    return StatisticsRow(
        level="Total",
        games_played=sum(row.games_played for row in rows),
        elapsed_seconds=sum(row.elapsed_seconds for row in rows),
        hints=sum(row.hints for row in rows),
        reveals=sum(row.reveals for row in rows),
        incorrect=sum(row.incorrect for row in rows),
        restarts=sum(row.restarts for row in rows),
        abandons=sum(row.abandons for row in rows),
        remaining_games=sum(row.remaining_games for row in rows),
    )


def load_statistics(
    history: HistoryStore, players: PlayerStore, *, include_imported: bool = True
) -> list[StatisticsRow]:
    """Aggregate History in SQLite and add every difficulty plus a weighted total."""
    try:
        with closing(history.connect()) as connection:
            records: list[tuple[str, int, float, int, int, int, int, int]] = connection.execute(
                "SELECT level,count(*),sum(elapsed_seconds),sum(hint_count),"
                "sum(reveal_count),sum(incorrect_count),sum(status='Restarted'),"
                "sum(status='Abandoned') FROM game_attempts "
                "WHERE (? OR substr(puzzle_id,1,4) != 'IMP-') GROUP BY level",
                (include_imported,),
            ).fetchall()
    except sqlite3.Error as error:
        raise SaveError(f"Could not load statistics: {error}") from error
    summaries: dict[str, StatisticsRow] = {record[0]: StatisticsRow(*record) for record in records}
    rows: list[StatisticsRow] = []
    for level in LEVELS:
        summary: StatisticsRow = summaries.get(level, StatisticsRow(level))
        rows.append(replace(summary, remaining_games=players.remaining_games(level)))
    return [*rows, total_row(rows)]
