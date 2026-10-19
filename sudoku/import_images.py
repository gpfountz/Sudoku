# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Locate Sudoku grids and recognize printed clues locally with OpenCV and Vision."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import Quartz as Q
import Vision as V
from Foundation import NSData, NSDictionary
from numpy.typing import NDArray

ImageArray = NDArray[Any]
Corners = tuple[tuple[float, float], ...]
BOARD_SIZE: int = 900
MAX_IMAGE_BYTES: int = 128 * 1024 * 1024
IMAGE_SIZE_ERROR: str = "This image is too large. Choose a smaller image or screenshot."


@dataclass(frozen=True)
class GridRegion:
    """Describe a detected or manually adjusted board in source image pixels."""

    corners: Corners
    score: float = 0.0


@dataclass(frozen=True)
class RecognizedGrid:
    """Keep tentative clues and uncertain cells separate from mathematical validation."""

    values: tuple[int, ...]
    uncertain: frozenset[int]
    board: ImageArray


def read_image_file(path: Path) -> bytes:
    """Reject oversized files before allocation and bound reads if the file grows."""
    with path.open("rb") as source:
        if os.fstat(source.fileno()).st_size > MAX_IMAGE_BYTES:
            raise ValueError(IMAGE_SIZE_ERROR)
        data: bytes = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(IMAGE_SIZE_ERROR)
    return data


def native_image(data: bytes) -> Any:
    """Decode an oriented native image, bounding its dimensions before pixel allocation."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(IMAGE_SIZE_ERROR)
    source: Any = Q.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(data, len(data)), None)
    if source is None:
        raise ValueError("Choose a supported image: PNG, JPEG, HEIC, or TIFF.")
    image: Any = Q.CGImageSourceCreateThumbnailAtIndex(
        source,
        0,
        {
            Q.kCGImageSourceCreateThumbnailFromImageAlways: True,
            Q.kCGImageSourceCreateThumbnailWithTransform: True,
            Q.kCGImageSourceThumbnailMaxPixelSize: 4096,
        },
    )
    if image is None:
        raise ValueError("Could not decode this image.")
    return image


def decode_image(data: bytes) -> ImageArray:
    """Convert PNG, JPEG, HEIC, or TIFF data into an upright RGB pixel array."""
    image: Any = native_image(data)
    width: int = Q.CGImageGetWidth(image)
    height: int = Q.CGImageGetHeight(image)
    pixels: bytearray = bytearray(width * height * 4)
    context: Any = Q.CGBitmapContextCreate(
        pixels,
        width,
        height,
        8,
        width * 4,
        Q.CGColorSpaceCreateDeviceRGB(),
        Q.kCGImageAlphaPremultipliedLast,
    )
    Q.CGContextSetRGBFillColor(context, 1, 1, 1, 1)
    Q.CGContextFillRect(context, Q.CGRectMake(0, 0, width, height))
    Q.CGContextDrawImage(context, Q.CGRectMake(0, 0, width, height), image)
    return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()


def image_bytes(image: ImageArray) -> bytes:
    """Encode a temporary PNG for native display or Vision without writing an image file."""
    converted: ImageArray = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image
    success: bool
    encoded: Any
    success, encoded = cv2.imencode(".png", converted)
    if not success:
        raise ValueError("Could not prepare the image")
    return bytes(encoded)


def ordered_corners(points: Any) -> Corners:
    """Order a convex quadrilateral clockwise starting at its top-left corner."""
    array: Any = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center: Any = array.mean(axis=0)
    order: Any = np.argsort(np.arctan2(array[:, 1] - center[1], array[:, 0] - center[0]))
    array = array[order]
    array = np.roll(array, -int(np.argmin(array.sum(axis=1))), axis=0)
    return tuple((float(x), float(y)) for x, y in array)


def warp_board(image: ImageArray, region: GridRegion) -> ImageArray:
    """Rectify four user-visible corners without treating surrounding content as cells."""
    points: Any = np.asarray(region.corners, dtype=np.float32)
    if points.shape != (4, 2) or not cv2.isContourConvex(points.astype(np.int32)):
        raise ValueError("Place the four corners around the board without crossing edges.")
    if abs(cv2.contourArea(points)) < 100:
        raise ValueError("The selected board area is too small.")
    target: Any = np.asarray(((0, 0), (899, 0), (899, 899), (0, 899)), dtype=np.float32)
    transform: Any = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, transform, (BOARD_SIZE, BOARD_SIZE))


def ink_mask(image: ImageArray) -> ImageArray:
    """Normalize light or dark puzzle backgrounds and isolate foreground ink."""
    gray: ImageArray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    if float(np.median(gray)) < 128:
        gray = cv2.bitwise_not(gray)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 10
    )


def line_centers(projection: Any) -> list[float]:
    """Collapse thick grid lines into single measured positions."""
    indices: Any = np.flatnonzero(projection > max(35.0, float(projection.max()) * 0.35))
    if not len(indices):
        return []
    groups: list[Any] = np.split(indices, np.flatnonzero(np.diff(indices) > 2) + 1)
    return [float(group.mean()) for group in groups]


def grid_score(board: ImageArray) -> float:
    """Require regular horizontal and vertical cell divisions rather than just a rectangle."""
    mask: ImageArray = ink_mask(board)
    scores: list[float] = []
    for vertical in (False, True):
        kernel: Any = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 65) if vertical else (65, 1))
        lines: ImageArray = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        projection: Any = np.count_nonzero(lines, axis=0 if vertical else 1)
        positions: list[float] = line_centers(projection)
        if not 8 <= len(positions) <= 12:
            return 0.0
        gaps: Any = np.diff(positions)
        regular: float = float(np.mean((gaps > 65) & (gaps < 130)))
        if regular < 0.75:
            return 0.0
        scores.append(regular)
    return min(scores)


def detect_grids(image: ImageArray) -> tuple[GridRegion, ...]:
    """Find verified Sudoku grids anywhere in a screenshot or clear printed page photo."""
    height, width = image.shape[:2]
    scale: float = min(1.0, 1500 / max(height, width))
    small: ImageArray = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
    mask: ImageArray = ink_mask(small)
    contours: Any
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[GridRegion] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:250]:
        if cv2.contourArea(contour) < 10000:
            continue
        polygon: Any = cv2.approxPolyDP(contour, cv2.arcLength(contour, True) * 0.02, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        corners: Corners = ordered_corners(polygon / scale)
        points: Any = np.asarray(corners)
        if any(np.linalg.norm(points[i] - points[(i + 1) % 4]) < 100 for i in range(4)):
            continue
        if any(
            float(np.max(np.linalg.norm(points - np.asarray(old.corners), axis=1)))
            < max(width, height) * 0.025
            for old in candidates
        ):
            continue
        region: GridRegion = GridRegion(corners)
        score: float = grid_score(warp_board(image, region))
        if score:
            candidates.append(GridRegion(corners, score))
        if len(candidates) == 8:
            break
    return tuple(sorted(candidates, key=lambda region: region.score, reverse=True))


def digit_patch(cell: ImageArray) -> ImageArray | None:
    """Remove borders and small pencil marks before recognizing a substantial digit."""
    inset: int = max(2, cell.shape[0] // 10)
    inner: ImageArray = cell[inset:-inset, inset:-inset]
    mask: ImageArray = ink_mask(inner)
    count: int
    labels: Any
    stats: Any
    centroids: Any
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    components: list[int] = [
        i
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_HEIGHT] >= cell.shape[0] * 0.28
        and stats[i, cv2.CC_STAT_AREA] >= cell.shape[0] ** 2 * 0.006
        and 0.12 * inner.shape[1] < centroids[i, 0] < 0.88 * inner.shape[1]
    ]
    if not components:
        return None
    largest: int = max(components, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    x, y, width, height = stats[largest, :4]
    glyph: ImageArray = 255 - mask[y : y + height, x : x + width]
    factor: float = 110 / height
    glyph = cv2.resize(glyph, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    result: ImageArray = np.full((170, 170), 255, dtype=np.uint8)
    if glyph.shape[1] > 150:
        return result
    left: int = (170 - glyph.shape[1]) // 2
    result[30 : 30 + glyph.shape[0], left : left + glyph.shape[1]] = glyph
    return result


def recognize_repeated_digit(patch: ImageArray, copies: int) -> tuple[int, float]:
    """Read a repeated source glyph, requiring all copies to agree on one digit."""
    # Vision's text detector can miss an isolated glyph. Repeating the same patch
    # provides a line of text without introducing any new source information.
    anchor: ImageArray = np.full((170, 240), 255, dtype=np.uint8)
    cv2.putText(anchor, "AB", (8, 140), cv2.FONT_HERSHEY_SIMPLEX, 4.5, 0, 4, cv2.LINE_AA)
    line: ImageArray = np.concatenate((anchor, *([patch] * copies)), axis=1)
    request: Any = V.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(V.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    request.setRecognitionLanguages_(["en-US"])
    handler: Any = V.VNImageRequestHandler.alloc().initWithCGImage_options_(
        native_image(image_bytes(line)), NSDictionary.dictionary()
    )
    success: bool
    error: Any
    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise ValueError(f"Local text recognition failed: {error}")
    for observation in request.results() or ():
        for candidate in observation.topCandidates_(3):
            text: str = "".join(str(candidate.string()).split())
            # Vision occasionally emits a Cyrillic look-alike for the anchor's B.
            # Ignore only its two letters; the remaining repeated digits must agree.
            if len(text) > 2 and text[:2].isalpha():
                text = text[2:]
            if (
                len(text) == copies
                and text[0] in "123456789"
                and all(character == text[0] for character in text)
            ):
                return int(text[0]), float(candidate.confidence())
    return 0, 0.0


def compact_digit_patch(patch: ImageArray) -> ImageArray | None:
    """Reduce horizontal whitespace so repeated thin digits form one detectable text line."""
    columns: Any = np.flatnonzero(np.any(patch < 128, axis=0))
    if not len(columns):
        return None
    left: int = max(0, int(columns[0]) - 16)
    right: int = min(patch.shape[1], int(columns[-1]) + 17)
    return patch[:, left:right]


def recognize_digit(patch: ImageArray) -> tuple[int, bool]:
    """Retry inconclusive OCR with varied counts and spacing, preserving conflicting readings."""
    value: int
    confidence: float
    value, confidence = recognize_repeated_digit(patch, 3)
    if value and confidence >= 0.85:
        return value, False
    first: int
    first_confidence: float
    second: int
    second_confidence: float
    first, first_confidence = recognize_repeated_digit(patch, 2)
    second, second_confidence = recognize_repeated_digit(patch, 4)
    if first and first == second and (not value or value == first):
        return first, min(first_confidence, second_confidence) < 0.85
    readings: set[int] = {digit for digit in (value, first, second) if digit}
    if len(readings) > 1:
        return value, True
    compact: ImageArray | None = compact_digit_patch(patch)
    if compact is None:
        return value, True
    first, first_confidence = recognize_repeated_digit(compact, 2)
    second, second_confidence = recognize_repeated_digit(compact, 3)
    if first and first == second and (not readings or first in readings):
        return first, min(first_confidence, second_confidence) < 0.85
    return value, True


def recognize_grid(
    image: ImageArray, region: GridRegion, cancelled: Callable[[], bool] = lambda: False
) -> RecognizedGrid:
    """Recognize each cell separately so page text never becomes puzzle clues."""
    board: ImageArray = warp_board(image, region)
    values: list[int] = []
    uncertain: set[int] = set()
    for index in range(81):
        if cancelled():
            raise ValueError("Import cancelled")
        row: int = index // 9
        column: int = index % 9
        patch: ImageArray | None = digit_patch(
            board[row * 100 : (row + 1) * 100, column * 100 : (column + 1) * 100]
        )
        value: int = 0
        needs_review: bool = False
        if patch is not None:
            value, needs_review = recognize_digit(patch)
        values.append(value)
        if needs_review:
            uncertain.add(index)
    return RecognizedGrid(tuple(values), frozenset(uncertain), board)
