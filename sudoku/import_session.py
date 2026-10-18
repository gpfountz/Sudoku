# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Stage replacement attempts and compensate unsuccessful History or pointer publication."""

from collections.abc import Callable
from datetime import UTC, datetime

from sudoku.history import HistoryStore
from sudoku.imported import is_imported
from sudoku.model import Game
from sudoku.storage import SaveError, Store


def replace_attempt(
    store: Store,
    history: HistoryStore,
    previous: Game,
    daily_date: str | None,
    prepare: Callable[[], Game],
    outcome: str = "Abandoned",
) -> Game:
    """Publish a fresh saved attempt only after its predecessor's outcome is recorded."""
    replacement: Game = prepare()
    abandoned: bool = False
    try:
        if not previous.complete:
            abandoned = history.record_outcome(
                previous, outcome, datetime.now(UTC).isoformat(), daily_date
            )
        store.activate_replay(replacement)
    except SaveError:
        if abandoned:
            history.remove_outcome(previous.attempt_id, outcome)
        if is_imported(replacement.puzzle.identifier):
            store.imported.discard(replacement)
        elif store.players is not None:
            store.players.discard_replay(replacement)
        raise
    return replacement
