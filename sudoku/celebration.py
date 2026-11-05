# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Draw a short burst of numbered tiles over the solved Sudoku board."""

from dataclasses import dataclass
from math import cos, sin, tau
from random import Random
from time import monotonic
from typing import Any

import AppKit as AK
import objc
from Foundation import NSRunLoop, NSString, NSTimer

from sudoku.model import COMPLETION_RANKS, LEVELS

# Each entry supplies the tile count, launch points, and duration in seconds.
CELEBRATIONS: tuple[tuple[int, int, float], ...] = (
    (14, 1, 0.85),
    (20, 1, 0.95),
    (26, 2, 1.05),
    (34, 2, 1.15),
    (42, 3, 1.27),
    (50, 3, 1.37),
    (60, 4, 1.50),
    (68, 4, 1.60),
    (80, 5, 1.75),
    (92, 6, 1.90),
)
LAUNCH_POINTS: tuple[tuple[float, float], ...] = (
    (0.16, 0.20),
    (0.84, 0.20),
    (0.16, 0.78),
    (0.84, 0.78),
    (0.50, 0.18),
    (0.50, 0.82),
)
TILE_COLORS: tuple[tuple[float, float, float], ...] = (
    (0.07, 0.47, 0.36),
    (0.65, 0.31, 0.07),
    (0.15, 0.38, 0.70),
    (0.63, 0.19, 0.42),
)


def celebration_level(difficulty: str, rank: str | None) -> int:
    """Return one of ten intensities, including difficulty-only legacy celebrations."""
    rank_steps: int = COMPLETION_RANKS.index(rank) if rank is not None else 0
    return 1 + LEVELS.index(difficulty) + 2 * rank_steps


@dataclass(frozen=True)
class Tile:
    """Keep one tile's normalized flight and drawing data for the entire burst."""

    x: float
    y: float
    dx: float
    dy: float
    turn: float
    delay: float
    size: float
    color: Any
    label: Any


class CompletionOverlay(AK.NSView):
    """Paint above the puzzle and alert in a window that passes through mouse input."""

    started: float
    duration: float
    tiles: tuple[Tile, ...]
    timer: Any = None
    overlay_window: Any = None

    def isFlipped(self) -> bool:
        """Use the same top-down coordinate system as the puzzle grid."""
        return True

    @objc.python_method
    def start(self, intensity: int, panel: Any, frame: Any) -> None:
        """Initialize the burst and animate while the native alert is open."""
        count: int
        launches: int
        count, launches, self.duration = CELEBRATIONS[intensity - 1]
        self.tiles = self.make_tiles(intensity, count, launches)
        window: Any = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, AK.NSWindowStyleMaskBorderless, AK.NSBackingStoreBuffered, False
        )
        window.setReleasedWhenClosed_(False)
        window.setOpaque_(False)
        window.setBackgroundColor_(AK.NSColor.clearColor())
        window.setHasShadow_(False)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(panel.level())
        self.setAccessibilityElement_(False)
        self.setClipsToBounds_(True)
        window.setContentView_(self)
        self.overlay_window = window
        self.started = monotonic()
        self.timer = NSTimer.timerWithTimeInterval_repeats_block_(1 / 45, True, self.advance)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self.timer, AK.NSModalPanelRunLoopMode)
        self.setNeedsDisplay_(True)
        panel.addChildWindow_ordered_(window, AK.NSWindowAbove)

    @objc.python_method
    def make_tiles(self, intensity: int, count: int, launches: int) -> tuple[Tile, ...]:
        """Prepare a repeatable mix of digits, launch points, and flight paths."""
        generator: Random = Random(intensity)
        colors: tuple[Any, ...] = tuple(
            AK.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1)
            for red, green, blue in TILE_COLORS
        )
        origins: tuple[tuple[float, float], ...] = (
            ((0.50, 0.18),) if launches == 1 else LAUNCH_POINTS[:launches]
        )
        tiles: list[Tile] = []
        for index in range(count):
            origin: tuple[float, float] = origins[index % launches]
            angle: float = index * tau * 0.381966
            distance: float = generator.uniform(0.12, 0.31)
            tiles.append(
                Tile(
                    origin[0],
                    origin[1],
                    cos(angle) * distance,
                    sin(angle) * distance - 0.07,
                    generator.uniform(-230, 230),
                    generator.uniform(0, 0.24),
                    generator.uniform(0.86, 1.16),
                    colors[index % len(colors)],
                    NSString.stringWithString_(str(index % 9 + 1)),
                )
            )
        return tuple(tiles)

    @objc.python_method
    def advance(self, timer: Any) -> None:
        """Refresh the overlay during the AppKit modal loop."""
        if (
            monotonic() - self.started >= self.duration
            or AK.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
        ):
            self.stop()
            return
        self.setNeedsDisplay_(True)
        self.displayIfNeeded()

    @objc.python_method
    def stop(self) -> None:
        """Release the timer and close the overlay on completion or dismissal."""
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        if self.overlay_window is not None:
            window: Any = self.overlay_window
            self.overlay_window = None
            window.orderOut_(None)
            window.close()

    def drawRect_(self, dirty: Any) -> None:
        """Clear the previous frame and draw over the puzzle and dialog."""
        AK.NSRectFillUsingOperation(dirty, AK.NSCompositingOperationClear)
        elapsed: float = (monotonic() - self.started) / self.duration
        bounds: Any = self.bounds()
        width: float = bounds.size.width
        height: float = bounds.size.height
        for tile in self.tiles:
            progress: float = (elapsed - tile.delay) / (1 - tile.delay)
            if 0 <= progress < 1:
                self.draw_tile(tile, progress, width, height)

    @objc.python_method
    def draw_tile(self, tile: Tile, progress: float, width: float, height: float) -> None:
        """Draw one spinning numbered square with a soft exit."""
        travel: float = 1 - (1 - progress) ** 2
        opacity: float = min(1.0, progress * 12, (1 - progress) * 3)
        size: float = min(24, max(12, width / 24)) * tile.size
        x: float = (tile.x + tile.dx * travel) * width
        y: float = (tile.y + tile.dy * travel + 0.34 * progress**2) * height
        rect: Any = AK.NSMakeRect(-size / 2, -size / 2, size, size)
        attributes: dict[Any, Any] = {
            AK.NSFontAttributeName: AK.NSFont.boldSystemFontOfSize_(size * 0.66),
            AK.NSForegroundColorAttributeName: AK.NSColor.whiteColor().colorWithAlphaComponent_(
                opacity
            ),
        }
        AK.NSGraphicsContext.saveGraphicsState()
        try:
            transform: Any = AK.NSAffineTransform.transform()
            transform.translateXBy_yBy_(x, y)
            transform.rotateByDegrees_(tile.turn * travel)
            transform.concat()
            tile.color.colorWithAlphaComponent_(opacity).setFill()
            AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 2, 2).fill()
            label_size: Any = tile.label.sizeWithAttributes_(attributes)
            tile.label.drawAtPoint_withAttributes_(
                AK.NSMakePoint(-label_size.width / 2, -label_size.height / 2), attributes
            )
        finally:
            AK.NSGraphicsContext.restoreGraphicsState()
