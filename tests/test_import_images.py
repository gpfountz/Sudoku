# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify grid location and local OCR against known printed grids in larger images."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import cv2
import numpy as np
import pytest

from sudoku.import_images import (
    GridRegion,
    ImageArray,
    compact_digit_patch,
    decode_image,
    detect_grids,
    digit_patch,
    image_bytes,
    read_image_file,
    recognize_digit,
    recognize_grid,
)

ROWS: tuple[str, ...] = (
    "530070000",
    "600195000",
    "098000060",
    "800060003",
    "400803001",
    "700020006",
    "060000280",
    "000419005",
    "000080079",
)


def test_oversized_file_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a real sparse file above the limit without reading its contents."""
    from sudoku.import_images import MAX_IMAGE_BYTES

    path: Path = tmp_path / "large.png"
    with path.open("wb") as output:
        output.truncate(MAX_IMAGE_BYTES + 1)
    with path.open("rb") as source:
        reader: Any = MagicMock(wraps=source)
        reader.__enter__.return_value = reader
        monkeypatch.setattr(Path, "open", Mock(return_value=reader))
        with pytest.raises(ValueError, match="image is too large"):
            read_image_file(path)
        reader.read.assert_not_called()


def test_file_growth_cannot_bypass_read_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bound the allocation when a file grows beyond its initially reported size."""
    from sudoku import import_images

    path: Path = tmp_path / "growing.png"
    path.write_bytes(b"x" * 100)
    monkeypatch.setattr(import_images, "MAX_IMAGE_BYTES", 16)
    monkeypatch.setattr(import_images.os, "fstat", Mock(return_value=Mock(st_size=16)))
    with path.open("rb") as source:
        reader: Any = MagicMock(wraps=source)
        reader.__enter__.return_value = reader
        monkeypatch.setattr(Path, "open", Mock(return_value=reader))
        with pytest.raises(ValueError, match="image is too large"):
            read_image_file(path)
        reader.read.assert_called_once_with(17)


def test_file_at_size_limit_preserves_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept a file exactly at the limit without changing its original data."""
    monkeypatch.setattr("sudoku.import_images.MAX_IMAGE_BYTES", 16)
    path: Path = tmp_path / "puzzle.png"
    data: bytes = b"0123456789abcdef"
    path.write_bytes(data)
    assert read_image_file(path) == data


def printed_grid() -> ImageArray:
    """Render a known clue grid with printed digits and normal box boundaries."""
    image: ImageArray = np.full((724, 724, 3), 255, dtype=np.uint8)
    for index in range(10):
        position: int = 2 + index * 80
        thickness: int = 4 if index % 3 == 0 else 1
        cv2.line(image, (position, 2), (position, 722), (0, 0, 0), thickness)
        cv2.line(image, (2, position), (722, position), (0, 0, 0), thickness)
    for row, digits in enumerate(ROWS):
        for column, digit in enumerate(digits):
            if digit != "0":
                cv2.putText(
                    image,
                    digit,
                    (column * 80 + 24, row * 80 + 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.6,
                    (0, 0, 0),
                    3,
                    cv2.LINE_AA,
                )
    return image


@pytest.mark.parametrize("dark", [False, True])
def test_detect_grid_inside_page(dark: bool) -> None:
    """Locate the board among surrounding headers, text, and unrelated rectangles."""
    image: ImageArray = np.full((1200, 1800, 3), 245, dtype=np.uint8)
    image[330:1054, 880:1604] = printed_grid()
    cv2.rectangle(image, (100, 200), (600, 550), (0, 0, 0), 3)
    cv2.putText(
        image, "NEWSPAPER - DAILY PUZZLE", (100, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2
    )
    if dark:
        image = 255 - image
    regions: tuple[GridRegion, ...] = detect_grids(image)
    assert len(regions) == 1
    assert regions[0].corners[0] == pytest.approx((882, 332), abs=6)


def test_multiple_boards_are_separate_candidates() -> None:
    """Expose each verified board so the UI can select one instead of mixing them."""
    image: ImageArray = np.full((1000, 1800, 3), 255, dtype=np.uint8)
    image[180:904, 60:784] = printed_grid()
    image[180:904, 1000:1724] = printed_grid()
    assert len(detect_grids(image)) == 2


def test_small_board_inside_large_image() -> None:
    """Find a board occupying only a small part of a full-page screenshot."""
    image: ImageArray = np.full((2200, 3200, 3), 245, dtype=np.uint8)
    image[1400:1850, 2400:2850] = cv2.resize(printed_grid(), (450, 450))
    cv2.putText(image, "PUZZLES AND NEWS", (100, 150), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 4)
    assert len(detect_grids(image)) == 1


def test_pencil_marks_are_not_original_clues() -> None:
    """Ignore small notes while keeping a normal-sized digit available for OCR."""
    cell: ImageArray = np.full((100, 100, 3), 255, dtype=np.uint8)
    for digit in range(1, 10):
        cv2.putText(
            cell,
            str(digit),
            (10 + (digit - 1) % 3 * 28, 25 + (digit - 1) // 3 * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0),
            1,
        )
    assert digit_patch(cell) is None


def test_native_decode_preserves_image_orientation() -> None:
    """Keep top and bottom rows aligned through ImageIO and the pixel buffer."""
    image: ImageArray = np.full((100, 100, 3), 255, dtype=np.uint8)
    image[:20] = (255, 0, 0)
    restored: ImageArray = decode_image(image_bytes(image))
    assert tuple(restored[0, 0]) == (255, 0, 0)
    assert tuple(restored[-1, 0]) == (255, 255, 255)


@pytest.mark.skipif(os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1", reason="Local Vision runtime")
@pytest.mark.parametrize("perspective", [False, True])
def test_local_recognition_preserves_exact_clues(perspective: bool) -> None:
    """Extract known clues from a whole page and from a simulated tilted paper photo."""
    image: ImageArray = np.full((1200, 1600, 3), 240, dtype=np.uint8)
    board: ImageArray = printed_grid()
    if perspective:
        source: Any = np.asarray([[0, 0], [723, 0], [723, 723], [0, 723]], dtype=np.float32)
        target: Any = np.asarray(
            [[400, 220], [1120, 310], [1060, 1060], [330, 990]], dtype=np.float32
        )
        transform: Any = cv2.getPerspectiveTransform(source, target)
        warped: ImageArray = cv2.warpPerspective(
            board, transform, (1600, 1200), borderValue=(240,) * 3
        )
        image = warped
    else:
        image[220:944, 600:1324] = board
    regions: tuple[GridRegion, ...] = detect_grids(image)
    assert regions
    recognized = recognize_grid(image, regions[0])
    assert recognized.values == tuple(int(digit) for row in ROWS for digit in row)


@pytest.mark.skipif(os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1", reason="Local Vision runtime")
def test_native_font_recognition() -> None:
    """Recognize real macOS printed glyphs as well as OpenCV's prototype font."""
    import AppKit as AK
    from Foundation import NSDictionary, NSString

    AK.NSApplication.sharedApplication()
    native: Any = AK.NSImage.alloc().initWithSize_((724, 724))
    native.lockFocus()
    try:
        AK.NSColor.whiteColor().setFill()
        AK.NSRectFill(AK.NSMakeRect(0, 0, 724, 724))
        AK.NSColor.blackColor().setStroke()
        for index in range(10):
            position: int = 2 + index * 80
            path: Any = AK.NSBezierPath.bezierPath()
            path.moveToPoint_((position, 2))
            path.lineToPoint_((position, 722))
            path.moveToPoint_((2, position))
            path.lineToPoint_((722, position))
            path.setLineWidth_(4 if index % 3 == 0 else 1)
            path.stroke()
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {
                AK.NSFontAttributeName: AK.NSFont.systemFontOfSize_weight_(
                    48, AK.NSFontWeightSemibold
                ),
                AK.NSForegroundColorAttributeName: AK.NSColor.blackColor(),
            }
        )
        for row, digits in enumerate(ROWS):
            for column, digit in enumerate(digits):
                if digit != "0":
                    text: Any = NSString.stringWithString_(digit)
                    measured: Any = text.sizeWithAttributes_(attributes)
                    text.drawAtPoint_withAttributes_(
                        (
                            2 + column * 80 + (80 - measured.width) / 2,
                            724 - 2 - (row + 1) * 80 + (80 - measured.height) / 2,
                        ),
                        attributes,
                    )
    finally:
        native.unlockFocus()
    image: ImageArray = decode_image(bytes(native.TIFFRepresentation()))
    regions: tuple[GridRegion, ...] = detect_grids(image)
    assert regions
    recognized = recognize_grid(image, regions[0])
    assert recognized.values == tuple(int(digit) for row in ROWS for digit in row)


@pytest.mark.skipif(os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1", reason="Local Vision runtime")
def test_bottom_eight_from_colored_screenshot() -> None:
    """Recover the actual printed glyph that Vision misread as '8 g' in the initial layout."""
    path: Path = Path(__file__).parent / "fixtures" / "import-bottom-eight.png"
    patch: ImageArray | None = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert patch is not None
    assert recognize_digit(patch) == (8, False)


@pytest.mark.skipif(os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1", reason="Local Vision runtime")
@pytest.mark.parametrize("size", [None, 320, 480])
def test_thin_digits_from_import_screenshot(size: int | None) -> None:
    """Read every clue and blank, including four thin 8s and four 3s, from a real import."""
    path: Path = Path(__file__).parent / "fixtures" / "import-thin-digits.png"
    image: ImageArray = decode_image(read_image_file(path))
    if size is not None:
        image = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
    height: int
    width: int
    height, width = image.shape[:2]
    region: GridRegion = GridRegion(
        ((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1))
    )
    expected: tuple[str, ...] = (
        "300914005",
        "105006000",
        "960000800",
        "013008400",
        "090432080",
        "002500360",
        "007000096",
        "000600708",
        "600257004",
    )
    recognized = recognize_grid(image, region)
    assert recognized.values == tuple(int(digit) for row in expected for digit in row)
    assert not recognized.uncertain


@pytest.mark.parametrize(
    ("initial", "pair", "four", "expected"),
    [
        ((0, 0.0), (8, 1.0), (8, 1.0), (8, False)),
        ((0, 0.0), (8, 0.75), (8, 1.0), (8, True)),
        ((0, 0.0), (8, 1.0), (3, 1.0), (0, True)),
        ((8, 0.75), (3, 1.0), (3, 1.0), (8, True)),
    ],
)
def test_recognition_rechecks_preserve_uncertainty(
    initial: tuple[int, float],
    pair: tuple[int, float],
    four: tuple[int, float],
    expected: tuple[int, bool],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require agreement and sufficient confidence without overwriting a conflicting reading."""
    from sudoku import import_images

    readings: dict[int, tuple[int, float]] = {3: initial, 2: pair, 4: four}

    def reading(patch: ImageArray, copies: int) -> tuple[int, float]:
        """Supply recognizer evidence independently from the decision being checked."""
        return readings[copies]

    monkeypatch.setattr(import_images, "recognize_repeated_digit", reading)
    assert recognize_digit(np.full((170, 170), 255, dtype=np.uint8)) == expected


def test_compact_patch_preserves_glyph_and_vertical_padding() -> None:
    """Change spacing without thickening, clipping, or inventing ink in a blank patch."""
    patch: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    assert compact_digit_patch(patch) is None
    cv2.putText(patch, "8", (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 4.5, 0, 2)
    original: ImageArray = patch.copy()
    compact: ImageArray | None = compact_digit_patch(patch)
    assert compact is not None
    assert compact.shape[0] == patch.shape[0]
    assert compact.shape[1] < patch.shape[1]
    assert np.count_nonzero(compact < 128) == np.count_nonzero(patch < 128)
    assert np.all(compact[:, :16] == 255)
    assert np.all(compact[:, -16:] == 255)
    assert np.array_equal(patch, original)


@pytest.mark.parametrize(
    ("originals", "compact_pair", "compact_triple", "expected"),
    [
        (((0, 0.0), (0, 0.0), (0, 0.0)), (8, 1.0), (8, 1.0), (8, False)),
        (((0, 0.0), (0, 0.0), (0, 0.0)), (3, 1.0), (3, 1.0), (3, False)),
        (((0, 0.0), (8, 1.0), (0, 0.0)), (8, 1.0), (8, 1.0), (8, False)),
        (((8, 0.75), (0, 0.0), (0, 0.0)), (8, 1.0), (8, 1.0), (8, False)),
        (((0, 0.0), (0, 0.0), (0, 0.0)), (8, 0.75), (8, 1.0), (8, True)),
        (((0, 0.0), (0, 0.0), (0, 0.0)), (8, 1.0), (3, 1.0), (0, True)),
        (((0, 0.0), (0, 0.0), (0, 0.0)), (8, 1.0), (0, 0.0), (0, True)),
        (((3, 0.75), (0, 0.0), (0, 0.0)), (8, 1.0), (8, 1.0), (3, True)),
        (((0, 0.0), (3, 1.0), (0, 0.0)), (8, 1.0), (8, 1.0), (0, True)),
        (((8, 0.75), (3, 1.0), (0, 0.0)), (8, 1.0), (8, 1.0), (8, True)),
    ],
)
def test_compact_recognition_requires_agreement(
    originals: tuple[tuple[int, float], ...],
    compact_pair: tuple[int, float],
    compact_triple: tuple[int, float],
    expected: tuple[int, bool],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover missing 8s and 3s only when repeated compact readings agree with prior evidence."""
    from sudoku import import_images

    patch: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    cv2.putText(patch, "8", (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 4.5, 0, 2)
    readings: dict[int, tuple[int, float]] = dict(zip((3, 2, 4), originals, strict=True))

    def reading(candidate: ImageArray, copies: int) -> tuple[int, float]:
        """Distinguish normal-spacing results from independent compact-layout evidence."""
        if candidate.shape == patch.shape:
            return readings[copies]
        return {2: compact_pair, 3: compact_triple}[copies]

    monkeypatch.setattr(import_images, "recognize_repeated_digit", reading)
    assert recognize_digit(patch) == expected


def test_confident_recognition_avoids_extra_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the normal single-call path for clear digits."""
    reader: Mock = Mock(return_value=(3, 1.0))
    monkeypatch.setattr("sudoku.import_images.recognize_repeated_digit", reader)
    patch: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    assert recognize_digit(patch) == (3, False)
    reader.assert_called_once_with(patch, 3)
