# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Native Cocoa Sudoku drawing, accessibility, and pointer/keyboard interaction."""

from dataclasses import dataclass
from functools import lru_cache
from math import hypot, sqrt
from typing import Any

import AppKit as AK
import objc
from Foundation import NSDictionary, NSMakeRect, NSPoint, NSString

from sudoku.context_menu import CellContextMenu
from sudoku.engine import PEERS, cell_name
from sudoku.hint_types import HintLink, HintNode
from sudoku.model import Game, Preferences
from sudoku.theme import Theme

CELL_HIT_INSET_RATIO: float = 0.12
CANDIDATE_DRAG_START_DISTANCE: float = 3.0  # macOS points in board coordinates.


@dataclass(frozen=True)
class CandidateLayout:
    """Keep glyph measurements and balanced positions independent of visible notes."""

    font_size: float
    baseline: float
    glyph_bounds: tuple[Any, ...]
    ink_width: float
    ink_height: float

    def digit_rect(self, cell: Any, digit: int) -> Any:
        """Center a candidate's highlight rectangle on its permanent 3×3 position."""
        gap_x: float = (cell.size.width - 3 * self.ink_width) / 4
        gap_y: float = (cell.size.height - 3 * self.ink_height) / 4
        center_x: float = (
            cell.origin.x + gap_x + self.ink_width / 2 + (digit - 1) % 3 * (self.ink_width + gap_x)
        )
        center_y: float = (
            cell.origin.y
            + gap_y
            + self.ink_height / 2
            + (digit - 1) // 3 * (self.ink_height + gap_y)
        )
        side: float = cell.size.width * 0.26
        return NSMakeRect(center_x - side / 2, center_y - side / 2, side, side)


@lru_cache(maxsize=16)
def candidate_layout(cell_size: float) -> CandidateLayout:
    """Measure bold digit ink once per cell size without retaining unbounded resize history."""
    size: float = cell_size * 0.25
    font: Any = AK.NSFont.systemFontOfSize_weight_(size, AK.NSFontWeightBold)
    storage: Any = AK.NSTextStorage.alloc().initWithString_attributes_(
        "123456789", {AK.NSFontAttributeName: font}
    )
    manager: Any = AK.NSLayoutManager.alloc().init()
    storage.addLayoutManager_(manager)
    bounds: tuple[Any, ...] = tuple(
        font.boundingRectForGlyph_(manager.glyphAtIndex_(index)) for index in range(9)
    )
    return CandidateLayout(
        font_size=size,
        baseline=manager.defaultBaselineOffsetForFont_(font),
        glyph_bounds=bounds,
        ink_width=max(rect.size.width for rect in bounds),
        ink_height=max(rect.size.height for rect in bounds),
    )


def candidate_painting_enabled(game: Game, preferences: Preferences) -> bool:
    """Allow candidate strokes in Candidates mode or through the Answers-mode option."""
    return game.note_mode or preferences.drag_answers_as_candidates


def segment_axis_interval(
    origin: float, delta: float, minimum: float, maximum: float
) -> tuple[float, float] | None:
    """Return the segment parameter interval that lies inside one axis range."""
    if abs(delta) < 1e-9:
        return (0.0, 1.0) if minimum <= origin <= maximum else None
    first: float = (minimum - origin) / delta
    second: float = (maximum - origin) / delta
    return min(first, second), max(first, second)


def cells_crossed_by_segment(
    start: tuple[float, float], end: tuple[float, float], board_width: float
) -> list[int]:
    """List cells whose inset interiors a pointer segment crosses, in travel order."""
    cell_size: float = (board_width - 2) / 9
    inset: float = cell_size * CELL_HIT_INSET_RATIO
    delta_x: float = end[0] - start[0]
    delta_y: float = end[1] - start[1]
    crossed: list[tuple[float, int]] = []
    for index in range(81):
        row: int = index // 9
        column: int = index % 9
        left: float = 1 + column * cell_size + inset
        right: float = 1 + (column + 1) * cell_size - inset
        top: float = 1 + row * cell_size + inset
        bottom: float = 1 + (row + 1) * cell_size - inset
        horizontal: tuple[float, float] | None = segment_axis_interval(
            start[0], delta_x, left, right
        )
        vertical: tuple[float, float] | None = segment_axis_interval(start[1], delta_y, top, bottom)
        if horizontal is None or vertical is None:
            continue
        entry: float = max(0.0, horizontal[0], vertical[0])
        exit_parameter: float = min(1.0, horizontal[1], vertical[1])
        if entry <= exit_parameter:
            crossed.append((entry, index))
    return [index for _, index in sorted(crossed)]


class AccessibleCell(AK.NSAccessibilityElement):
    """Expose one custom-drawn board cell as a pressable accessibility element."""

    board: Any
    index: int

    def accessibilityPerformPress(self) -> bool:
        """Activate a cell using the same entry rules as a pointer click."""
        controller: Any = self.board.controller
        game: Game = controller.game
        if game.paused:
            return False
        self.board.window().makeFirstResponder_(self.board)
        self.board.finish_gesture()
        controller.clear_all_game = None
        game.selected = self.index
        changed: bool = self.board.apply_active_digit(self.index)
        if changed:
            controller.changed()
        else:
            controller.refresh()
        return True


class SudokuBoard(AK.NSView):
    """Draw a crisp board and translate native events into model operations."""

    controller: Any
    cells: list[Any]
    drag_origin: int | None
    drag_last: int | None
    drag_point: tuple[float, float] | None
    drag_operation: str | None
    dragging: bool
    keyboard_operation: str | None
    keyboard_painting: bool
    pencil_cursor: Any
    cursor_is_candidate: bool
    context_menu_controller: Any

    def initWithFrame_(self, frame: Any) -> Any:
        """Initialize interaction state and the board accessibility container."""
        self = objc.super(SudokuBoard, self).initWithFrame_(frame)
        if self is not None:
            self.controller = None
            self.pencil_cursor = None
            self.cursor_is_candidate = False
            self.context_menu_controller = None
            self.cells = []
            self.drag_origin = None
            self.drag_last = None
            self.drag_point = None
            self.drag_operation = None
            self.dragging = False
            self.keyboard_operation = None
            self.keyboard_painting = False
            self.setAccessibilityElement_(False)
            self.setAccessibilityRole_(AK.NSAccessibilityGroupRole)
            self.setAccessibilityLabel_("Sudoku board")
        return self

    def isFlipped(self) -> bool:
        """Use top-to-bottom Sudoku row coordinates."""
        return True

    def acceptsFirstResponder(self) -> bool:
        """Allow arrow keys and digit entry directly in the board."""
        return True

    def becomeFirstResponder(self) -> bool:
        """Redraw keyboard focus when the board becomes active."""
        self.setNeedsDisplay_(True)
        return True

    def resignFirstResponder(self) -> bool:
        """Finish painting before focus moves to another native control."""
        if self.controller:
            self.finish_gesture()
        self.setNeedsDisplay_(True)
        return True

    @objc.python_method
    def cell_rect(self, index: int) -> Any:
        """Compute the drawing rectangle for a zero-based cell."""
        size: float = (self.bounds().size.width - 2) / 9
        return NSMakeRect(1 + index % 9 * size, 1 + index // 9 * size, size, size)

    @objc.python_method
    def hint_node_rect(self, node: HintNode, layout: CandidateLayout, scale: float) -> Any:
        """Enclose a link endpoint, keeping grouped candidates as one OR node."""
        rect: Any = layout.digit_rect(self.cell_rect(node.cells[0]), node.digit)
        for cell in node.cells[1:]:
            rect = AK.NSUnionRect(rect, layout.digit_rect(self.cell_rect(cell), node.digit))
        return AK.NSInsetRect(rect, -scale, -scale)

    @objc.python_method
    def hint_link_endpoint(self, rect: Any, target: Any, grouped: bool) -> tuple[float, float]:
        """Stop a link at the outside of its candidate circle or group enclosure."""
        center_x: float = AK.NSMidX(rect)
        center_y: float = AK.NSMidY(rect)
        delta_x: float = AK.NSMidX(target) - center_x
        delta_y: float = AK.NSMidY(target) - center_y
        distance: float = hypot(delta_x, delta_y)
        if distance == 0:
            return center_x, center_y
        fraction: float = (
            min(
                rect.size.width / (2 * abs(delta_x)) if delta_x else float("inf"),
                rect.size.height / (2 * abs(delta_y)) if delta_y else float("inf"),
            )
            if grouped
            else rect.size.width / (2 * distance)
        )
        return center_x + delta_x * fraction, center_y + delta_y * fraction

    @objc.python_method
    def hint_ink_rects(
        self, layout: CandidateLayout, endpoints: set[tuple[int, int]]
    ) -> list[tuple[float, float, float, float]]:
        """Collect answer and candidate ink bounds, excluding a link's endpoints."""
        cell_size: float = self.cell_rect(0).size.width
        obstacles: list[tuple[float, float, float, float]] = []
        evidence: set[tuple[int, int]] = (
            self.controller.hint_candidates
            | self.controller.hint_placements
            | self.controller.hint_removals
        )
        for cell, value in enumerate(self.controller.game.values):
            rect: Any = self.cell_rect(cell)
            rects: list[Any] = (
                [AK.NSInsetRect(rect, cell_size * 0.24, cell_size * 0.2)]
                if value
                else [
                    AK.NSInsetRect(layout.digit_rect(rect, digit), cell_size * 0.04, 0)
                    for digit in self.controller.game.notes[cell]
                    | {digit for index, digit in evidence if index == cell}
                    if (cell, digit) not in endpoints
                ]
            )
            obstacles.extend(
                (AK.NSMinX(item), AK.NSMinY(item), AK.NSMaxX(item), AK.NSMaxY(item))
                for item in rects
            )
        return obstacles

    @objc.python_method
    def hint_link_bend(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        layout: CandidateLayout,
        endpoints: set[tuple[int, int]],
    ) -> float:
        """Choose a gentle curve when a straight link would cross other candidate ink."""
        delta_x: float = end[0] - start[0]
        delta_y: float = end[1] - start[1]
        distance: float = hypot(delta_x, delta_y)
        if distance == 0:
            return 0
        cell_size: float = self.cell_rect(0).size.width
        normal_x: float = -delta_y / distance
        normal_y: float = delta_x / distance
        obstacles: list[tuple[float, float, float, float]] = self.hint_ink_rects(layout, endpoints)
        samples: int = max(12, int(distance / cell_size * 12))
        board_width: float = self.bounds().size.width

        def crossings(bend: float) -> int:
            """Count distinct ink rectangles crossed by a sampled cubic curve."""
            hits: set[int] = set()
            for step in range(1, samples):
                fraction: float = step / samples
                offset: float = 3 * fraction * (1 - fraction) * bend
                x: float = start[0] + delta_x * fraction + normal_x * offset
                y: float = start[1] + delta_y * fraction + normal_y * offset
                if not (1 <= x <= board_width - 1 and 1 <= y <= board_width - 1):
                    return len(obstacles) + 1
                hits.update(
                    index
                    for index, (left, top, right, bottom) in enumerate(obstacles)
                    if left <= x <= right and top <= y <= bottom
                )
            return len(hits)

        if crossings(0) == 0:
            return 0
        bends: tuple[float, ...] = tuple(cell_size * value for value in (0, 0.4, -0.4, 0.8, -0.8))
        return min(bends, key=crossings)

    @objc.python_method
    def hint_curve_path(
        self, start: tuple[float, float], end: tuple[float, float], bend: float
    ) -> Any:
        """Build a straight segment or cubic curve with the selected perpendicular bend."""
        path: Any = AK.NSBezierPath.bezierPath()
        path.moveToPoint_(start)
        distance: float = hypot(end[0] - start[0], end[1] - start[1])
        if not bend or not distance:
            path.lineToPoint_(end)
            return path
        delta_x: float = end[0] - start[0]
        delta_y: float = end[1] - start[1]
        offset_x: float = -delta_y / distance * bend
        offset_y: float = delta_x / distance * bend
        path.curveToPoint_controlPoint1_controlPoint2_(
            end,
            (start[0] + delta_x / 3 + offset_x, start[1] + delta_y / 3 + offset_y),
            (start[0] + delta_x * 2 / 3 + offset_x, start[1] + delta_y * 2 / 3 + offset_y),
        )
        return path

    @objc.python_method
    def hint_link_path(
        self, link: HintLink, layout: CandidateLayout, scale: float, parallel: bool
    ) -> Any:
        """Connect circle or group boundaries while keeping different link styles distinct."""
        first, second = sorted((link.start, link.end))
        start_rect: Any = self.hint_node_rect(first, layout, scale)
        end_rect: Any = self.hint_node_rect(second, layout, scale)
        if (len(first.cells) > 1 or len(second.cells) > 1) and AK.NSIntersectsRect(
            start_rect, end_rect
        ):
            path: Any = AK.NSBezierPath.bezierPath()
            edge_y: float = max(
                2 * scale, min(AK.NSMinY(start_rect), AK.NSMinY(end_rect)) - 12 * scale
            )
            edge_x: float = min(
                self.bounds().size.width - 2 * scale,
                max(AK.NSMaxX(start_rect), AK.NSMaxX(end_rect)) + 12 * scale,
            )
            start: tuple[float, float] = (AK.NSMaxX(start_rect), AK.NSMidY(start_rect))
            end: tuple[float, float] = (AK.NSMidX(end_rect), AK.NSMinY(end_rect))
            path.moveToPoint_(start)
            path.curveToPoint_controlPoint1_controlPoint2_(
                end, (edge_x, start[1]), (end[0], edge_y)
            )
            return path
        start = self.hint_link_endpoint(start_rect, end_rect, len(first.cells) > 1)
        end = self.hint_link_endpoint(end_rect, start_rect, len(second.cells) > 1)
        endpoints: set[tuple[int, int]] = {
            (cell, node.digit) for node in (first, second) for cell in node.cells
        }
        bend: float = (
            self.cell_rect(0).size.width * (0.25 if link.strong else -0.25)
            if parallel
            else self.hint_link_bend(start, end, layout, endpoints)
        )
        return self.hint_curve_path(start, end, bend)

    @objc.python_method
    def draw_hint_links(self, layout: CandidateLayout, scale: float, theme: Theme) -> None:
        """Draw solid strong links and round dotted weak links behind candidate ink."""
        groups: set[HintNode] = set()
        drawn: set[tuple[HintNode, HintNode, bool]] = set()
        styles: dict[tuple[HintNode, HintNode], set[bool]] = {}
        for link in self.controller.hint_links:
            first, second = sorted((link.start, link.end))
            styles.setdefault((first, second), set()).add(link.strong)
        theme.hints.evidence_stroke.setStroke()
        for link in self.controller.hint_links:
            first, second = sorted((link.start, link.end))
            key: tuple[HintNode, HintNode, bool] = (first, second, link.strong)
            if key in drawn:
                continue
            drawn.add(key)
            groups.update(node for node in (first, second) if len(node.cells) > 1)
            path: Any = self.hint_link_path(link, layout, scale, len(styles[(first, second)]) > 1)
            path.setLineWidth_((2.25 if theme.high_contrast else 1.6) * scale)
            path.setLineCapStyle_(AK.NSRoundLineCapStyle)
            if not link.strong:
                path.setLineDash_count_phase_((0.1 * scale, 3.5 * scale), 2, 0)
            path.stroke()
        for node in sorted(groups):
            enclosure: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                self.hint_node_rect(node, layout, scale), 5 * scale, 5 * scale
            )
            enclosure.setLineWidth_((1.75 if theme.high_contrast else 1.1) * scale)
            enclosure.stroke()

    @objc.python_method
    def draw_cell_backgrounds(self, game: Game, prefs: Preferences, theme: Theme) -> None:
        """Paint every cell before connecting hint candidates across the board."""
        errors: set[int] = game.errors(prefs.error_check)
        matching: int = 0 if game.color_mode else game.active_digit
        for index in range(81):
            rect: Any = self.cell_rect(index)
            if prefs.highlight_peers and index in PEERS[game.selected]:
                theme.board.peer_fill.resolve().setFill()
                AK.NSRectFill(rect)
            if game.colors[index]:
                theme.annotations.cell_fill(game.colors[index]).setFill()
                AK.NSRectFill(rect)
            if prefs.highlight_digits and matching and game.values[index] == matching:
                theme.board.matching_answer_fill.resolve().setFill()
                AK.NSRectFill(rect)
            if index in self.controller.hint_focus:
                theme.hints.focus_fill.resolve().setFill()
                AK.NSRectFill(rect)
            if index in errors:
                theme.hints.error_fill.resolve().setFill()
                AK.NSRectFill(rect)

    @objc.python_method
    def draw_text(
        self,
        text: str,
        rect: Any,
        size: float,
        color: Any,
        weight: float = AK.NSFontWeightRegular,
        underline: bool = False,
        candidate: CandidateLayout | None = None,
    ) -> None:
        """Center text, using visible digit ink bounds for pencil marks."""
        font: Any = AK.NSFont.systemFontOfSize_weight_(size, weight)
        # Native attributes avoid retaining Python dictionaries across Cocoa text calls.
        attributes: Any = NSDictionary.dictionaryWithDictionary_(
            {
                AK.NSFontAttributeName: font,
                AK.NSForegroundColorAttributeName: color,
                AK.NSUnderlineStyleAttributeName: AK.NSUnderlineStyleSingle if underline else 0,
            }
        )
        string: Any = NSString.stringWithString_(text)
        measured: Any = string.sizeWithAttributes_(attributes)
        point: Any = NSPoint(
            rect.origin.x + (rect.size.width - measured.width) / 2,
            rect.origin.y + (rect.size.height - measured.height) / 2,
        )
        if candidate is not None:
            ink: Any = candidate.glyph_bounds[int(text) - 1]
            point = NSPoint(
                AK.NSMidX(rect) - AK.NSMidX(ink),
                AK.NSMidY(rect) + AK.NSMidY(ink) - candidate.baseline,
            )
        string.drawAtPoint_withAttributes_(point, attributes)

    @objc.python_method
    def draw_match_outline(self, rect: Any, scale: float, candidate: bool = False) -> None:
        """Distinguish matches by shape in High Contrast without changing selection."""
        self.controller.theme.accent.setStroke()
        path: Any = AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AK.NSInsetRect(
                rect, scale if candidate else 3 * scale, scale if candidate else 3 * scale
            ),
            3 * scale,
            3 * scale,
        )
        path.setLineWidth_(scale)
        if not candidate:
            path.setLineDash_count_phase_((3 * scale, 2 * scale), 2, 0)
        path.stroke()

    @objc.python_method
    def draw_error_marker(self, rect: Any, color: Any, line_width: float) -> None:
        """Overlay a circled X sized to the answer or candidate rectangle."""
        marker_rect: Any = AK.NSInsetRect(rect, rect.size.width * 0.12, rect.size.height * 0.12)
        cross_rect: Any = AK.NSInsetRect(
            marker_rect, marker_rect.size.width * 0.15, marker_rect.size.height * 0.15
        )
        color.setStroke()
        marker: Any = AK.NSBezierPath.bezierPathWithOvalInRect_(marker_rect)
        marker.moveToPoint_((AK.NSMinX(cross_rect), AK.NSMinY(cross_rect)))
        marker.lineToPoint_((AK.NSMaxX(cross_rect), AK.NSMaxY(cross_rect)))
        marker.moveToPoint_((AK.NSMinX(cross_rect), AK.NSMaxY(cross_rect)))
        marker.lineToPoint_((AK.NSMaxX(cross_rect), AK.NSMinY(cross_rect)))
        marker.setLineWidth_(line_width)
        marker.stroke()

    def drawRect_(self, dirty: Any) -> None:
        """Render cell colors, values, fixed-position notes, and hint annotations."""
        if not self.controller:
            return
        scale: float = (self.bounds().size.width - 2) / 588
        game: Game = self.controller.game
        prefs: Preferences = self.controller.preferences
        theme: Theme = self.controller.theme
        theme.board.background.draw(self.bounds())
        if game.paused:
            self.draw_text("Paused", self.bounds(), 28 * scale, theme.secondary_text)
            return
        errors: set[int] = game.errors(prefs.error_check)
        matching: int = 0 if game.color_mode else game.active_digit
        removed: set[tuple[int, int]] = self.controller.hint_removals
        evidence: set[tuple[int, int]] = self.controller.hint_candidates
        placed: set[tuple[int, int]] = self.controller.hint_placements
        accent: Any = theme.accent
        notes_layout: CandidateLayout = candidate_layout(self.cell_rect(0).size.width)
        self.draw_cell_backgrounds(game, prefs, theme)
        self.draw_hint_links(notes_layout, scale, theme)
        for index in range(81):
            rect: Any = self.cell_rect(index)
            if (
                theme.high_contrast
                and prefs.highlight_digits
                and matching
                and game.values[index] == matching
            ):
                self.draw_match_outline(rect, scale)
            if game.values[index]:
                color: Any = theme.text if game.puzzle.givens[index] else accent
                if index in errors:
                    color = theme.hints.error_text
                self.draw_text(
                    str(game.values[index]),
                    rect,
                    rect.size.width * 0.65,
                    color,
                    AK.NSFontWeightSemibold,
                    underline=theme.high_contrast and not game.puzzle.givens[index],
                )
                if index in errors:
                    self.draw_error_marker(
                        rect, theme.hints.error_text, (1.6 if theme.high_contrast else 1.25) * scale
                    )
            else:
                shown: set[int] = game.notes[index] | {
                    d for i, d in removed | placed | evidence if i == index
                }
                for digit in sorted(shown):
                    note_rect: Any = notes_layout.digit_rect(rect, digit)
                    color = theme.text
                    highlighted: bool = prefs.highlight_digits and digit == matching
                    if highlighted:
                        # Scale the filled area by 75% while preserving the candidate's center.
                        growth: float = (note_rect.size.width + 2 * scale) * (sqrt(1.75) - 1) / 2
                        highlight_rect: Any = AK.NSInsetRect(
                            note_rect, -2 * scale - growth, -2 * scale - growth
                        )
                        theme.board.matching_candidate_fill.resolve().setFill()
                        AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                            AK.NSInsetRect(highlight_rect, scale, scale), 3 * scale, 3 * scale
                        ).fill()
                        if theme.high_contrast:
                            self.draw_match_outline(highlight_rect, scale, candidate=True)
                    self.draw_text(
                        str(digit),
                        note_rect,
                        notes_layout.font_size,
                        color,
                        AK.NSFontWeightBold,
                        candidate=notes_layout,
                    )
                    if (index, digit) in (evidence | placed) - removed:
                        placement: bool = (index, digit) in placed
                        marker_color: Any = (
                            theme.hints.placement_stroke
                            if placement
                            else theme.hints.evidence_stroke
                        )
                        marker_inset: float = (-2 if placement else 0.5) * scale
                        marker_width: float = (
                            (3 if theme.high_contrast else 2.25)
                            if placement
                            else (2 if theme.high_contrast else 1.5)
                        ) * scale
                        marker_color.setStroke()
                        marker: Any = AK.NSBezierPath.bezierPathWithOvalInRect_(
                            AK.NSInsetRect(note_rect, marker_inset, marker_inset)
                        )
                        marker.setLineWidth_(marker_width)
                        marker.stroke()
                    if (index, digit) in removed:
                        self.draw_error_marker(
                            AK.NSInsetRect(note_rect, -5 * scale, -5 * scale),
                            theme.hints.removal_stroke,
                            (1.25 if theme.high_contrast else 0.95) * scale,
                        )
        width: float = self.bounds().size.width
        size: float = (width - 2) / 9
        for step in range(10):
            major: bool = step % 3 == 0
            (theme.board.major_grid if major else theme.board.minor_grid).resolve().setStroke()
            path: Any = AK.NSBezierPath.bezierPath()
            thickness: float = (
                (2 if major else 0.8) if theme.high_contrast else (1.5 if major else 0.5)
            )
            path.setLineWidth_(thickness * scale)
            coordinate: float = 1 + step * size
            path.moveToPoint_((coordinate, 1))
            path.lineToPoint_((coordinate, width - 1))
            path.moveToPoint_((1, coordinate))
            path.lineToPoint_((width - 1, coordinate))
            path.stroke()
        accent.setStroke()
        outline: Any = AK.NSBezierPath.bezierPathWithRect_(
            AK.NSInsetRect(self.cell_rect(game.selected), 1.5 * scale, 1.5 * scale)
        )
        focused: bool = self.window().firstResponder() == self
        outline.setLineWidth_(
            ((3 if focused else 2) if theme.high_contrast else (2 if focused else 1)) * scale
        )
        outline.stroke()
        if game.note_mode and not game.color_mode:
            rect = self.cell_rect(game.selected)
            theme.board.candidate_guides.resolve().setStroke()
            guides: Any = AK.NSBezierPath.bezierPath()
            guides.setLineWidth_(0.75 * scale)
            for fraction in (1 / 3, 2 / 3):
                x: float = rect.origin.x + rect.size.width * fraction
                y: float = rect.origin.y + rect.size.height * fraction
                guides.moveToPoint_((x, rect.origin.y + 2 * scale))
                guides.lineToPoint_((x, rect.origin.y + rect.size.height - 2 * scale))
                guides.moveToPoint_((rect.origin.x + 2 * scale, y))
                guides.lineToPoint_((rect.origin.x + rect.size.width - 2 * scale, y))
            guides.stroke()

    @objc.python_method
    def candidate_cursor(self) -> Any:
        """Cache a high-resolution pencil cursor with the hotspot at its writing tip."""
        if self.pencil_cursor is None:
            pencil: Any = AK.NSImage.alloc().initWithSize_((28, 28))
            pencil.lockFocus()
            path: Any = AK.NSBezierPath.bezierPath()
            path.moveToPoint_((3, 3))
            for point in ((5, 11), (20, 26), (25, 21), (10, 6)):
                path.lineToPoint_(point)
            path.closePath()
            self.controller.theme.board.cursor_fill.setFill()
            path.fill()
            self.controller.theme.board.cursor_outline.setStroke()
            path.setLineWidth_(1.5)
            path.stroke()
            detail: Any = AK.NSBezierPath.bezierPath()
            detail.moveToPoint_((5, 11))
            detail.lineToPoint_((10, 6))
            detail.moveToPoint_((18, 24))
            detail.lineToPoint_((23, 19))
            detail.setLineWidth_(1)
            detail.stroke()
            pencil.unlockFocus()
            self.pencil_cursor = AK.NSCursor.alloc().initWithImage_hotSpot_(pencil, (3, 25))
        return self.pencil_cursor

    @objc.python_method
    def update_cursor(self) -> None:
        """Refresh Cocoa cursor regions when entry mode or pause state changes."""
        candidate: bool = (
            self.controller.game.note_mode
            and not self.controller.game.color_mode
            and not self.controller.game.paused
        )
        if candidate != self.cursor_is_candidate:
            self.cursor_is_candidate = candidate
            if self.window():
                self.window().invalidateCursorRectsForView_(self)

    def resetCursorRects(self) -> None:
        """Use the pencil only over an unpaused board in candidate mode."""
        cursor: Any = (
            self.candidate_cursor() if self.cursor_is_candidate else AK.NSCursor.arrowCursor()
        )
        self.addCursorRect_cursor_(self.bounds(), cursor)

    @objc.python_method
    def index_at_event(self, event: Any) -> int | None:
        """Hit-test a native event in the flipped board coordinate system."""
        point: tuple[float, float] = self.point_at_event(event)
        size: float = (self.bounds().size.width - 2) / 9
        row: int = int((point[1] - 1) // size)
        column: int = int((point[0] - 1) // size)
        return row * 9 + column if 0 <= row < 9 and 0 <= column < 9 else None

    @objc.python_method
    def point_at_event(self, event: Any) -> tuple[float, float]:
        """Convert a native pointer event to stable board coordinates."""
        point: Any = self.convertPoint_fromView_(event.locationInWindow(), None)
        return float(point.x), float(point.y)

    @objc.python_method
    def apply_active_digit(self, index: int, operation: str = "toggle") -> bool:
        """Apply a number-first cell activation; cell-first activation only selects."""
        game: Game = self.controller.game
        if self.controller.preferences.input_order != "Number First":
            return False
        if game.color_mode:
            return game.paint_color(index, operation)
        if game.note_mode:
            return game.mark(index, game.active_digit, operation)
        return game.set_value(
            index,
            game.active_digit,
            self.controller.preferences.cleanup_notes,
            error_check=self.controller.preferences.error_check,
        )

    def rightMouseDown_(self, event: Any) -> None:
        """Show answer, candidate, and color choices for the clicked cell."""
        game: Game = self.controller.game
        if game.paused or game.complete:
            return
        index: int | None = self.index_at_event(event)
        if index is None:
            return
        self.finish_gesture()
        self.controller.clear_all_game = None
        game.selected = index
        self.window().makeFirstResponder_(self)
        self.controller.refresh()
        context: Any = CellContextMenu.alloc().init()
        context.configure(self, index)
        self.context_menu_controller = context
        try:
            AK.NSMenu.popUpContextMenu_withEvent_forView_(context.build_menu(), event, self)
        finally:
            self.context_menu_controller = None
            self.window().makeFirstResponder_(self)
            self.controller.refresh()

    def mouseDown_(self, event: Any) -> None:
        """Select the initial cell and prepare a click or candidate stroke."""
        if event.modifierFlags() & AK.NSEventModifierFlagControl:
            self.rightMouseDown_(event)
            return
        if self.controller.game.paused:
            return
        self.window().makeFirstResponder_(self)
        index: int | None = self.index_at_event(event)
        if index is None:
            return
        self.finish_gesture()
        self.controller.clear_all_game = None
        self.drag_origin = self.drag_last = index
        self.drag_point = self.point_at_event(event)
        self.dragging = False
        self.controller.game.selected = index
        self.controller.game.begin_gesture()
        self.drag_operation = (
            self.controller.game.color_stroke_operation(index)
            if self.controller.game.color_mode
            else self.controller.game.candidate_stroke_operation(
                index,
                self.controller.game.active_digit,
                bool(event.modifierFlags() & AK.NSEventModifierFlagOption),
            )
        )
        self.controller.refresh()

    def mouseDragged_(self, event: Any) -> None:
        """Wait for intentional candidate movement, then paint crossed cell interiors."""
        point: tuple[float, float] = self.point_at_event(event)
        index: int | None = self.index_at_event(event)
        if self.drag_point is None or self.drag_last is None:
            return
        game: Game = self.controller.game
        paints: bool = game.color_mode or candidate_painting_enabled(
            game, self.controller.preferences
        )
        if paints:
            if not self.dragging and not game.color_mode:
                distance_from_press: float = hypot(
                    point[0] - self.drag_point[0], point[1] - self.drag_point[1]
                )
                if distance_from_press < CANDIDATE_DRAG_START_DISTANCE:
                    # Keep the press position as the origin until painting starts.
                    return
            crossed: list[int] = cells_crossed_by_segment(
                self.drag_point, point, self.bounds().size.width
            )
            new_cells: list[int] = [cell for cell in crossed if cell != self.drag_last]
            starts_candidate_stroke: bool = not self.dragging and not game.color_mode
            if new_cells or starts_candidate_stroke:
                if (
                    not self.dragging
                    and self.drag_origin is not None
                    and self.drag_origin not in crossed
                ):
                    crossed.insert(0, self.drag_origin)
                self.dragging = True
                operation: str = self.drag_operation or "add"
                for cell in crossed:
                    if game.color_mode:
                        game.paint_color(cell, operation)
                    else:
                        game.mark(cell, game.active_digit, operation)
                if new_cells:
                    self.drag_last = new_cells[-1]
                    game.selected = self.drag_last
                self.controller.changed(save=False)
        elif index is not None:
            self.drag_last = index
            game.selected = index
        self.drag_point = point
        self.controller.refresh()

    def mouseUp_(self, event: Any) -> None:
        """Activate a clicked cell or commit all candidates in a painted stroke."""
        if self.drag_origin is not None and not self.dragging:
            operation: str = (
                "remove" if event.modifierFlags() & AK.NSEventModifierFlagOption else "toggle"
            )
            if self.controller.game.color_mode:
                operation = "toggle"
            self.apply_active_digit(self.drag_origin, operation)
        self.finish_gesture()

    @objc.python_method
    def finish_gesture(self) -> None:
        """Commit input transactions and clear transient pointer state."""
        changed: bool = self.controller.game.end_gesture()
        self.drag_origin = self.drag_last = None
        self.drag_point = None
        self.drag_operation = None
        self.keyboard_operation = None
        self.dragging = self.keyboard_painting = False
        if changed:
            self.controller.changed()

    def keyDown_(self, event: Any) -> None:
        """Handle board navigation, answer entry, colors, notes, and clearing."""
        text: str = str(event.charactersIgnoringModifiers() or "")
        game: Game = self.controller.game
        if game.paused:
            return
        if text != "9":
            self.controller.clear_all_game = None
        flags: int = event.modifierFlags()
        if flags & AK.NSEventModifierFlagShift and not flags & (
            AK.NSEventModifierFlagCommand
            | AK.NSEventModifierFlagControl
            | AK.NSEventModifierFlagOption
        ):
            unshifted: str = str(event.charactersByApplyingModifiers_(0) or "")
            digit_text: str = text if text in "123456789" and len(text) == 1 else unshifted
            if len(digit_text) == 1 and digit_text in "123456789":
                self.finish_gesture()
                if game.color_mode:
                    self.controller.select_digit(int(digit_text), True)
                    return
                else:
                    game.active_digit = int(digit_text)
                self.controller.save()
                self.controller.refresh()
                return
        moves: dict[str, tuple[int, int]] = {
            "\uf700": (-1, 0),
            "\uf701": (1, 0),
            "\uf702": (0, -1),
            "\uf703": (0, 1),
        }
        if text in moves:
            painting: bool = bool(flags & AK.NSEventModifierFlagShift) and (
                game.color_mode or candidate_painting_enabled(game, self.controller.preferences)
            )
            if painting:
                if not self.keyboard_painting:
                    self.keyboard_painting = True
                    game.begin_gesture()
                    self.keyboard_operation = (
                        game.color_stroke_operation(game.selected)
                        if game.color_mode
                        else game.candidate_stroke_operation(
                            game.selected,
                            game.active_digit,
                            bool(flags & AK.NSEventModifierFlagOption),
                        )
                    )
                operation: str = self.keyboard_operation or "add"
                if game.color_mode:
                    game.paint_color(game.selected, operation)
                else:
                    game.mark(game.selected, game.active_digit, operation)
                game.move(*moves[text])
                if game.color_mode:
                    game.paint_color(game.selected, operation)
                else:
                    game.mark(game.selected, game.active_digit, operation)
                self.controller.changed(save=False)
            else:
                self.finish_gesture()
                game.move(*moves[text])
            self.controller.refresh()
            return
        self.finish_gesture()
        if text in (" ", "\r", "\n", "\x03"):
            paint_candidate: bool = (
                bool(flags & AK.NSEventModifierFlagShift)
                and not game.color_mode
                and candidate_painting_enabled(game, self.controller.preferences)
            )
            if paint_candidate:
                candidate_operation: str = game.candidate_stroke_operation(
                    game.selected,
                    game.active_digit,
                    bool(flags & AK.NSEventModifierFlagOption),
                )
                if game.mark(game.selected, game.active_digit, candidate_operation):
                    self.controller.changed()
                else:
                    self.controller.refresh()
            elif game.color_mode or self.controller.preferences.input_order == "Number First":
                changed: bool = (
                    game.paint_color(game.selected)
                    if game.color_mode
                    else self.apply_active_digit(game.selected)
                )
                if changed:
                    self.controller.changed()
                else:
                    self.controller.refresh()
            else:
                objc.super(SudokuBoard, self).keyDown_(event)
        elif len(text) == 1 and text in "123456789":
            if game.color_mode:
                self.controller.select_digit(int(text), False)
                return
            else:
                game.active_digit = int(text)
            if self.controller.preferences.input_order == "Cell First":
                if game.color_mode:
                    game.paint_color(game.selected)
                elif game.note_mode:
                    game.mark(game.selected, game.active_digit)
                else:
                    game.set_value(
                        game.selected,
                        game.active_digit,
                        self.controller.preferences.cleanup_notes,
                        error_check=self.controller.preferences.error_check,
                    )
                self.controller.changed()
            self.controller.refresh()
        elif text.lower() == "n":
            self.controller.toggleNotes_(None)
        elif text.lower() == "c":
            self.controller.toggleColor_(None)
        elif text in ("\x7f", "\uf728", "\x08", "0"):
            self.controller.erase_(None)
        elif text == "\x1b":
            self.controller.clear_hint()
            self.controller.refresh()
        else:
            objc.super(SudokuBoard, self).keyDown_(event)

    def flagsChanged_(self, event: Any) -> None:
        """End a Shift-arrow paint action when the Shift key is released."""
        if self.keyboard_painting and not event.modifierFlags() & AK.NSEventModifierFlagShift:
            self.finish_gesture()

    def accessibilityChildren(self) -> list[Any]:
        """Expose values, notes, colors, and selection to VoiceOver."""
        if not self.controller or not self.window() or self.controller.game.paused:
            return []
        if not self.cells:
            for index in range(81):
                element: Any = AccessibleCell.alloc().init()
                element.board = self
                element.index = index
                element.setAccessibilityParent_(self)
                element.setAccessibilityRole_(AK.NSAccessibilityButtonRole)
                element.setAccessibilityEnabled_(True)
                element.setAccessibilityElement_(True)
                self.cells.append(element)
        game: Game = self.controller.game
        for index, element in enumerate(self.cells):
            value: str = str(game.values[index]) if game.values[index] else "empty"
            notes: str = ", ".join(map(str, sorted(game.notes[index])))
            label: str = f"{cell_name(index)}, {value}"
            if game.puzzle.givens[index]:
                label += ", given"
            if notes:
                label += f", candidates {notes}"
            if game.colors[index]:
                label += f", {self.controller.theme.annotations.name(game.colors[index])} highlight"
            if game.selected == index:
                label += ", selected"
            element.setAccessibilityLabel_(label)
            frame: Any = self.convertRect_toView_(self.cell_rect(index), None)
            element.setAccessibilityFrame_(self.window().convertRectToScreen_(frame))
        return self.cells
