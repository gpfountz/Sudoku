# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Load and play game audio on one worker so the board can redraw immediately."""

import sys
from concurrent.futures import Future, ThreadPoolExecutor
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from threading import Event
from typing import Any

import AppKit as AK
import objc
from Foundation import NSData


def load_game_sound(name: str) -> Any:
    """Decode one of the bundled audio cues."""
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


class GameSounds:
    """Accept requests from the UI while keeping native sound objects on the worker."""

    def __init__(self) -> None:
        """Create a serial queue that starts its worker on the first cue."""
        self._worker: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="Sudoku audio"
        )
        self._pending: Future[None] | None = None
        self._cancelled: Event = Event()
        self._sounds: dict[str, Any] = {}
        self._active: Any = None

    def play(self, name: str) -> None:
        """Queue audio without waiting and drop extra buzzes while a request is pending."""
        if self._pending is not None and not self._pending.done():
            if name == "incorrect":
                return
            self._pending.cancel()
        self._pending = self._worker.submit(self._play, name, self._cancelled)

    def stop(self) -> None:
        """Cancel a queued cue and silence playback on the worker when sounds are disabled."""
        if self._pending is not None:
            self._cancelled.set()
            self._cancelled = Event()
            self._pending.cancel()
            self._pending = None
            self._worker.submit(self._stop)

    def _play(self, name: str, cancelled: Event) -> None:
        """Load and start the cue, giving a completion chime priority over a buzz."""
        with objc.autorelease_pool():
            if cancelled.is_set():
                return
            if self._active is not None and self._active.isPlaying():
                if name == "incorrect":
                    return
                self._active.stop()
            if name not in self._sounds:
                self._sounds[name] = load_game_sound(name)
            sound: Any = self._sounds[name]
            if not cancelled.is_set() and sound is not None and sound.play():
                self._active = sound

    def _stop(self) -> None:
        """Stop and release the active cue reference on the playback thread."""
        with objc.autorelease_pool():
            if self._active is not None:
                self._active.stop()
                self._active = None


game_sounds: GameSounds = GameSounds()
