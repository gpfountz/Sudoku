# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify automatic OCR selection, conservative fallback, and preview overrides."""

from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from scripts.ocr_experiment import experimental_fast_ocr
from sudoku import compatibility, import_images
from sudoku.import_images import ImageArray


@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        ([(8, 1.0)], (8, 1.0)),
        ([(8, 0.85)], (8, 0.85)),
        ([(0, 0.0), (8, 0.95)], (8, 0.95)),
        ([(6, 0.30), (9, 0.95)], (9, 0.95)),
        ([(0, 1.0), (0, 0.0)], (0, 0.0)),
        ([(9, 0.50), (9, 0.30)], (9, 0.30)),
    ],
)
def test_automatic_fast_ocr_retains_accurate_fallback(
    monkeypatch: pytest.MonkeyPatch,
    readings: list[tuple[int, float]],
    expected: tuple[int, float],
) -> None:
    """Accept confident Fast digits while retaining weak Accurate confidence for review."""
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", lambda: True)
    reader: Mock = Mock(side_effect=readings)
    monkeypatch.setattr(import_images, "read_repeated_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    assert import_images.recognize_repeated_digit(glyph, 3) == expected
    assert reader.call_count == len(readings)
    assert reader.call_args_list[0].args[2] == import_images.V.VNRequestTextRecognitionLevelFast
    if len(readings) == 2:
        assert (
            reader.call_args_list[1].args[2]
            == import_images.V.VNRequestTextRecognitionLevelAccurate
        )


def test_other_hosts_keep_accurate_recognition(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the existing Accurate-only path unchanged when automatic Fast is disabled."""
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", lambda: False)
    reader: Mock = Mock(return_value=(8, 0.30))
    monkeypatch.setattr(import_images, "read_repeated_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    assert import_images.recognize_repeated_digit(glyph, 3) == (8, 0.30)
    reader.assert_called_once_with(
        glyph, 3, int(import_images.V.VNRequestTextRecognitionLevelAccurate)
    )


@pytest.mark.parametrize("fast_policy", [False, True])
@pytest.mark.parametrize("level", [0, 1])
def test_explicit_recognition_level_bypasses_automatic_policy(
    monkeypatch: pytest.MonkeyPatch, fast_policy: bool, level: int
) -> None:
    """Keep explicit native recognition levels usable for controlled diagnostic comparisons."""
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", lambda: fast_policy)
    reader: Mock = Mock(return_value=(5, 0.30))
    monkeypatch.setattr(import_images, "read_repeated_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    assert import_images.recognize_repeated_digit(glyph, 2, recognition_level=level) == (5, 0.30)
    reader.assert_called_once_with(glyph, 2, level)


@pytest.mark.parametrize("fast_policy", [False, True])
def test_compact_corroboration_follows_automatic_policy(
    fast_policy: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay the Intel 5 through the default digit reader without preview overrides."""
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", lambda: fast_policy)
    reader: Mock = Mock(side_effect=[(0, 0.0), (5, 0.30), (0, 0.0), (5, 0.30), (5, 1.0), (5, 1.0)])
    monkeypatch.setattr(import_images, "recognize_repeated_digit", reader)
    glyph: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    cv2.putText(glyph, "5", (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 4.5, 0, 2)
    assert import_images.recognize_digit(glyph) == (5, not fast_policy)
    assert reader.call_count == (6 if fast_policy else 5)


@pytest.mark.parametrize("host_policy", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_preview_override_preserves_host_policy(
    host_policy: bool, enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the production policy only inside the preview context, restoring it afterward."""
    policy: Mock = Mock(return_value=host_policy)
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", policy)
    with experimental_fast_ocr(enabled):
        assert compatibility.prefers_fast_ocr() is (enabled or host_policy)
    assert compatibility.prefers_fast_ocr is policy


def test_preview_restores_policy_after_native_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore policy even when a native reader raises during the forced preview."""
    policy: Mock = Mock(return_value=False)
    monkeypatch.setattr(compatibility, "prefers_fast_ocr", policy)
    monkeypatch.setattr(
        import_images,
        "read_repeated_digit",
        Mock(side_effect=ValueError("Native recognition failed")),
    )
    with pytest.raises(ValueError, match="Native recognition failed"), experimental_fast_ocr(True):
        import_images.recognize_repeated_digit(np.full((170, 170), 255, dtype=np.uint8), 3)
    assert compatibility.prefers_fast_ocr is policy
