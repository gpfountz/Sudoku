# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Load and play the game's short original audio cues through AppKit."""

import sys
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import AppKit as AK
from Foundation import NSData


@lru_cache(maxsize=4)
def game_sound(name: str) -> Any:
    """Keep each decoded sound alive for asynchronous native playback."""
    resources: Traversable = (
        Path(sys.executable).parent.parent / "Resources" / "sounds"
        if getattr(sys, "frozen", False)
        else files("sudoku").joinpath("data", "sounds")
    )
    try:
        data: bytes = resources.joinpath(f"{name}.wav").read_bytes()
    except OSError:
        return None
    return AK.NSSound.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
