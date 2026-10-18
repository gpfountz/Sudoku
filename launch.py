# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Standalone app-bundle entry point."""

if __name__ == "__main__":
    from sudoku.app import main as launch_app

    launch_app()
