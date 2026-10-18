# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Run this feature worktree with fresh, persistent preview data and isolated window geometry."""

import os
from pathlib import Path


def preview_directory() -> Path:
    """Locate test data inside this worktree, independently of production Application Support."""
    return Path(__file__).resolve().parents[1] / ".preview-data" / "puzzle-import"


def main() -> None:
    """Launch the source preview without installing or building an application bundle."""
    os.environ["SUDOKU_DATA_DIR"] = str(preview_directory())
    os.environ["SUDOKU_WINDOW_AUTOSAVE_NAME"] = "SudokuImportPreviewWindow"
    os.environ["SUDOKU_WINDOW_TITLE"] = "Sudoku — Import Preview"
    os.environ["SUDOKU_CATALOG_DIR"] = str(
        Path(__file__).resolve().parents[1] / "sudoku" / "data" / "catalog"
    )
    from sudoku.app import main as launch

    launch()


if __name__ == "__main__":
    main()
