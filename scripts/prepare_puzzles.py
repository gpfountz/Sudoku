# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Validate a supplied local catalog and publish per-difficulty SQLite resources."""

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sudoku.catalog import level_filename  # noqa: E402
from sudoku.engine import conflicts, solve  # noqa: E402
from sudoku.model import LEVELS  # noqa: E402

ROOT: Path = Path(__file__).resolve().parents[1]
GIT_LIMIT: int = 100 * 1024 * 1024


def level_for(rating: float) -> str:
    """Map the existing published ratings to unchanged difficulty bands."""
    if not math.isfinite(rating) or rating < 0:
        raise ValueError("Invalid rating")
    for level, ceiling in zip(LEVELS, (1.5, 2.5, 5.0, 7.0, 9.0, float("inf")), strict=True):
        if rating < ceiling:
            return level
    raise ValueError("Invalid rating")


def source_records(path: Path) -> Iterator[dict[str, Any]]:
    """Read the existing JSON catalog or stream a larger supplied JSONL catalog."""
    if path.is_dir():
        for name in ("easy", "medium", "hard", "diabolical"):
            source_file: Path = path / f"{name}.txt"
            with source_file.open("rb") as raw:
                digest: str = hashlib.file_digest(raw, "sha256").hexdigest()
            with source_file.open() as lines:
                for line_number, line in enumerate(lines, 1):
                    if not line.strip():
                        continue
                    _, digits, rating_text = line.split()
                    rating: float = float(rating_text)
                    yield {
                        "id": hashlib.sha256(digits.encode()).hexdigest()[:16],
                        "givens": digits,
                        "solution": None,
                        "source_format": "sudoku-exchange-text",
                        "rating": rating,
                        "level": level_for(rating),
                        "source": "https://github.com/grantm/sudoku-exchange-puzzle-bank",
                        "source_file": source_file.name,
                        "source_line": line_number,
                        "source_sha256": digest,
                    }
        return
    with path.open() as stream:
        if path.suffix == ".jsonl":
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        else:
            data: dict[str, Any] = json.load(stream)
            if data.get("version") != 1 or not data.get("source"):
                raise ValueError("Missing catalog version or source metadata")
            for record in data["puzzles"]:
                yield {
                    "source": data["source"],
                    "source_sha256": data.get("source_sha256"),
                    **record,
                }


def validate_record(record: dict[str, Any]) -> tuple[str, str, str, float, str]:
    """Check identity, rating, board integrity, and exactly one matching solution."""
    identifier: Any = record["id"]
    givens: Any = record["givens"]
    solution: Any = record["solution"]
    if not isinstance(givens, str) or len(givens) != 81 or set(givens) - set("0123456789"):
        raise ValueError(f"Invalid givens: {identifier}")
    derived: bool = solution is None and record.get("source_format") == "sudoku-exchange-text"
    if derived:
        solutions: list[tuple[int, ...]] = solve(tuple(map(int, givens)))
        if len(solutions) != 1:
            raise ValueError(f"Nonunique puzzle: {identifier}")
        solution = "".join(map(str, solutions[0]))
    rating: float = float(record["rating"])
    level: str = record["level"]
    if not isinstance(identifier, str) or not identifier or not record.get("source"):
        raise ValueError("Missing stable ID or source")
    if (
        not isinstance(givens, str)
        or len(givens) != 81
        or set(givens) - set("0123456789")
        or not isinstance(solution, str)
        or len(solution) != 81
        or set(solution) - set("123456789")
    ):
        raise ValueError(f"Invalid board: {identifier}")
    if level != level_for(rating):
        raise ValueError(f"Incorrect difficulty: {identifier}")
    values: tuple[int, ...] = tuple(map(int, givens))
    answer: tuple[int, ...] = tuple(map(int, solution))
    if conflicts(answer) or any(given and given != answer[i] for i, given in enumerate(values)):
        raise ValueError(f"Inconsistent solution: {identifier}")
    if not derived and solve(values) != [answer]:
        raise ValueError(f"Puzzle does not have the supplied unique solution: {identifier}")
    return identifier, givens, solution, rating, level


def prepare(source: Path, output: Path, limit_per_level: int | None = None) -> dict[str, int]:
    """Stage and validate all databases before atomically publishing their manifest."""
    if limit_per_level is not None and limit_per_level < 1:
        raise ValueError("Small-import limit must be positive")
    output.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = dict.fromkeys(LEVELS, 0)
    generation: str = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output) as temporary:
        staging: Path = Path(temporary)
        connections: dict[str, sqlite3.Connection] = {}
        oversized: list[str] = []
        seen: sqlite3.Connection = sqlite3.connect(staging / "identities.sqlite")
        seen.execute("CREATE TABLE seen(id TEXT PRIMARY KEY, givens TEXT UNIQUE)")
        try:
            for level in LEVELS:
                connection: sqlite3.Connection = sqlite3.connect(staging / level_filename(level))
                connections[level] = connection
                connection.executescript(
                    "PRAGMA user_version=1;"
                    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                    "CREATE TABLE sources(source_id INTEGER PRIMARY KEY,"
                    "details TEXT NOT NULL UNIQUE);"
                    "CREATE TABLE puzzles(ordinal INTEGER PRIMARY KEY,id TEXT NOT NULL UNIQUE,"
                    "givens TEXT NOT NULL,solution TEXT NOT NULL,rating REAL NOT NULL,"
                    "level TEXT NOT NULL,source_id INTEGER NOT NULL REFERENCES sources(source_id),"
                    "source_line INTEGER);"
                )
            for record in source_records(source):
                level = record["level"]
                if level not in LEVELS:
                    raise ValueError(f"Unknown difficulty: {level}")
                if limit_per_level and counts[level] >= limit_per_level:
                    continue
                identifier, givens, solution, rating, level = validate_record(record)
                try:
                    seen.execute("INSERT INTO seen VALUES (?,?)", (identifier, givens))
                except sqlite3.IntegrityError as error:
                    raise ValueError(f"Duplicate puzzle ID or givens: {identifier}") from error
                counts[level] += 1
                metadata: str = json.dumps(
                    {
                        key: value
                        for key, value in record.items()
                        if key not in ("id", "givens", "solution", "rating", "level", "source_line")
                    },
                    sort_keys=True,
                    allow_nan=False,
                )
                connections[level].execute(
                    "INSERT OR IGNORE INTO sources(details) VALUES (?)", (metadata,)
                )
                source_id: int = (
                    connections[level]
                    .execute("SELECT source_id FROM sources WHERE details=?", (metadata,))
                    .fetchone()[0]
                )
                connections[level].execute(
                    "INSERT INTO puzzles VALUES (?,?,?,?,?,?,?,?)",
                    (
                        counts[level],
                        identifier,
                        givens,
                        solution,
                        rating,
                        level,
                        source_id,
                        record.get("source_line"),
                    ),
                )
                if sum(counts.values()) % 10000 == 0:
                    print(f"Validated {sum(counts.values())} puzzles: {counts}", flush=True)
            if not all(counts.values()):
                raise ValueError(f"Every difficulty must contain puzzles: {counts}")
            source_hash: str = "per-record source file hashes"
            if source.is_file():
                with source.open("rb") as raw:
                    source_hash = hashlib.file_digest(raw, "sha256").hexdigest()
            for level, connection in connections.items():
                connection.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    (
                        ("level", level),
                        ("count", str(counts[level])),
                        ("source_sha256", source_hash),
                        (
                            "validation",
                            "unique solution, stable IDs, difficulty and integrity verified",
                        ),
                    ),
                )
                connection.commit()
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(f"Integrity failure: {level}")
                connection.close()
                size: int = (staging / level_filename(level)).stat().st_size
                print(f"{level}: {counts[level]} rows; validation OK; {size} bytes", flush=True)
                if size >= GIT_LIMIT:
                    oversized.append(level)
            if oversized:
                raise ValueError(f"GitHub 100 MiB limit reached by {oversized}; not published")
        finally:
            seen.close()
            for connection in connections.values():
                connection.close()
        (staging / "identities.sqlite").unlink()
        destination: Path = output / generation
        shutil.move(str(staging), destination)
        manifest: Path = output / f".manifest-{generation}.tmp"
        with manifest.open("w") as stream:
            json.dump({"version": 1, "generation": generation, "counts": counts}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        manifest.replace(output / "manifest.json")
    print(f"Published {sum(counts.values())} puzzles to {output / generation}")
    return counts


def main() -> None:
    """Convert only a user-supplied local source; never download replacement puzzles."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "sudoku/data/puzzles.json")
    parser.add_argument("--output", type=Path, default=ROOT / "sudoku/data/catalog")
    parser.add_argument("--limit-per-level", type=int, help="Explicit small import for testing")
    args: argparse.Namespace = parser.parse_args()
    prepare(args.source, args.output, args.limit_per_level)


if __name__ == "__main__":
    main()
