# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Scope optional OCR experiments to source previews and diagnostic processes."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

from sudoku import import_images
from sudoku.import_images import MINIMUM_OCR_CONFIDENCE, ImageArray


@contextmanager
def experimental_fast_ocr(enabled: bool) -> Iterator[None]:
    """Try confident Fast readings first, retaining Accurate fallback and review policy."""
    if not enabled:
        yield
        return
    original: Callable[..., tuple[int, float]] = import_images.recognize_repeated_digit

    def fast_then_accurate(source: ImageArray, copies: int) -> tuple[int, float]:
        """Use Accurate recognition whenever Fast does not provide confident digits."""
        digit: int
        confidence: float
        digit, confidence = original(
            source,
            copies,
            recognition_level=int(import_images.V.VNRequestTextRecognitionLevelFast),
        )
        if digit and confidence >= MINIMUM_OCR_CONFIDENCE:
            return digit, confidence
        return original(source, copies)

    with patch.object(import_images, "recognize_repeated_digit", fast_then_accurate):
        yield
