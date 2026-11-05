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

SOUND_NAMES: tuple[str, ...] = ("incorrect", "good", "great", "excellent")


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
        """Create a serial queue for preparation and playback."""
        self._worker: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="Sudoku audio"
        )
        self._pending: Future[None] | None = None
        self._cancelled: Event = Event()
        self._sounds: dict[str, Any] = {}
        self._active: Any = None
        self._warmup: Any = None

    def prepare(self) -> None:
        """Preload and prime the audio output while the UI continues launching."""
        self._worker.submit(self._prepare, self._cancelled)

    def play(self, name: str) -> None:
        """Queue audio without waiting and drop extra buzzes while a request is pending."""
        if self._pending is not None and not self._pending.done():
            if name == "incorrect":
                return
            self._pending.cancel()
        self._pending = self._worker.submit(self._play, name, self._cancelled)

    def stop(self) -> None:
        """Cancel a queued cue and silence playback on the worker when sounds are disabled."""
        self._cancelled.set()
        self._cancelled = Event()
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        self._worker.submit(self._stop)

    def _sound(self, name: str) -> Any:
        """Return a decoded cue, loading it on demand if necessary."""
        if name not in self._sounds:
            self._sounds[name] = load_game_sound(name)
        return self._sounds[name]

    def _prepare(self, cancelled: Event) -> None:
        """Cache each cue and open the audio output with a separate, silent sound."""
        with objc.autorelease_pool():
            for name in SOUND_NAMES:
                if cancelled.is_set():
                    return
                self._sound(name)
            buzzer: Any = self._sounds["incorrect"]
            if cancelled.is_set() or buzzer is None or self._warmup is not None:
                return
            warmup: Any = buzzer.copy()
            warmup.setVolume_(0.0)
            if not cancelled.is_set() and warmup.play():
                self._warmup = warmup

    def _play(self, name: str, cancelled: Event) -> None:
        """Load and start the cue, giving a completion chime priority over a buzz."""
        with objc.autorelease_pool():
            if cancelled.is_set():
                return
            if self._active is not None and self._active.isPlaying():
                if name == "incorrect":
                    return
                self._active.stop()
            sound: Any = self._sound(name)
            if not cancelled.is_set() and sound is not None and sound.play():
                self._active = sound

    def _stop(self) -> None:
        """Stop active playback and any silent warm-up on the playback thread."""
        with objc.autorelease_pool():
            if self._active is not None:
                self._active.stop()
                self._active = None
            if self._warmup is not None:
                self._warmup.stop()
                self._warmup = None


game_sounds: GameSounds = GameSounds()
