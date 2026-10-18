# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native, editable puzzle import review with cancellable background recognition."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import AppKit as AK
import objc
from Foundation import NSData, NSDictionary, NSString, NSTimer

from sudoku.catalog import Catalog, load_catalog
from sudoku.controls import (
    ThemePopUpButton,
    apply_action_theme,
    apply_native_accent,
    button_title,
)
from sudoku.engine import conflicts
from sudoku.import_images import (
    Corners,
    GridRegion,
    ImageArray,
    RecognizedGrid,
    decode_image,
    detect_grids,
    image_bytes,
    read_image_file,
    recognize_grid,
)
from sudoku.model import LEVELS, Puzzle
from sudoku.puzzle_import import ValidatedImport, parse_grid, validate_import
from sudoku.storage import Store
from sudoku.theme import DEFAULT_THEME, Theme


def display_image(pixels: ImageArray) -> Any:
    """Create a transient native image for source comparison without saving it."""
    data: bytes = image_bytes(pixels)
    return AK.NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))


class SourceImageView(AK.NSView):
    """Draw the complete source and let the user drag its four board corners."""

    owner: Any
    image: Any = None
    dragging_corner: int | None = None

    def isFlipped(self) -> bool:
        """Use image-style coordinates from top to bottom."""
        return True

    @objc.python_method
    def image_rect(self) -> Any:
        """Fit the full source while retaining a consistent mapping for corner editing."""
        if self.image is None:
            return self.bounds()
        size: Any = self.image.size()
        factor: float = min(
            self.bounds().size.width / size.width, self.bounds().size.height / size.height
        )
        width: float = size.width * factor
        height: float = size.height * factor
        return AK.NSMakeRect(
            (self.bounds().size.width - width) / 2,
            (self.bounds().size.height - height) / 2,
            width,
            height,
        )

    @objc.python_method
    def corner_points(self) -> list[tuple[float, float]]:
        """Map the selected board from source pixels to visible handle centers."""
        rect: Any = self.image_rect()
        if self.owner.image is None:
            return []
        height, width = self.owner.image.shape[:2]
        return [
            (
                rect.origin.x + x / width * rect.size.width,
                rect.origin.y + y / height * rect.size.height,
            )
            for x, y in self.owner.corners
        ]

    def drawRect_(self, dirty: Any) -> None:
        """Paint the source image and numbered corner handles."""
        self.owner.theme.controls.background.setFill()
        AK.NSRectFill(self.bounds())
        if self.image is None:
            return
        self.image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
            self.image_rect(), AK.NSZeroRect, AK.NSCompositingOperationSourceOver, 1, True, None
        )
        points: list[tuple[float, float]] = self.corner_points()
        if len(points) != 4:
            return
        self.owner.theme.accent.setStroke()
        path: Any = AK.NSBezierPath.bezierPath()
        path.moveToPoint_(points[0])
        for point in points[1:]:
            path.lineToPoint_(point)
        path.closePath()
        path.setLineWidth_(2)
        path.stroke()
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {
                AK.NSFontAttributeName: AK.NSFont.boldSystemFontOfSize_(12),
                AK.NSForegroundColorAttributeName: self.owner.theme.controls.selected_text,
            }
        )
        for number, (x, y) in enumerate(points, 1):
            self.owner.theme.accent.setFill()
            AK.NSBezierPath.bezierPathWithOvalInRect_(AK.NSMakeRect(x - 10, y - 10, 20, 20)).fill()
            text: Any = NSString.stringWithString_(str(number))
            measured: Any = text.sizeWithAttributes_(attributes)
            text.drawAtPoint_withAttributes_(
                (x - measured.width / 2, y - measured.height / 2), attributes
            )

    def mouseDown_(self, event: Any) -> None:
        """Select a nearby corner for manual correction."""
        point: Any = self.convertPoint_fromView_(event.locationInWindow(), None)
        self.dragging_corner = next(
            (
                index
                for index, (x, y) in enumerate(self.corner_points())
                if (x - point.x) ** 2 + (y - point.y) ** 2 < 20**2
            ),
            None,
        )

    def mouseDragged_(self, event: Any) -> None:
        """Move a selected corner within the image, without running OCR during the drag."""
        if self.dragging_corner is None or self.owner.image is None:
            return
        point: Any = self.convertPoint_fromView_(event.locationInWindow(), None)
        rect: Any = self.image_rect()
        height, width = self.owner.image.shape[:2]
        corners: list[tuple[float, float]] = list(self.owner.corners)
        corners[self.dragging_corner] = (
            max(0, min(width - 1, (point.x - rect.origin.x) / rect.size.width * width)),
            max(0, min(height - 1, (point.y - rect.origin.y) / rect.size.height * height)),
        )
        self.owner.corners = tuple(corners)
        self.owner.invalidate_review()
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event: Any) -> None:
        """Retain adjusted corners until the user asks to read this board."""
        self.dragging_corner = None


class ReviewCell(AK.NSAccessibilityElement):
    """Expose each editable clue to accessibility tools."""

    owner: Any
    index: int

    def accessibilityPerformPress(self) -> bool:
        """Select the clue through the same review path as mouse and keyboard."""
        self.owner.select_cell(self.index)
        return True


class ClueGrid(AK.NSView):
    """Draw and edit all clues, including cells recognition considered empty."""

    owner: Any

    def isFlipped(self) -> bool:
        """Arrange Sudoku rows from top to bottom."""
        return True

    def acceptsFirstResponder(self) -> bool:
        """Allow arrows, digits, and Delete to review clues directly."""
        return True

    def drawRect_(self, dirty: Any) -> None:
        """Show tentative digits, conflicts, uncertainty, and keyboard selection."""
        size: float = self.bounds().size.width / 9
        theme: Theme = self.owner.theme
        theme.board.background.draw(self.bounds())
        errors: set[int] = conflicts(self.owner.values)
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {
                AK.NSFontAttributeName: AK.NSFont.systemFontOfSize_weight_(
                    size * 0.58, AK.NSFontWeightSemibold
                ),
                AK.NSForegroundColorAttributeName: theme.text,
            }
        )
        for index, value in enumerate(self.owner.values):
            rect: Any = AK.NSMakeRect(index % 9 * size, index // 9 * size, size, size)
            if index in self.owner.uncertain:
                theme.hints.focus_fill.resolve().setFill()
                AK.NSRectFill(rect)
            if index in errors:
                theme.hints.error_fill.resolve().setFill()
                AK.NSRectFill(rect)
            if value:
                text: Any = NSString.stringWithString_(str(value))
                measured: Any = text.sizeWithAttributes_(attributes)
                text.drawAtPoint_withAttributes_(
                    (
                        rect.origin.x + (size - measured.width) / 2,
                        rect.origin.y + (size - measured.height) / 2,
                    ),
                    attributes,
                )
            if index in self.owner.uncertain:
                theme.hints.evidence_stroke.setStroke()
                marker: Any = AK.NSBezierPath.bezierPathWithRect_(AK.NSInsetRect(rect, 4, 4))
                marker.setLineWidth_(1)
                marker.stroke()
            if index == self.owner.selected:
                theme.accent.setStroke()
                outline: Any = AK.NSBezierPath.bezierPathWithRect_(AK.NSInsetRect(rect, 2, 2))
                outline.setLineWidth_(2)
                outline.stroke()
        for step in range(10):
            (
                theme.board.major_grid if step % 3 == 0 else theme.board.minor_grid
            ).resolve().setStroke()
            line: Any = AK.NSBezierPath.bezierPath()
            line.moveToPoint_((step * size, 0))
            line.lineToPoint_((step * size, 9 * size))
            line.moveToPoint_((0, step * size))
            line.lineToPoint_((9 * size, step * size))
            line.setLineWidth_(2 if step % 3 == 0 else 0.5)
            line.stroke()

    def mouseDown_(self, event: Any) -> None:
        """Select any clue for correction or comparison with its image cell."""
        point: Any = self.convertPoint_fromView_(event.locationInWindow(), None)
        size: float = self.bounds().size.width / 9
        index: int = int(point.y / size) * 9 + int(point.x / size)
        if 0 <= point.x < size * 9 and 0 <= point.y < size * 9:
            self.owner.select_cell(index)

    def keyDown_(self, event: Any) -> None:
        """Review with arrows and edit digits without treating them as game answers."""
        key: str = str(event.charactersIgnoringModifiers() or "")
        deltas: dict[int, int] = {123: -1, 124: 1, 125: 9, 126: -9}
        if event.keyCode() in deltas:
            self.owner.select_cell(max(0, min(80, self.owner.selected + deltas[event.keyCode()])))
        elif len(key) == 1 and key in "123456789":
            self.owner.edit_cell(int(key))
        elif event.keyCode() in (51, 117) or key in ("0", "."):
            self.owner.edit_cell(0)
        else:
            objc.super(ClueGrid, self).keyDown_(event)

    def accessibilityChildren(self) -> list[Any]:
        """Describe clues and flagged cells using accessible, selectable elements."""
        children: list[Any] = []
        for index, value in enumerate(self.owner.values):
            cell: Any = ReviewCell.alloc().init()
            cell.owner = self.owner
            cell.index = index
            cell.setAccessibilityRole_(AK.NSAccessibilityButtonRole)
            cell.setAccessibilityLabel_(
                f"Row {index // 9 + 1}, column {index % 9 + 1}, "
                f"{value if value else 'empty'}"
                + (", needs review" if index in self.owner.uncertain else "")
            )
            children.append(cell)
        return children


class ImportContentView(AK.NSView):
    """Keep the review usable when the native window is resized."""

    owner: Any

    def resizeSubviewsWithOldSize_(self, size: Any) -> None:
        """Reflow the source, review board, and actions within the content bounds."""
        if hasattr(self, "owner"):
            self.owner.layout()


class ImportWindow(AK.NSObject):
    """Own transient image data and coordinate recognition, review, and the Play action."""

    store: Store
    catalog: Catalog
    catalog_match: Puzzle | None
    play: Callable[[ValidatedImport, str], bool]
    window: Any
    content: Any
    controls: dict[str, Any]
    source: Any
    grid: Any
    image: ImageArray | None
    board_image: ImageArray | None
    regions: tuple[GridRegion, ...]
    corners: Corners
    values: list[int]
    uncertain: set[int]
    selected: int
    difficulty: str
    saved_givens: tuple[int, ...] | None
    validated: ValidatedImport | None
    executor: ThreadPoolExecutor
    future: Future[Any] | None
    cancelled: Event
    finished: Callable[[Any], None]
    timer: Any
    closed: bool
    theme: Theme = DEFAULT_THEME

    @objc.python_method
    def setup(self, store: Store, play: Callable[[ValidatedImport, str], bool]) -> None:
        """Build an independent native review window without touching the current game."""
        self.store = store
        self.catalog = store.players.catalog if store.players is not None else load_catalog()
        self.catalog_match = None
        self.play = play
        self.image = self.board_image = None
        self.regions = ()
        self.corners = ()
        self.values = [0] * 81
        self.uncertain = set()
        self.selected = 0
        self.validated = None
        self.closed = False
        self.future = None
        self.cancelled = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="puzzle-import")
        self.controls = {}
        self.window = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AK.NSMakeRect(0, 0, 1100, 720),
            AK.NSWindowStyleMaskTitled
            | AK.NSWindowStyleMaskClosable
            | AK.NSWindowStyleMaskResizable,
            AK.NSBackingStoreBuffered,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("Import Puzzle")
        self.window.setContentMinSize_((1000, 690))
        self.window.setDelegate_(self)
        self.content = ImportContentView.alloc().initWithFrame_(self.window.contentView().bounds())
        self.content.owner = self
        self.window.setContentView_(self.content)
        self.source = SourceImageView.alloc().initWithFrame_(AK.NSZeroRect)
        self.source.owner = self
        self.source.setAccessibilityLabel_("Source image with adjustable board corners")
        self.grid = ClueGrid.alloc().initWithFrame_(AK.NSZeroRect)
        self.grid.owner = self
        self.grid.setAccessibilityElement_(False)
        self.content.addSubview_(self.source)
        self.content.addSubview_(self.grid)
        for key, title, action in (
            ("clipboard", "Read Clipboard", "readClipboard:"),
            ("file", "Choose Image File…", "chooseFile:"),
            ("read", "Read This Board", "readBoard:"),
            ("rotate", "Rotate Board", "rotateBoard:"),
            ("clear", "Clear", "clearCell:"),
            ("cancel", "Cancel", "cancel:"),
            ("play", "Play", "playPuzzle:"),
        ):
            self.add_button(key, title, action)
        self.controls["play"].setKeyEquivalent_("\r")
        self.controls["cancel"].setKeyEquivalent_("\x1b")
        for digit in range(1, 10):
            button: Any = self.add_button(f"digit{digit}", str(digit), "digit:")
            button.setTag_(digit)
            button.setAccessibilityLabel_(f"Set clue to {digit}")
        for key, title in (
            ("source_label", "Choose an image or read the clipboard."),
            ("status", "Review the original clues. Difficulty defaults to Medium."),
            ("cell_label", "Selected source cell"),
            ("difficulty_label", "Difficulty"),
        ):
            label: Any = AK.NSTextField.wrappingLabelWithString_(title)
            self.controls[key] = label
            self.content.addSubview_(label)
        popup: Any = ThemePopUpButton.alloc().initWithFrame_pullsDown_(AK.NSZeroRect, False)
        popup.addItemWithTitle_("Detected board")
        popup.setTarget_(self)
        popup.setAction_("regionChanged:")
        popup.setAccessibilityLabel_("Detected puzzle board")
        self.controls["regions"] = popup
        self.content.addSubview_(popup)
        for index, level in enumerate(LEVELS):
            button = self.add_button(f"difficulty_{level}", level, "difficultyChanged:")
            button.setButtonType_(AK.NSButtonTypePushOnPushOff)
            button.setTag_(index)
            button.setAccessibilityLabel_(f"Imported puzzle difficulty: {level}")
        self.reset_difficulty()
        zoom: Any = AK.NSImageView.alloc().initWithFrame_(AK.NSZeroRect)
        zoom.setImageScaling_(AK.NSImageScaleProportionallyUpOrDown)
        zoom.setAccessibilityLabel_("Enlarged source cell")
        self.controls["zoom"] = zoom
        self.content.addSubview_(zoom)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1, self, "poll:", None, True
        )
        self.layout()
        self.update_play()
        self.window.center()

    @objc.python_method
    def apply_theme(self, theme: Theme, appearance: Any = None) -> None:
        """Update native controls and review drawings while preserving the in-progress import."""
        self.theme = theme
        self.window.setAppearance_(appearance)
        self.window.setBackgroundColor_(
            theme.window_background or AK.NSColor.windowBackgroundColor()
        )
        for key, control in self.controls.items():
            if isinstance(control, ThemePopUpButton):
                control.apply_theme(theme)
            elif isinstance(control, AK.NSButton):
                apply_action_theme(control, theme)
                apply_native_accent(control, theme)
                if key.startswith("difficulty_"):
                    control.setAttributedTitle_(
                        button_title(
                            control,
                            theme.controls.selected_text if control.state() else theme.text,
                        )
                    )
            elif isinstance(control, AK.NSTextField):
                control.setTextColor_(
                    theme.text if key == "difficulty_label" else theme.secondary_text
                )
        self.source.setNeedsDisplay_(True)
        self.grid.setNeedsDisplay_(True)

    @objc.python_method
    def add_button(self, key: str, title: str, action: str) -> Any:
        """Create a labeled native action owned by this review window."""
        button: Any = AK.NSButton.buttonWithTitle_target_action_(title, self, action)
        button.setBezelStyle_(AK.NSBezelStyleRounded)
        self.controls[key] = button
        self.content.addSubview_(button)
        return button

    @objc.python_method
    def layout(self) -> None:
        """Fit both comparison columns and editing controls without clipping actions."""
        if not self.controls or "zoom" not in self.controls:
            return
        width: float = self.content.bounds().size.width
        height: float = self.content.bounds().size.height
        left: float = (width - 60) / 2
        right: float = left + 40
        side: float = min(left, height - 280)
        bottom: float = height - 65 - side
        self.source.setFrame_(AK.NSMakeRect(20, 205, left, height - 335))
        self.grid.setFrame_(AK.NSMakeRect(right, bottom, side, side))
        frames: dict[str, tuple[float, float, float, float]] = {
            "clipboard": (20, height - 52, 150, 32),
            "file": (180, height - 52, 175, 32),
            "source_label": (20, height - 90, left, 30),
            "regions": (20, height - 125, 150, 28),
            "read": (180, height - 125, 140, 28),
            "rotate": (330, height - 125, 130, 28),
            "zoom": (20, 55, 140, 140),
            "cell_label": (180, 80, left - 160, 100),
            "status": (right, bottom - 98, left, 46),
            "difficulty_label": (right, 95, 90, 20),
            "play": (width - 110, 20, 90, 32),
            "cancel": (width - 210, 20, 90, 32),
            "clear": (right + 9 * 39, bottom - 45, 75, 30),
        }
        for digit in range(1, 10):
            frames[f"digit{digit}"] = (right + (digit - 1) * 39, bottom - 45, 36, 30)
        difficulty_width: float = (left - 5 * 5) / len(LEVELS)
        for index, level in enumerate(LEVELS):
            frames[f"difficulty_{level}"] = (
                right + index * (difficulty_width + 5),
                60,
                difficulty_width,
                32,
            )
        for key, frame in frames.items():
            self.controls[key].setFrame_(AK.NSMakeRect(*frame))

    @objc.python_method
    def show(self) -> None:
        """Bring the review forward without starting or abandoning a game."""
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.grid)

    @objc.python_method
    def run_job(self, work: Callable[[Event], Any], finished: Callable[[Any], None]) -> None:
        """Replace stale work and present results on the Cocoa main thread."""
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
        self.cancelled = Event()
        self.finished = finished

        def execute(cancelled: Event) -> Any:
            """Drain native temporary objects when background work finishes."""
            with objc.autorelease_pool():
                if cancelled.is_set():
                    raise ValueError("Import cancelled")
                return work(cancelled)

        self.future = self.executor.submit(execute, self.cancelled)
        self.controls["status"].setStringValue_("Working…")
        self.update_play()

    def poll_(self, timer: Any) -> None:
        """Present only the latest background result on the Cocoa main thread."""
        if self.closed or self.future is None or not self.future.done():
            return
        future: Future[Any] = self.future
        self.future = None
        try:
            self.finished(future.result())
        except Exception as error:
            self.controls["status"].setStringValue_(str(error))
        self.update_play()

    def readClipboard_(self, sender: Any) -> None:
        """Read the clipboard once, preferring image content over a supported text grid."""
        pasteboard: Any = AK.NSPasteboard.generalPasteboard()
        for image_type in (AK.NSPasteboardTypePNG, AK.NSPasteboardTypeTIFF):
            encoded: Any = pasteboard.dataForType_(image_type)
            if encoded is not None:
                self.load_image(bytes(encoded))
                return
        images: Any = pasteboard.readObjectsForClasses_options_(
            [AK.NSImage], NSDictionary.dictionary()
        )
        if images:
            data: Any = images[0].TIFFRepresentation()
            if data is not None:
                self.load_image(bytes(data))
                return
        text: str = str(pasteboard.stringForType_(AK.NSPasteboardTypeString) or "")
        try:
            values: tuple[int, ...] = parse_grid(text)
        except ValueError as error:
            self.controls["status"].setStringValue_(str(error))
            return
        self.image = self.board_image = self.source.image = None
        self.corners = ()
        self.regions = ()
        self.values = list(values)
        self.uncertain.clear()
        self.reset_difficulty()
        self.controls["zoom"].setImage_(None)
        self.controls["source_label"].setStringValue_("Text grid from clipboard")
        self.source.setNeedsDisplay_(True)
        self.select_cell(0)
        self.validate()

    def chooseFile_(self, sender: Any) -> None:
        """Navigate to an image through the native macOS file picker."""
        panel: Any = AK.NSOpenPanel.openPanel()
        panel.setTitle_("Choose Puzzle Image")
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "heic", "heif", "tif", "tiff"])
        if panel.runModal() != AK.NSModalResponseOK:
            return
        try:
            data: bytes = read_image_file(Path(str(panel.URL().path())))
        except OSError:
            self.controls["status"].setStringValue_("Could not read that image file.")
            return
        except ValueError as error:
            self.controls["status"].setStringValue_(str(error))
            return
        self.load_image(data)

    @objc.python_method
    def load_image(self, data: bytes) -> None:
        """Decode and locate boards in the background before proposing any clues."""
        self.invalidate_review()
        self.reset_difficulty()

        def locate(cancelled: Event) -> tuple[ImageArray, tuple[GridRegion, ...]]:
            """Decode the selected source and verify candidate grids."""
            image: ImageArray = decode_image(data)
            return image, detect_grids(image)

        self.run_job(locate, self.image_loaded)

    @objc.python_method
    def image_loaded(self, result: tuple[ImageArray, tuple[GridRegion, ...]]) -> None:
        """Show detected boards or provide manual corners when detection finds none."""
        self.image, self.regions = result
        self.source.image = display_image(self.image)
        popup: Any = self.controls["regions"]
        popup.removeAllItems()
        if self.regions:
            popup.addItemsWithTitles_([f"Board {i + 1}" for i in range(len(self.regions))])
            self.corners = self.regions[0].corners
            self.controls["source_label"].setStringValue_(
                "Drag corners to adjust. Select a board if several were found."
            )
            self.readBoard_(None)
        else:
            height, width = self.image.shape[:2]
            self.corners = (
                (width * 0.1, height * 0.1),
                (width * 0.9, height * 0.1),
                (width * 0.9, height * 0.9),
                (width * 0.1, height * 0.9),
            )
            popup.addItemWithTitle_("Manual selection")
            self.controls["source_label"].setStringValue_(
                "No grid found. Drag the four corners around the puzzle, then Read This Board."
            )
            self.controls["status"].setStringValue_("Select the full 9×9 board.")
        self.source.setNeedsDisplay_(True)

    def regionChanged_(self, sender: Any) -> None:
        """Select one detected puzzle without mixing clues from separate boards."""
        index: int = sender.indexOfSelectedItem()
        if 0 <= index < len(self.regions):
            self.corners = self.regions[index].corners
            self.reset_difficulty()
            self.source.setNeedsDisplay_(True)
            self.readBoard_(None)

    def readBoard_(self, sender: Any) -> None:
        """Recognize only the current detected or adjusted board region."""
        if self.image is None or len(self.corners) != 4:
            return
        self.invalidate_review()
        image: ImageArray = self.image
        region: GridRegion = GridRegion(self.corners)
        self.run_job(
            lambda cancelled: recognize_grid(image, region, cancelled.is_set), self.board_read
        )

    def rotateBoard_(self, sender: Any) -> None:
        """Rotate the cell mapping by a quarter turn when the printed digits are sideways."""
        if self.image is None or len(self.corners) != 4:
            return
        self.corners = self.corners[1:] + self.corners[:1]
        self.source.setNeedsDisplay_(True)
        self.readBoard_(None)

    @objc.python_method
    def board_read(self, result: RecognizedGrid) -> None:
        """Present all tentative clues and require explicit correction of uncertainty."""
        self.board_image = result.board
        self.values = list(result.values)
        self.uncertain = set(result.uncertain)
        self.select_cell(min(self.uncertain) if self.uncertain else 0)
        self.validate()

    @objc.python_method
    def select_cell(self, index: int) -> None:
        """Select a review cell and enlarge its source patch when available."""
        self.selected = index
        self.grid.setNeedsDisplay_(True)
        if self.board_image is not None:
            row: int = index // 9
            column: int = index % 9
            self.controls["zoom"].setImage_(
                display_image(
                    self.board_image[row * 100 : (row + 1) * 100, column * 100 : (column + 1) * 100]
                )
            )
        self.controls["cell_label"].setStringValue_(
            f"Row {index // 9 + 1}, column {index % 9 + 1}\n"
            + (
                "Needs review. Click a digit to confirm, or Clear for a blank."
                if index in self.uncertain
                else "Compare with the original clue."
            )
        )
        self.window.makeFirstResponder_(self.grid)

    @objc.python_method
    def edit_cell(self, digit: int) -> None:
        """Correct or confirm a clue, then invalidate any stale mathematical result."""
        self.values[self.selected] = digit
        self.uncertain.discard(self.selected)
        self.select_cell(self.selected)
        self.validate()

    def digit_(self, sender: Any) -> None:
        """Set the selected clue from a labeled digit action."""
        self.edit_cell(sender.tag())

    def clearCell_(self, sender: Any) -> None:
        """Confirm that the selected cell contains no original clue."""
        self.edit_cell(0)

    @objc.python_method
    def invalidate_review(self) -> None:
        """Disable Play as soon as source geometry or clues change."""
        self.validated = None
        self.catalog_match = None
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
            self.future = None
        self.update_play()

    @objc.python_method
    def validate(self) -> None:
        """Validate and scan catalog clues on the cancellable background worker."""
        self.validated = None
        self.catalog_match = None
        values: tuple[int, ...] = tuple(self.values)
        self.grid.setNeedsDisplay_(True)

        def review_clues(cancelled: Event) -> tuple[ValidatedImport, Puzzle | None]:
            """Return validated clues and their exact catalog match without changing play data."""
            validated: ValidatedImport = validate_import(values, cancelled=cancelled.is_set)
            return validated, self.catalog.find_givens(values, cancelled.is_set)

        self.run_job(review_clues, self.validation_finished)

    @objc.python_method
    def validation_finished(self, review: tuple[ValidatedImport, Puzzle | None]) -> None:
        """Show prior play status and use the catalog difficulty whenever clues match."""
        result, match = review
        if result.givens != tuple(self.values):
            return
        text: str = "Exactly one solution."
        if match is not None:
            played: bool = self.store.players is not None and self.store.players.has_played(match)
            text = f"Built-in match: {match.identifier} · {match.level}. " + (
                "Already played." if played else "Not played yet."
            )
            self.select_difficulty(match.level)
            self.saved_givens = result.givens
        else:
            text += " No built-in match."
            existing: Puzzle | None = self.store.imported.find_givens(result.givens)
            if existing is not None:
                if self.saved_givens != result.givens:
                    self.select_difficulty(existing.level)
                self.saved_givens = result.givens
                text += f" Already saved as {existing.identifier}."
            elif self.saved_givens is not None:
                self.reset_difficulty()
        self.catalog_match = match
        self.validated = result
        if self.uncertain:
            text += f" {len(self.uncertain)} cells still need review."
        self.controls["status"].setStringValue_(text)

    @objc.python_method
    def reset_difficulty(self) -> None:
        """Select Medium for a new source, board, or clues leaving a saved puzzle."""
        self.catalog_match = None
        self.saved_givens = None
        self.select_difficulty("Medium")

    @objc.python_method
    def select_difficulty(self, level: str) -> None:
        """Select exactly one difficulty button while keeping every level available."""
        self.difficulty = level
        for candidate in LEVELS:
            button: Any = self.controls[f"difficulty_{candidate}"]
            button.setState_(
                AK.NSControlStateValueOn if candidate == level else AK.NSControlStateValueOff
            )
            button.setAttributedTitle_(
                button_title(
                    button,
                    self.theme.controls.selected_text if candidate == level else self.theme.text,
                )
            )

    def difficultyChanged_(self, sender: Any) -> None:
        """Keep catalog difficulty fixed and allow any level for unmatched imports."""
        self.select_difficulty(
            self.catalog_match.level if self.catalog_match is not None else LEVELS[sender.tag()]
        )
        self.update_play()

    @objc.python_method
    def update_play(self) -> None:
        """Enable Play for reviewed clues and lock the difficulty of a built-in match."""
        if "play" not in self.controls:
            return
        for level in LEVELS:
            self.controls[f"difficulty_{level}"].setEnabled_(self.catalog_match is None)
        self.controls["play"].setEnabled_(
            self.future is None
            and self.validated is not None
            and self.validated.givens == tuple(self.values)
            and not self.uncertain
            and self.difficulty in LEVELS
        )
        self.controls["read"].setEnabled_(self.image is not None)
        self.controls["rotate"].setEnabled_(self.image is not None)
        self.controls["regions"].setEnabled_(len(self.regions) > 1)

    def playPuzzle_(self, sender: Any) -> None:
        """Save and start through the app's compensated transition, then discard image data."""
        if self.controls["play"].isEnabled() and self.validated is not None:
            if self.play(self.validated, self.difficulty):
                self.close()

    def cancel_(self, sender: Any) -> None:
        """Discard review data without saving or abandoning the current attempt."""
        self.close()

    def windowShouldClose_(self, sender: Any) -> bool:
        """Release recognition work and image data when the native close button is used."""
        self.release_review()
        return True

    @objc.python_method
    def release_review(self) -> None:
        """Cancel pending work and release transient images without waiting on the UI thread."""
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
            self.future = None
        self.timer.invalidate()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.image = self.board_image = self.source.image = None
        self.controls["zoom"].setImage_(None)
        self.validated = None
        self.regions = ()

    @objc.python_method
    def close(self) -> None:
        """Close the review while keeping the native window alive through its final callbacks."""
        self.release_review()
        self.window.setDelegate_(None)
        self.window.close()
