# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Draw a simple code-defined macOS Sudoku icon with native Cocoa graphics."""

import struct
from pathlib import Path
from typing import Any

import AppKit as AK
from Foundation import NSString


def render_icon(size: int) -> bytes:
    """Render a rounded Sudoku grid directly into a PNG bitmap."""
    bitmap: Any = AK.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(  # noqa: E501
        None, size, size, 8, 4, True, False, AK.NSCalibratedRGBColorSpace, 0, 0
    )
    context: Any = AK.NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    AK.NSGraphicsContext.saveGraphicsState()
    AK.NSGraphicsContext.setCurrentContext_(context)
    scale: float = size / 1024
    transform: Any = AK.NSAffineTransform.transform()
    transform.scaleBy_(scale)
    transform.concat()
    frame: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        AK.NSMakeRect(44, 44, 936, 936), 206, 206
    )
    gradient: Any = AK.NSGradient.alloc().initWithStartingColor_endingColor_(
        AK.NSColor.colorWithSRGBRed_green_blue_alpha_(0.10, 0.37, 0.68, 1),
        AK.NSColor.colorWithSRGBRed_green_blue_alpha_(0.035, 0.12, 0.28, 1),
    )
    gradient.drawInBezierPath_angle_(frame, -90)
    AK.NSColor.whiteColor().colorWithAlphaComponent_(0.10).setFill()
    AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        AK.NSMakeRect(165, 165, 694, 694), 34, 34
    ).fill()
    for step in range(4):
        coordinate: float = 176 + step * 224
        line: Any = AK.NSBezierPath.bezierPath()
        line.setLineWidth_(6)
        line.moveToPoint_((coordinate, 176))
        line.lineToPoint_((coordinate, 848))
        line.moveToPoint_((176, coordinate))
        line.lineToPoint_((848, coordinate))
        AK.NSColor.whiteColor().colorWithAlphaComponent_(0.65).setStroke()
        line.stroke()
    for digit, column, row in ((1, 0, 2), (5, 1, 1), (9, 2, 0)):
        text: Any = NSString.stringWithString_(str(digit))
        attrs: dict[str, Any] = {
            AK.NSFontAttributeName: AK.NSFont.systemFontOfSize_weight_(144, AK.NSFontWeightMedium),
            AK.NSForegroundColorAttributeName: AK.NSColor.whiteColor(),
        }
        measured: Any = text.sizeWithAttributes_(attrs)
        text.drawAtPoint_withAttributes_(
            (
                176 + column * 224 + (224 - measured.width) / 2,
                176 + row * 224 + (224 - measured.height) / 2,
            ),
            attrs,
        )
    AK.NSGraphicsContext.restoreGraphicsState()
    return bytes(bitmap.representationUsingType_properties_(AK.NSBitmapImageFileTypePNG, {}))


def main() -> None:
    """Write a multi-resolution icon resource for the application bundle."""
    directory: Path = Path(__file__).resolve().parents[1] / "resources"
    directory.mkdir(exist_ok=True)
    chunks: list[bytes] = []
    for size, code in ((128, b"ic07"), (256, b"ic08"), (512, b"ic09"), (1024, b"ic10")):
        png: bytes = render_icon(size)
        chunks.append(code + struct.pack(">I", len(png) + 8) + png)
    payload: bytes = b"".join(chunks)
    (directory / "Sudoku.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


if __name__ == "__main__":
    main()
