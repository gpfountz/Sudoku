# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise native clipboard, file selection, review controls, and image disposal."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import AppKit as AK
import pytest
from Foundation import NSURL, NSData, NSDate, NSRunLoop

from sudoku.catalog import Catalog
from sudoku.import_images import Corners, GridRegion, decode_image, image_bytes
from sudoku.import_ui import ImportWindow, display_image
from sudoku.model import LEVELS
from sudoku.puzzle_import import ValidatedImport, validate_import
from sudoku.storage import Store
from sudoku.theme import SolidBackground, theme_for_name
from sudoku.theme_names import THEME_NAMES

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NATIVE_LAYOUT_TESTS") != "1", reason="Native AppKit WindowServer session"
)


class ReferenceSurface(AK.NSView):
    """Render a palette swatch through the same display profile as the review views."""

    color: Any

    def drawRect_(self, dirty: Any) -> None:
        """Paint an opaque reference for comparison with actual native pixels."""
        self.color.setFill()
        AK.NSRectFill(self.bounds())


@pytest.fixture
def review(tmp_path: Path) -> Iterator[Any]:
    """Build an isolated review without a visible window or production data."""
    AK.NSApplication.sharedApplication()
    window: Any = ImportWindow.alloc().init()
    window.setup(Store(tmp_path), Mock(return_value=True))
    yield window
    window.close()


def finish_jobs(review: Any, timeout: float = 15) -> None:
    """Drain native polling until all latest recognition or validation work completes."""
    deadline: Any = NSDate.dateWithTimeIntervalSinceNow_(timeout)
    while review.future is not None and deadline.timeIntervalSinceNow() > 0:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))
        review.poll_(None)
    assert review.future is None, (
        f"Import job still running after {timeout}s: {review.controls['status'].stringValue()}"
    )


def confirm_flagged_clues(review: Any, expected: list[int]) -> None:
    """Confirm each tentative clue through its digit button before Play can enable."""
    pending: set[int] = set(review.uncertain)
    for index in sorted(pending):
        assert not review.controls["play"].isEnabled()
        review.select_cell(index)
        assert "Needs review" in str(review.controls["cell_label"].stringValue())
        review.controls[f"digit{review.values[index]}"].performClick_(None)
        finish_jobs(review)
        pending.remove(index)
        assert review.uncertain == pending
        assert review.values == expected
    assert not review.uncertain
    assert review.controls["play"].isEnabled()


def test_clipboard_reads_directly_and_uses_matched_difficulty(
    review: Any,
    isolated_catalog: Catalog,
) -> None:
    """Read a clipboard grid with no paste step and expose only Cancel and Play as final actions."""
    grid: str = "".join(map(str, isolated_catalog["Easy"][0].givens))
    pasteboard: Any = AK.NSPasteboard.pasteboardWithUniqueName()
    pasteboard.setString_forType_(grid, AK.NSPasteboardTypeString)
    original: Any = AK.NSPasteboard
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(AK, "NSPasteboard", Mock(generalPasteboard=Mock(return_value=pasteboard)))
        review.readClipboard_(None)
    assert AK.NSPasteboard is original
    finish_jobs(review)
    assert review.validated is not None
    assert review.difficulty == "Easy"
    assert "Not played yet" in str(review.controls["status"].stringValue())
    assert all(not review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert review.controls["play"].isEnabled()
    assert "save" not in review.controls
    assert "save_and_play" not in review.controls
    assert not (review.store.directory / "imported.sqlite3").exists()
    validated: ValidatedImport = review.validated
    review.playPuzzle_(None)
    review.play.assert_called_once_with(validated, "Easy")
    assert review.closed
    assert review.image is None


@pytest.mark.parametrize("flagged_count", [1, 3])
def test_uncertain_cell_must_be_corrected_or_confirmed(
    review: Any, isolated_catalog: Catalog, flagged_count: int
) -> None:
    """Do not enable Play while a flagged digit has only mathematical validation."""
    clues: tuple[int, ...] = isolated_catalog["Easy"][0].givens
    review.values = list(clues)
    review.uncertain = {index for index, digit in enumerate(clues) if digit}
    review.uncertain = set(sorted(review.uncertain)[:flagged_count])
    review.validated = validate_import(clues)
    review.update_play()
    assert not review.controls["play"].isEnabled()
    assert len(review.uncertain) == flagged_count
    confirm_flagged_clues(review, list(clues))


@pytest.mark.parametrize("played", [False, True])
def test_builtin_match_reports_prior_play_and_locks_level(
    review: Any, isolated_catalog: Catalog, played: bool
) -> None:
    """Explain the built-in identity and prior play before starting the reviewed puzzle."""
    review.store.load_game(isolated_catalog)
    puzzle = isolated_catalog["Extreme"][-1]
    if played:
        review.store.start_replay(puzzle.identifier)
    review.values = list(puzzle.givens)
    review.validate()
    finish_jobs(review)
    status: str = str(review.controls["status"].stringValue())
    assert puzzle.identifier in status
    assert "Extreme" in status
    assert ("Already played." if played else "Not played yet.") in status
    assert review.difficulty == "Extreme"
    assert all(not review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert review.controls["play"].isEnabled()
    assert not review.store.imported.path.exists()


def test_editing_builtin_match_restores_import_difficulty(
    review: Any, isolated_catalog: Catalog
) -> None:
    """Clear a stale built-in identity when a clue edit produces a different puzzle."""
    puzzle = isolated_catalog["Extreme"][-1]
    review.values = list(puzzle.givens)
    review.validate()
    finish_jobs(review)
    review.selected = review.values.index(0)
    review.edit_cell(puzzle.solution[review.selected])
    finish_jobs(review)
    assert review.catalog_match is None
    assert "No built-in match" in str(review.controls["status"].stringValue())
    assert review.difficulty == "Medium"
    assert all(review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert review.controls["play"].isEnabled()


def test_cancel_file_picker_leaves_review_unchanged(
    review: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use a native file panel without handling dropped files or changing cancelled review data."""
    panel: Any = Mock()
    panel.runModal.return_value = AK.NSModalResponseCancel
    monkeypatch.setattr(AK, "NSOpenPanel", Mock(openPanel=Mock(return_value=panel)))
    review.chooseFile_(None)
    panel.setCanChooseDirectories_.assert_called_once_with(False)
    panel.setAllowsMultipleSelection_.assert_called_once_with(False)
    assert review.image is None
    assert review.values == [0] * 81
    review.play.assert_not_called()


@pytest.mark.parametrize("size", [(1000, 690), (1100, 720), (1400, 900)])
def test_review_layout_keeps_controls_inside_window(review: Any, size: tuple[int, int]) -> None:
    """Keep file actions, clue controls, status, and Play visible at every supported size."""
    review.window.setContentSize_(size)
    review.layout()
    for control in [*review.controls.values(), review.grid, review.source]:
        assert AK.NSContainsRect(review.content.bounds(), control.frame())
    difficulty_controls: list[Any] = [review.controls[f"difficulty_{level}"] for level in LEVELS]
    for index, button in enumerate(difficulty_controls):
        assert not AK.NSIntersectsRect(review.controls["status"].frame(), button.frame())
        assert not AK.NSIntersectsRect(review.controls["difficulty_label"].frame(), button.frame())
        assert not AK.NSIntersectsRect(review.controls["cancel"].frame(), button.frame())
        assert not AK.NSIntersectsRect(review.controls["play"].frame(), button.frame())
        assert button.frame().size.width >= button.intrinsicContentSize().width
        for other in difficulty_controls[index + 1 :]:
            assert not AK.NSIntersectsRect(button.frame(), other.frame())
    assert not AK.NSIntersectsRect(
        review.controls["status"].frame(), review.controls["difficulty_label"].frame()
    )


def test_empty_clipboard_does_not_start_or_abandon(
    review: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report unsupported clipboard content while leaving the application callback untouched."""
    pasteboard: Any = AK.NSPasteboard.pasteboardWithUniqueName()
    monkeypatch.setattr(AK, "NSPasteboard", Mock(generalPasteboard=Mock(return_value=pasteboard)))
    review.readClipboard_(None)
    assert "Copy an image" in str(review.controls["status"].stringValue())
    review.play.assert_not_called()
    assert not review.controls["play"].isEnabled()


def test_image_clipboard_precedes_text_and_is_discarded(
    review: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prefer clipboard image data and retain no image after cancellation."""
    import numpy as np

    image: Any = np.full((100, 100, 3), 255, dtype=np.uint8)
    native: Any = display_image(image)
    pasteboard: Any = Mock()
    pasteboard.dataForType_.return_value = None
    pasteboard.readObjectsForClasses_options_.return_value = [native]
    pasteboard.stringForType_.return_value = "unsupported"
    monkeypatch.setattr(AK, "NSPasteboard", Mock(generalPasteboard=Mock(return_value=pasteboard)))
    review.load_image = Mock()
    review.readClipboard_(None)
    review.load_image.assert_called_once()
    pasteboard.stringForType_.assert_not_called()
    review.image = decode_image(image_bytes(image))
    review.corners = GridRegion(((0, 0), (99, 0), (99, 99), (0, 99))).corners
    review.cancel_(None)
    assert review.image is None
    assert review.board_image is None


def test_clipboard_and_file_pass_identical_image_bytes(
    review: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep original PNG bytes through both entry points instead of rendering a clipboard copy."""
    import numpy as np

    data: bytes = image_bytes(np.full((100, 100, 3), 255, dtype=np.uint8))
    pasteboard: Any = AK.NSPasteboard.pasteboardWithUniqueName()
    pasteboard.setData_forType_(
        NSData.dataWithBytes_length_(data, len(data)), AK.NSPasteboardTypePNG
    )
    pasteboard.setString_forType_("ignored text", AK.NSPasteboardTypeString)
    monkeypatch.setattr(AK, "NSPasteboard", Mock(generalPasteboard=Mock(return_value=pasteboard)))
    review.load_image = Mock()
    review.readClipboard_(None)
    review.load_image.assert_called_once_with(data)
    review.load_image.reset_mock()
    path: Path = tmp_path / "puzzle.png"
    path.write_bytes(data)
    panel: Any = Mock()
    panel.runModal.return_value = AK.NSModalResponseOK
    panel.URL.return_value = NSURL.fileURLWithPath_(str(path))
    monkeypatch.setattr(AK, "NSOpenPanel", Mock(openPanel=Mock(return_value=panel)))
    review.chooseFile_(None)
    review.load_image.assert_called_once_with(data)


@pytest.mark.parametrize("entry", ["clipboard", "file"])
def test_thin_digits_reach_review_from_clipboard_and_file(
    review: Any, monkeypatch: pytest.MonkeyPatch, entry: str, modern_vision_baseline: bool
) -> None:
    """Recover the screenshot's missed 8s through both real image-loading and OCR paths."""
    path: Path = Path(__file__).parent / "fixtures" / "import-thin-digits.png"
    data: bytes = path.read_bytes()
    if entry == "clipboard":
        pasteboard: Any = AK.NSPasteboard.pasteboardWithUniqueName()
        pasteboard.setData_forType_(
            NSData.dataWithBytes_length_(data, len(data)), AK.NSPasteboardTypePNG
        )
        monkeypatch.setattr(
            AK, "NSPasteboard", Mock(generalPasteboard=Mock(return_value=pasteboard))
        )
        review.readClipboard_(None)
    else:
        panel: Any = Mock()
        panel.runModal.return_value = AK.NSModalResponseOK
        panel.URL.return_value = NSURL.fileURLWithPath_(str(path))
        monkeypatch.setattr(AK, "NSOpenPanel", Mock(openPanel=Mock(return_value=panel)))
        review.chooseFile_(None)
    # The Intel trace measured up to three seconds per clue, including retries.
    # Bound this real-OCR integration wait separately from ordinary UI jobs.
    finish_jobs(review, timeout=180)
    # The fixture retains the screenshot's corner handles. Select the original
    # board bounds explicitly, just as a user adjusts the four import corners.
    height: int
    width: int
    height, width = review.image.shape[:2]
    review.corners = ((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1))
    review.readBoard_(None)
    finish_jobs(review, timeout=180)
    expected: str = (
        "300914005105006000960000800013008400090432080002500360007000096000600708600257004"
    )
    assert review.values == list(map(int, expected))
    if modern_vision_baseline:
        assert not review.uncertain
    assert review.validated is not None
    confirm_flagged_clues(review, list(map(int, expected)))


@pytest.mark.parametrize("oversized", [False, True])
def test_unreadable_or_oversized_file_keeps_current_review(
    review: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oversized: bool
) -> None:
    """Show file errors without starting recognition or replacing the current clues."""
    from sudoku.import_images import MAX_IMAGE_BYTES

    path: Path = tmp_path / "puzzle.png"
    if oversized:
        with path.open("wb") as output:
            output.truncate(MAX_IMAGE_BYTES + 1)
    panel: Any = Mock()
    panel.runModal.return_value = AK.NSModalResponseOK
    panel.URL.return_value = NSURL.fileURLWithPath_(str(path))
    monkeypatch.setattr(AK, "NSOpenPanel", Mock(openPanel=Mock(return_value=panel)))
    review.load_image = Mock()
    before: list[int] = list(review.values)
    review.chooseFile_(None)
    review.load_image.assert_not_called()
    assert review.values == before
    expected: str = "image is too large" if oversized else "Could not read that image file"
    assert expected in str(review.controls["status"].stringValue())


def test_duplicate_review_preserves_saved_difficulty(
    review: Any, unmatched_import: ValidatedImport
) -> None:
    """Show the permanent import ID and use its original level when clues are repeated."""
    validated: ValidatedImport = unmatched_import
    saved = review.store.imported.start(validated, "Expert")
    review.values = list(validated.givens)
    review.validation_finished((validated, None))
    review.update_play()
    assert review.difficulty == "Expert"
    assert review.controls["difficulty_Expert"].state() == AK.NSControlStateValueOn
    assert all(review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert saved.puzzle.identifier in str(review.controls["status"].stringValue())
    assert review.controls["play"].isEnabled()
    review.controls["difficulty_Medium"].performClick_(None)
    assert review.difficulty == "Medium"
    review.edit_cell(validated.givens[0])
    finish_jobs(review)
    assert review.difficulty == "Medium"
    review.playPuzzle_(None)
    review.play.assert_called_once_with(validated, "Medium")


def test_corner_rotation_invalidates_old_review(review: Any) -> None:
    """Rotate source mapping and require recognition of the newly oriented board."""
    import numpy as np

    review.image = np.full((100, 100, 3), 255, dtype=np.uint8)
    corners: Corners = ((0.0, 0.0), (99.0, 0.0), (99.0, 99.0), (0.0, 99.0))
    review.corners = corners
    review.run_job = Mock()
    review.rotateBoard_(None)
    assert review.corners == corners[1:] + corners[:1]
    assert review.validated is None
    review.run_job.assert_called_once()


def test_new_clues_reset_saved_difficulty(review: Any, unmatched_import: ValidatedImport) -> None:
    """Default different clues to Medium after reviewing a previously saved import."""
    duplicate: ValidatedImport = unmatched_import
    review.store.imported.start(duplicate, "Expert")
    review.values = list(duplicate.givens)
    review.validation_finished((duplicate, None))
    givens: list[int] = list(duplicate.givens)
    empty: int = givens.index(0)
    givens[empty] = duplicate.solution[empty]
    fresh: ValidatedImport = validate_import(tuple(givens))
    review.values = list(fresh.givens)
    review.validation_finished((fresh, None))
    assert all(review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert review.difficulty == "Medium"


def test_difficulty_buttons_keep_one_selection(review: Any) -> None:
    """Allow every level and keep a pressed selected button from clearing the selection."""
    assert review.controls["difficulty_Medium"].state() == AK.NSControlStateValueOn
    for level in LEVELS:
        button: Any = review.controls[f"difficulty_{level}"]
        for _ in range(2):
            button.performClick_(None)
            assert review.difficulty == level
            assert [
                candidate
                for candidate in LEVELS
                if review.controls[f"difficulty_{candidate}"].state() == AK.NSControlStateValueOn
            ] == [level]
    assert not review.controls["play"].isEnabled()


def test_clue_validation_preserves_chosen_difficulty(
    review: Any, unmatched_import: ValidatedImport
) -> None:
    """Keep the user's level through ordinary clue confirmation and validation."""
    validated: ValidatedImport = unmatched_import
    review.values = list(validated.givens)
    review.controls["difficulty_Hard"].performClick_(None)
    review.edit_cell(validated.givens[0])
    finish_jobs(review)
    assert review.difficulty == "Hard"
    assert review.controls["play"].isEnabled()
    review.playPuzzle_(None)
    review.play.assert_called_once_with(validated, "Hard")


def test_new_image_defaults_to_medium(review: Any) -> None:
    """Reset the chosen level when another image loads before recognition completes."""
    review.select_difficulty("Expert")
    review.run_job = Mock()
    review.load_image(b"image data")
    assert review.difficulty == "Medium"
    assert all(review.controls[f"difficulty_{level}"].isEnabled() for level in LEVELS)
    assert review.controls["difficulty_Medium"].state() == AK.NSControlStateValueOn


@pytest.mark.parametrize("appearance", (AK.NSAppearanceNameAqua, AK.NSAppearanceNameDarkAqua))
def test_import_drawings_and_controls_use_every_theme(review: Any, appearance: str) -> None:
    """Render each review palette and retain difficulty, clue editing, and popup choices."""
    native_appearance: Any = AK.NSAppearance.appearanceNamed_(appearance)
    review.controls["regions"].removeAllItems()
    review.controls["regions"].addItemsWithTitles_(["Board 1", "Board 2"])
    review.controls["regions"].selectItemAtIndex_(1)
    review.select_difficulty("Hard")
    reference: Any = ReferenceSurface.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 20, 20))
    reference.color = AK.NSColor.clearColor()
    review.content.addSubview_(reference)
    for name in THEME_NAMES:
        theme: Any = theme_for_name(name)
        review.apply_theme(theme, native_appearance)
        assert review.controls["regions"].titleOfSelectedItem() == "Board 2"
        assert review.difficulty == "Hard"
        assert review.controls["status"].textColor().isEqual_(theme.secondary_text)
        assert review.controls["difficulty_Hard"].state() == AK.NSControlStateValueOn
        background: Any = theme.board.background
        assert isinstance(background, SolidBackground)
        for view, color in (
            (review.grid, background.color),
            (review.source, theme.controls.background),
        ):
            bitmap: Any = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
            view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
            pixel: Any = bitmap.colorAtX_y_(bitmap.pixelsWide() // 2, bitmap.pixelsHigh() // 2)
            # Sample an empty cell center, away from selection and grid lines.
            reference.color = color
            swatch: Any = reference.bitmapImageRepForCachingDisplayInRect_(reference.bounds())
            reference.cacheDisplayInRect_toBitmapImageRep_(reference.bounds(), swatch)
            expected: Any = swatch.colorAtX_y_(swatch.pixelsWide() // 2, swatch.pixelsHigh() // 2)
            assert (pixel.redComponent(), pixel.greenComponent(), pixel.blueComponent()) == (
                pytest.approx(
                    (expected.redComponent(), expected.greenComponent(), expected.blueComponent()),
                    abs=1 / 255,
                )
            ), name
        review.controls["difficulty_Expert"].performClick_(None)
        assert review.difficulty == "Expert"
        review.select_difficulty("Hard")
