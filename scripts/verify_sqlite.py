# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Inspect a prepared catalog and benchmark selection using new isolated player storage."""

import argparse
import json
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sudoku.catalog import Catalog, read_database  # noqa: E402
from sudoku.model import LEVELS, Game  # noqa: E402
from sudoku.storage import Store  # noqa: E402


def verify(directory: Path, selections: int, integrity: bool) -> None:
    """Measure actual supplied data; never generate puzzles or touch personal saves."""
    if selections < 1:
        raise ValueError("Selection count must be positive")
    tracemalloc.start()
    start: float = time.perf_counter()
    catalog: Catalog = Catalog(directory)
    print(f"Catalog startup: {time.perf_counter() - start:.6f} seconds")
    for level in LEVELS:
        group = catalog[level]
        size: int = group.path.stat().st_size
        with read_database(group.path) as connection:
            result: Any = connection.execute(
                "PRAGMA integrity_check" if integrity else "PRAGMA quick_check"
            ).fetchone()[0]
            count: int = connection.execute("SELECT count(*) FROM puzzles").fetchone()[0]
        if result != "ok" or count != len(group):
            raise ValueError(f"Catalog verification failed: {level}")
        print(f"{level}: {count} rows, {size} bytes, integrity={result}")
        if size >= 100 * 1024 * 1024:
            raise ValueError(f"{level} reaches the ordinary-Git 100 MiB limit")
    with tempfile.TemporaryDirectory(prefix="sudoku-player-benchmark-") as temporary:
        store: Store = Store(Path(temporary))
        store.load_game(catalog)
        for level in LEVELS:
            timings: list[float] = []
            for _ in range(selections):
                start = time.perf_counter()
                game: Game = store.start_game(level)
                timings.append(time.perf_counter() - start)
            store.save_game(game)
            restored: Game | None = store.load_game(catalog)
            assert restored and restored.puzzle.identifier == game.puzzle.identifier
            timings.sort()
            print(
                f"{level} selection: n={selections}, median={timings[len(timings) // 2]:.6f}s, "
                f"p95={timings[min(len(timings) - 1, int(len(timings) * 0.95))]:.6f}s, "
                f"max={timings[-1]:.6f}s"
            )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "python_current_bytes": current,
                "python_peak_bytes": peak,
                "process_peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_units": "bytes on macOS; KiB on Linux",
            }
        )
    )
    print("PASS: catalog resources and isolated save/resume verified")


def main() -> None:
    """Accept explicit catalog and benchmark size, with optional full integrity checking."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path(__file__).resolve().parents[1] / "sudoku/data/catalog"
    )
    parser.add_argument("--selections", type=int, default=100)
    parser.add_argument("--integrity-check", action="store_true")
    args: argparse.Namespace = parser.parse_args()
    verify(args.catalog, args.selections, args.integrity_check)


if __name__ == "__main__":
    main()
