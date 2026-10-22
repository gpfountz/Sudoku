# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Report real Vision readings and timings without changing recognition or confidence rules."""

import argparse
import json
import platform
import sys
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2

from sudoku import import_images
from sudoku.engine import cell_name
from sudoku.import_images import GridRegion, ImageArray

ROOT: Path = Path(__file__).resolve().parents[1]


def trace_digit(glyph: ImageArray) -> dict[str, Any]:
    """Capture each production OCR attempt while preserving its value and review decision."""
    calls: list[dict[str, Any]] = []
    original: Callable[[ImageArray, int], tuple[int, float]] = (
        import_images.recognize_repeated_digit
    )

    def record(source: ImageArray, copies: int) -> tuple[int, float]:
        """Record the engine's confidence and latency without modifying either result."""
        started: float = time.monotonic()
        value: int
        confidence: float
        value, confidence = original(source, copies)
        calls.append(
            {
                "copies": copies,
                "patch_shape": list(source.shape),
                "digit": value,
                "confidence": confidence,
                "seconds": round(time.monotonic() - started, 4),
            }
        )
        return value, confidence

    started: float = time.monotonic()
    with patch.object(import_images, "recognize_repeated_digit", record):
        value: int
        needs_review: bool
        value, needs_review = import_images.recognize_digit(glyph)
    return {
        "digit": value,
        "needs_review": needs_review,
        "seconds": round(time.monotonic() - started, 4),
        "attempts": calls,
    }


def fixture_glyphs(fixture: str, cells: list[int]) -> list[tuple[str, ImageArray | None]]:
    """Prepare the same fixture pixels used by the native recognition regression tests."""
    directory: Path = ROOT / "tests/fixtures"
    if fixture == "bottom-eight":
        glyph: ImageArray | None = cv2.imread(
            str(directory / "import-bottom-eight.png"), cv2.IMREAD_GRAYSCALE
        )
        if glyph is None:
            raise ValueError("Could not read the bottom-eight fixture")
        return [("bottom-eight", glyph)]
    image: ImageArray = import_images.decode_image(
        import_images.read_image_file(directory / "import-thin-digits.png")
    )
    height: int
    width: int
    height, width = image.shape[:2]
    board: ImageArray = import_images.warp_board(
        image, GridRegion(((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)))
    )
    return [
        (
            cell_name(index),
            import_images.digit_patch(
                board[
                    index // 9 * 100 : (index // 9 + 1) * 100,
                    index % 9 * 100 : (index % 9 + 1) * 100,
                ]
            ),
        )
        for index in cells
    ]


def main() -> None:
    """Print a small JSON diagnostic suitable for comparing OS-supplied OCR engines."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", choices=("bottom-eight", "thin-digits"), default="bottom-eight"
    )
    parser.add_argument(
        "--cells", type=int, nargs="+", default=[3, 5, 8], help="Zero-based cell indices"
    )
    arguments: argparse.Namespace = parser.parse_args()
    if any(index < 0 or index >= 81 for index in arguments.cells):
        parser.error("Cell indices must be between 0 and 80")
    request: Any = import_images.V.VNRecognizeTextRequest.alloc().init()
    report: dict[str, Any] = {
        "macos": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "vision_request_revision": int(request.revision()),
        "packages": {
            name: metadata.version(name)
            for name in ("pyobjc-framework-Vision", "opencv-python-headless", "numpy")
        },
        "fixture": arguments.fixture,
        "results": [
            {"cell": name, **trace_digit(glyph)}
            if glyph is not None
            else {"cell": name, "digit": 0, "needs_review": False, "attempts": []}
            for name, glyph in fixture_glyphs(arguments.fixture, arguments.cells)
        ],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
