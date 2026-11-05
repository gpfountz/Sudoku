# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise the input-to-audio boundary without depending on an audio device."""

from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sudoku.app import AppController
from sudoku.game_sounds import GameSounds
from sudoku.model import Game, Preferences


def test_answer_feedback_can_draw_while_the_first_buzz_loads(
    game: Game, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose the error while the audio device is busy and keep cues from overlapping."""
    sounds: GameSounds = GameSounds()
    main_thread: int = get_ident()
    loading: Event = Event()
    ready: Event = Event()
    buzzer: Mock = Mock()
    buzzer.play.return_value = True
    buzzer.isPlaying.return_value = True
    chime: Mock = Mock()
    chime.play.return_value = True
    monkeypatch.setattr("sudoku.app.game_sounds", sounds)

    def load(name: str) -> Mock:
        """Hold the first decode on the audio worker until entry has returned."""
        assert get_ident() != main_thread
        if name == "incorrect":
            loading.set()
            assert ready.wait(5)
            return buzzer
        return chime

    monkeypatch.setattr("sudoku.game_sounds.load_game_sound", load)
    controller: Any = SimpleNamespace(
        game=game,
        preferences=Preferences(error_check="Against Solution", game_sounds=True),
        play_game_sound=lambda name: AppController.play_game_sound(controller, name),
    )
    try:
        assert AppController.enter_answer(controller, 1, 3)
        assert loading.wait(5)
        assert game.errors(controller.preferences.error_check) == {1}
        buzzer.play.assert_not_called()
        assert AppController.enter_answer(controller, 2, 4)
        ready.set()
        sounds._worker.submit(lambda: None).result(timeout=5)
        sounds.play("incorrect")
        sounds._worker.submit(lambda: None).result(timeout=5)
        buzzer.play.assert_called_once_with()
        sounds.play("excellent")
        sounds._worker.submit(lambda: None).result(timeout=5)
        buzzer.stop.assert_called_once_with()
        chime.play.assert_called_once_with()
        sounds.stop()
        sounds._worker.submit(lambda: None).result(timeout=5)
        chime.stop.assert_called_once_with()
    finally:
        ready.set()
        sounds._worker.shutdown()


def test_muting_discards_a_cue_still_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a cold cue from starting after the player turns sound off."""
    sounds: GameSounds = GameSounds()
    loading: Event = Event()
    ready: Event = Event()
    buzzer: Mock = Mock()
    buzzer.play.return_value = True

    def load(name: str) -> Mock:
        """Wait for the UI to mute the pending cue."""
        loading.set()
        assert ready.wait(5)
        return buzzer

    monkeypatch.setattr("sudoku.game_sounds.load_game_sound", load)
    try:
        sounds.play("incorrect")
        assert loading.wait(5)
        sounds.stop()
        ready.set()
        sounds._worker.submit(lambda: None).result(timeout=5)
        buzzer.play.assert_not_called()
        sounds.play("incorrect")
        sounds._worker.submit(lambda: None).result(timeout=5)
        buzzer.play.assert_called_once_with()
    finally:
        ready.set()
        sounds._worker.shutdown()
