# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Run older-macOS testing from source with separate progress and window geometry."""

import argparse
import os
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    """Launch isolated test data, optionally exercising rounded controls on a newer Mac."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rounded-controls",
        action="store_true",
        help="Preview the older-macOS button style on a system that supports glass.",
    )
    arguments: argparse.Namespace = parser.parse_args()
    root: Path = Path(__file__).resolve().parents[1]
    mode: str = "Rounded" if arguments.rounded_controls else "Native"
    os.environ["SUDOKU_DATA_DIR"] = str(root / ".preview-data" / "older-macos" / mode.lower())
    os.environ["SUDOKU_WINDOW_AUTOSAVE_NAME"] = f"SudokuCompatibilityPreviewWindow{mode}"
    os.environ["SUDOKU_WINDOW_TITLE"] = f"Sudoku — Compatibility Preview ({mode})"
    os.environ["SUDOKU_CATALOG_DIR"] = str(root / "sudoku/data/catalog")

    from sudoku.app import main as launch

    if arguments.rounded_controls:
        with patch("sudoku.compatibility.supports_glass_buttons", return_value=False):
            launch()
    else:
        launch()


if __name__ == "__main__":
    main()
