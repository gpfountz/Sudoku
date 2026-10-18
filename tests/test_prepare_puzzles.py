# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Small imports validate source integrity before publishing any replacement databases."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.prepare_puzzles import prepare
from sudoku.catalog import Catalog, load_catalog
from sudoku.model import LEVELS, Puzzle


def source_subset(path: Path) -> list[dict[str, Any]]:
    """Export only two existing puzzles per difficulty for isolated import checks."""
    catalog: Catalog = load_catalog()
    records: list[dict[str, Any]] = []
    for level in LEVELS:
        for puzzle in catalog[level][:2]:
            records.append(
                {
                    "id": puzzle.identifier,
                    "level": level,
                    "rating": puzzle.rating,
                    "givens": "".join(map(str, puzzle.givens)),
                    "solution": "".join(map(str, puzzle.solution)),
                }
            )
    path.write_text(
        json.dumps({"version": 1, "source": "existing catalog subset", "puzzles": records})
    )
    return records


def test_small_import_preserves_ids(tmp_path: Path) -> None:
    """Partition an explicit subset into six valid databases without changing IDs."""
    source: Path = tmp_path / "input.json"
    records: list[dict[str, Any]] = source_subset(source)
    counts: dict[str, int] = prepare(source, tmp_path / "out", 1)
    assert counts == dict.fromkeys(LEVELS, 1)
    catalog: Catalog = Catalog(tmp_path / "out")
    assert {catalog[level][0].identifier for level in LEVELS} == {r["id"] for r in records[::2]}


@pytest.mark.parametrize(
    "damage", ["duplicate", "difficulty", "solution", "givens", "source", "empty", "nonunique"]
)
def test_failed_import_preserves_published_generation(tmp_path: Path, damage: str) -> None:
    """Reject data failures before replacing a previously published valid manifest."""
    source: Path = tmp_path / "input.json"
    records: list[dict[str, Any]] = source_subset(source)
    output: Path = tmp_path / "out"
    prepare(source, output, 1)
    before: dict[Path, bytes] = {
        path: path.read_bytes() for path in output.rglob("*") if path.is_file()
    }
    if damage == "duplicate":
        records[1]["id"] = records[0]["id"]
    elif damage == "difficulty":
        records[0]["level"] = "Extreme"
    elif damage == "solution":
        records[0]["solution"] = "1" * 81
    elif damage == "nonunique":
        records[0]["givens"] = "0" * 81
    elif damage == "givens":
        records[0]["givens"] = "9" * 81
    elif damage == "empty":
        records = [record for record in records if record["level"] != "Extreme"]
    source.write_text(
        json.dumps(
            {"version": 1, "source": "" if damage == "source" else "test", "puzzles": records}
        )
    )
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        prepare(source, output)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not list(output.glob(".prepare-*"))


def test_git_limit_stops_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An oversized output is flagged without silently enabling LFS or publishing."""
    source: Path = tmp_path / "input.json"
    source_subset(source)
    monkeypatch.setattr("scripts.prepare_puzzles.GIT_LIMIT", 1)
    with pytest.raises(ValueError, match="100 MiB"):
        prepare(source, tmp_path / "out", 1)
    assert not (tmp_path / "out/manifest.json").exists()


def test_local_bank_import_has_no_default_limit(tmp_path: Path) -> None:
    """Read every local bank row and map source categories into the app's six bands."""
    bank: Path = tmp_path / "bank"
    bank.mkdir()
    catalog: Catalog = load_catalog()
    groups: dict[str, tuple[str, ...]] = {
        "easy": ("Easy",),
        "medium": ("Medium",),
        "hard": ("Hard",),
        "diabolical": ("Expert", "Master", "Extreme"),
    }
    for name, levels in groups.items():
        lines: list[str] = []
        for level in levels:
            puzzle: Puzzle
            for puzzle in catalog[level][:2]:
                lines.append(f"source-id {''.join(map(str, puzzle.givens))} {puzzle.rating}\n")
        (bank / f"{name}.txt").write_text("".join(lines))
    assert prepare(bank, tmp_path / "out") == dict.fromkeys(LEVELS, 2)
    imported: Catalog = Catalog(tmp_path / "out")
    assert imported["Easy"][0].identifier == catalog["Easy"][0].identifier


def test_distribution_metadata_and_resource_declarations() -> None:
    """Rename only the distribution, keeping commands and native identity stable."""
    import tomllib

    root: Path = Path(__file__).resolve().parents[1]
    config: dict[str, Any] = tomllib.loads((root / "pyproject.toml").read_text())
    assert config["project"]["name"] == "pfountz-sudoku"
    assert config["project"]["scripts"]["sudoku"] == "sudoku.app:main"
    assert "data/catalog/*/*.sqlite" in config["tool"]["setuptools"]["package-data"]["sudoku"]
    assert '"CFBundleIdentifier": "com.pfountz.sudoku"' in (root / "setup.py").read_text()


def test_build_stages_only_active_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Packaging uses real database files and excludes retired catalog generations."""
    from scripts.build_app import stage_catalog

    source: Path = tmp_path / "input.json"
    source_subset(source)
    output: Path = tmp_path / "sudoku/data/catalog"
    prepare(source, output, 1)
    prepare(source, output, 1)
    monkeypatch.setattr("scripts.build_app.ROOT", tmp_path)
    stage_catalog(tmp_path / "staged")
    assert len(list((tmp_path / "staged").rglob("*.sqlite"))) == 6
    assert (
        Catalog(tmp_path / "staged")["Easy"][0].identifier == load_catalog()["Easy"][0].identifier
    )


def test_frozen_runtime_uses_actual_resource_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve py2app's resource files rather than a symlinked Python executable."""
    import shutil
    import sys

    catalog: Catalog = load_catalog()
    shutil.copytree(catalog["Easy"].path.parent.parent, tmp_path / "catalog")
    monkeypatch.delenv("SUDOKU_CATALOG_DIR")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("RESOURCEPATH", str(tmp_path))
    packaged: Catalog = load_catalog()
    assert packaged["Easy"][0].identifier == catalog["Easy"][0].identifier
    assert packaged["Easy"].path.is_relative_to(tmp_path / "catalog")
