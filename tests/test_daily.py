# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Local daily selection, date assignment, and progress persistence."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sudoku.app import AppController
from sudoku.catalog import Catalog, load_catalog
from sudoku.daily import choose_daily_level
from sudoku.history import HistoryStore
from sudoku.model import LEVELS, Game, Preferences
from sudoku.storage import SaveError, Store, game_data


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [(0, "Easy"), (1, "Medium"), (2, "Medium")],
)
def test_level_tickets_match_catalog_counts(
    monkeypatch: pytest.MonkeyPatch, ticket: int, expected: str
) -> None:
    """A level with two puzzles receives twice as many tickets as one with one."""
    random_source: Mock = Mock()
    random_source.randrange.return_value = ticket
    monkeypatch.setattr("sudoku.daily.random.SystemRandom", lambda: random_source)
    catalog: dict[str, range] = {"Easy": range(1), "Medium": range(2)}
    assert choose_daily_level(catalog, "Easy", "Medium") == expected
    random_source.randrange.assert_called_once_with(3)


def test_daily_range_includes_sixth_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inclusive range can select Extreme without requiring other levels."""
    random_source: Mock = Mock()
    random_source.randrange.return_value = 0
    monkeypatch.setattr("sudoku.daily.random.SystemRandom", lambda: random_source)
    assert choose_daily_level({"Extreme": range(5)}, "Extreme", "Extreme") == "Extreme"
    assert Preferences.from_dict({}).daily_maximum == LEVELS[-1]
    assert Preferences.from_dict({"daily_minimum": "Master"}).daily_minimum == "Master"
    assert (
        Preferences.from_dict({"daily_minimum": "Extreme", "daily_maximum": "Easy"}).daily_minimum
        == "Easy"
    )


@pytest.mark.parametrize("level", ["Medium", "Hard", "Expert"])
@pytest.mark.parametrize("last_ticket", [False, True])
def test_medium_to_expert_range_boundaries(
    monkeypatch: pytest.MonkeyPatch, level: str, last_ticket: bool
) -> None:
    """Reach both ends of every eligible level using the real catalog weights."""
    catalog: Catalog = load_catalog()
    levels: tuple[str, ...] = ("Medium", "Hard", "Expert")
    ticket: int = sum(len(catalog[previous]) for previous in levels[: levels.index(level)])
    if last_ticket:
        ticket += len(catalog[level]) - 1
    random_source: Mock = Mock()
    random_source.randrange.return_value = ticket
    monkeypatch.setattr("sudoku.daily.random.SystemRandom", lambda: random_source)
    assert choose_daily_level(catalog, "Medium", "Expert") == level
    random_source.randrange.assert_called_once_with(sum(len(catalog[name]) for name in levels))


def test_daily_game_uses_regular_rotation_and_preserves_regular_game(tmp_path: Path) -> None:
    """Assign one unplayed puzzle while leaving the regular active pointer alone."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    assert store.load_game(catalog) is None
    regular: Game = store.start_game("Easy")
    day: str = "2026-09-25"
    daily: Game = store.start_daily_game(day, "Medium")
    assert daily.puzzle.level == "Medium"
    assert daily.puzzle.identifier != regular.puzzle.identifier
    assert store.daily_game_exists(day)
    with pytest.raises(SaveError, match="already been assigned"):
        store.start_daily_game(day, "Medium")
    empty: int = next(index for index, value in enumerate(daily.values) if not value)
    daily.set_value(empty, daily.puzzle.solution[empty])
    daily.elapsed = 42.5
    store.save_daily_game(day, daily)
    store.save_active_daily_date(day)
    reopened: Store = Store(tmp_path)
    restored_regular: Game | None = reopened.load_game(catalog)
    restored_daily: Game | None = reopened.load_daily_game(day, catalog)
    assert restored_regular is not None and restored_regular.puzzle == regular.puzzle
    assert restored_daily is not None and restored_daily.snapshot() == daily.snapshot()
    assert restored_daily.elapsed == 42.5
    assert reopened.load_active_daily_date() == day


@pytest.mark.parametrize("backup_only", [False, True])
def test_daily_button_reopens_today_without_a_chooser(tmp_path: Path, backup_only: bool) -> None:
    """Opening today's assigned puzzle never selects a second one."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    regular: Game = store.start_game("Easy")
    existing: Game = store.start_daily_game("2026-09-25", "Hard")
    if backup_only:
        path: Path = tmp_path / "catalog-daily-games/2026-09-25.json"
        path.rename(path.with_suffix(".backup.json"))
    state: SimpleNamespace = SimpleNamespace(
        preferences=Preferences(daily_enabled=True),
        board=Mock(),
        save=Mock(),
        update_current_day=Mock(return_value=False),
        current_day="2026-09-25",
        daily_games={},
        store=store,
        history=HistoryStore(tmp_path / "history.sqlite3"),
        catalog=catalog,
        regular_game=regular,
        active_daily_date=None,
        game=regular,
        changed=Mock(),
        alert=Mock(),
        window=Mock(),
    )
    controller: Any = AppController.alloc().init()
    for name, value in vars(state).items():
        setattr(controller, name, value)
    AppController.dailyGames_(controller, None)
    assert controller.game.puzzle == existing.puzzle
    assert controller.regular_game is regular
    controller.alert.assert_not_called()
    controller.changed.assert_called_once()
    assert len(list((tmp_path / "catalog-daily-games").glob("*.json"))) == 1
    controller.game.values = list(controller.game.puzzle.solution)
    AppController.dailyGames_(controller, None)
    controller.changed.assert_called_once()
    assert len(list((tmp_path / "catalog-daily-games").glob("*.json"))) == 1


@pytest.mark.parametrize("backup_only", [False, True])
def test_invalid_daily_save_does_not_assign_replacement(tmp_path: Path, backup_only: bool) -> None:
    """Preserve damaged daily state and prevent a second game for its date."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    day: str = "2026-09-25"
    store.start_daily_game(day, "Easy")
    path: Path = tmp_path / "catalog-daily-games" / f"{day}.json"
    if backup_only:
        path = path.rename(path.with_suffix(".backup.json"))
    path.write_text("broken")
    with pytest.raises(SaveError, match="unreadable"):
        Store(tmp_path).load_daily_game(day, catalog)
    with pytest.raises(SaveError, match="already been assigned"):
        store.start_daily_game(day, "Easy")
    assert path.read_text() == "broken"


@pytest.mark.parametrize("damage", ["missing", "syntax", "invalid_board", "invalid_puzzle_id"])
def test_daily_backup_restores_progress_and_prevents_reassignment(
    tmp_path: Path, damage: str
) -> None:
    """Recover the same attempt and protect the original until saving can safely resume."""
    catalog: Catalog = load_catalog()
    store: Store = Store(tmp_path)
    store.load_game(catalog)
    day: str = "2026-09-25"
    daily: Game = store.start_daily_game(day, "Easy")
    empty: int = daily.values.index(0)
    daily.set_value(empty, daily.puzzle.solution[empty])
    daily.elapsed = 23
    store.save_daily_game(day, daily)
    expected: dict[str, Any] = game_data(daily)
    daily.elapsed = 47
    store.save_daily_game(day, daily)
    store.save_active_daily_date(day)
    name: str = f"catalog-daily-games/{day}.json"
    path: Path = tmp_path / name
    backup: Path = path.with_suffix(".backup.json")
    backup_contents: bytes = backup.read_bytes()
    if damage == "missing":
        path.unlink()
    elif damage == "syntax":
        path.write_text("broken")
    else:
        game_state: dict[str, Any] = game_data(daily)
        if damage == "invalid_board":
            game_state["board"]["values"][empty] = 10
        else:
            game_state["puzzle_id"] = ["invalid"]
        path.write_text(json.dumps({"version": 1, "date": day, "game": game_state}))
    damaged_contents: bytes | None = path.read_bytes() if path.exists() else None

    reopened: Store = Store(tmp_path)
    reopened.load_game(catalog)
    assert reopened.load_active_daily_date() == day
    with pytest.raises(SaveError, match="already been assigned"):
        reopened.start_daily_game(day, "Easy")
    restored: Game | None = reopened.load_daily_game(day, catalog)
    assert restored is not None and game_data(restored) == expected
    assert any("from its backup" in warning for warning in reopened.warnings)
    if damaged_contents is not None:
        assert path.read_bytes() == damaged_contents
        with pytest.raises(SaveError, match="Recover Saving"):
            reopened.save_daily_game(day, restored)
        reopened.recover()
        preserved: Path = next(path.parent.glob(f"{day}.unreadable-*.json"))
        assert preserved.read_bytes() == damaged_contents
    assert not path.exists()

    restored.elapsed = 31
    reopened.save_daily_game(day, restored)
    assert backup.read_bytes() == backup_contents
    resaved: Game | None = Store(tmp_path).load_daily_game(day, catalog)
    assert resaved is not None and game_data(resaved) == game_data(restored)
