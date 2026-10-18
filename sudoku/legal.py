# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Read application and third-party license notices without network access."""

import sys
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

COPYRIGHT_NOTICE: str = "Copyright © 2026 Greg Pfountz"
LICENSE_IDENTIFIER: str = "GPL-3.0-only"


def license_resources() -> Traversable:
    """Locate notices in a standalone app or an installed Python package."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.parent / "Resources" / "licenses"
    return files("sudoku").joinpath("data", "licenses")


def license_text() -> str:
    """Return the application notice and the complete GPLv3 license text."""
    resources: Traversable = license_resources()
    return (
        resources.joinpath("NOTICE.txt").read_text(encoding="utf-8")
        + "\n\n"
        + resources.joinpath("GPL-3.0.txt").read_text(encoding="utf-8")
    )


def third_party_text() -> str:
    """Return the puzzle dedication and all preserved upstream software notices."""
    resources: Traversable = license_resources()
    sections: list[str] = [
        resources.joinpath("THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8"),
        "Puzzle catalog\n\n" + resources.joinpath("PUZZLE-LICENSE.txt").read_text(encoding="utf-8"),
    ]
    for notice in sorted(resources.joinpath("third-party").iterdir(), key=lambda item: item.name):
        if notice.name.endswith(".txt") and notice.is_file():
            sections.append(notice.name + "\n\n" + notice.read_text(encoding="utf-8"))
    return "\n\n".join(sections)
