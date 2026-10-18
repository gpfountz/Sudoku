# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Sample the actual daily difficulty selector without changing saved games."""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sudoku.catalog import Catalog, load_catalog  # noqa: E402
from sudoku.daily import choose_daily_level  # noqa: E402
from sudoku.model import LEVELS  # noqa: E402


def sample_levels(catalog: Catalog, minimum: str, maximum: str, selections: int) -> Counter[str]:
    """Call the production selector repeatedly and count its returned levels."""
    if selections < 1:
        raise ValueError("Selection count must be positive")
    counts: Counter[str] = Counter(
        choose_daily_level(catalog, minimum, maximum) for _ in range(selections)
    )
    return counts


def main() -> None:
    """Report sampled counts and catalog-weighted probabilities for an inclusive range."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum", choices=LEVELS, default="Medium")
    parser.add_argument("--maximum", choices=LEVELS, default="Expert")
    parser.add_argument("--selections", type=int, default=100)
    parser.add_argument(
        "--catalog", type=Path, help="Use a specific catalog, such as the installed app"
    )
    args: argparse.Namespace = parser.parse_args()
    catalog: Catalog = load_catalog(args.catalog)
    counts: Counter[str] = sample_levels(catalog, args.minimum, args.maximum, args.selections)
    levels: tuple[str, ...] = LEVELS[LEVELS.index(args.minimum) : LEVELS.index(args.maximum) + 1]
    total: int = sum(len(catalog[level]) for level in levels)
    print(f"Daily range: {args.minimum} through {args.maximum}; selections: {args.selections}")
    print(f"{'Level':<10} {'Selected':>8} {'Catalog puzzles':>16} {'Expected chance':>16}")
    for level in levels:
        probability: float = len(catalog[level]) / total
        print(f"{level:<10} {counts[level]:>8} {len(catalog[level]):>16,} {probability:>15.2%}")
    print(f"Total: {sum(counts.values())}")
    print("Counts vary on each run; a random sample does not guarantee every level appears.")


if __name__ == "__main__":
    main()
