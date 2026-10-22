# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Keep the opt-in OCR experiment conservative and scoped to its preview process."""

from collections.abc import Callable
from unittest.mock import Mock

import numpy as np
import pytest

from scripts.ocr_experiment import experimental_fast_ocr
from sudoku import import_images
from sudoku.import_images import ImageArray


@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        ([(8, 1.0)], (8, 1.0)),
        ([(0, 0.0), (8, 0.95)], (8, 0.95)),
        ([(6, 0.30), (9, 0.95)], (9, 0.95)),
        ([(0, 1.0), (0, 0.0)], (0, 0.0)),
        ([(9, 0.50), (9, 0.30)], (9, 0.30)),
    ],
)
def test_fast_experiment_falls_back_without_promoting_weak_readings(
    monkeypatch: pytest.MonkeyPatch,
    readings: list[tuple[int, float]],
    expected: tuple[int, float],
) -> None:
    """Avoid costly retries for confident Fast digits and retain weak Accurate confidence."""
    reader: Mock = Mock(side_effect=readings)
    monkeypatch.setattr(import_images, "recognize_repeated_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    with experimental_fast_ocr(True):
        assert import_images.recognize_repeated_digit(glyph, 3) == expected
    assert import_images.recognize_repeated_digit is reader
    assert reader.call_count == len(readings)
    assert reader.call_args_list[0].kwargs == {
        "recognition_level": int(import_images.V.VNRequestTextRecognitionLevelFast)
    }
    if len(readings) == 2:
        assert not reader.call_args_list[1].kwargs


def test_fast_experiment_leaves_normal_recognition_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the original reader when the preview flag is absent."""
    reader: Mock = Mock()
    monkeypatch.setattr(import_images, "recognize_repeated_digit", reader)
    with experimental_fast_ocr(False):
        assert import_images.recognize_repeated_digit is reader
    reader.assert_not_called()


def test_fast_experiment_restores_reader_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uninstall the experimental reader even when native recognition raises."""
    reader: Mock = Mock(side_effect=ValueError("Native recognition failed"))
    digit_reader: Callable[..., tuple[int, bool]] = import_images.recognize_digit
    monkeypatch.setattr(import_images, "recognize_repeated_digit", reader)
    with pytest.raises(ValueError, match="Native recognition failed"), experimental_fast_ocr(True):
        import_images.recognize_repeated_digit(np.full((170, 170), 255, dtype=np.uint8), 3)
    assert import_images.recognize_repeated_digit is reader
    assert import_images.recognize_digit is digit_reader


@pytest.mark.parametrize("enabled", [False, True])
def test_compact_corroboration_is_scoped_to_experiment(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enable the extra compact retry only for the explicit experiment and restore it."""
    reader: Mock = Mock(return_value=(5, True))
    monkeypatch.setattr(import_images, "recognize_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    with experimental_fast_ocr(enabled):
        assert import_images.recognize_digit(glyph) == (5, True)
    assert import_images.recognize_digit is reader
    assert reader.call_args.kwargs == ({"corroborate_compact": True} if enabled else {})
