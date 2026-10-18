# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Game state, preferences, reversible edits, and candidate painting."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sudoku.engine import DIGITS, PEERS, UNITS, candidates, conflicts
from sudoku.theme_names import THEME_NAMES

LEVELS: tuple[str, ...] = ("Easy", "Medium", "Hard", "Expert", "Master", "Extreme")


@dataclass(frozen=True)
class Puzzle:
    """A validated, uniquely solvable puzzle with an optional published rating."""

    identifier: str
    givens: tuple[int, ...]
    solution: tuple[int, ...]
    rating: float | None
    level: str


@dataclass
class Preferences:
    """Persistent presentation and input choices with explicit defaults."""

    appearance: str = "System"
    theme: str = "Default"
    window_full_screen: bool = False
    input_order: str = "Cell First"
    error_check: str = "Rule Conflicts"
    highlight_digits: bool = True
    dim_completed_digits: bool = True
    highlight_peers: bool = True
    drag_answers_as_candidates: bool = True
    cleanup_notes: bool = True
    show_timer: bool = True
    daily_enabled: bool = False
    daily_minimum: str = "Easy"
    daily_maximum: str = "Extreme"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preferences":
        """Load recognized, correctly typed settings while tolerating new fields."""
        result: Preferences = cls()
        choices: dict[str, tuple[str, ...]] = {
            "appearance": ("System", "Light", "Dark"),
            "theme": THEME_NAMES,
            "input_order": ("Cell First", "Number First"),
            "error_check": ("Off", "Rule Conflicts", "Against Solution"),
            "daily_minimum": LEVELS,
            "daily_maximum": LEVELS,
        }
        for name, options in choices.items():
            if data.get(name) in options:
                setattr(result, name, data[name])
        if LEVELS.index(result.daily_minimum) > LEVELS.index(result.daily_maximum):
            result.daily_minimum = "Easy"
            result.daily_maximum = "Extreme"
        for name in (
            "window_full_screen",
            "highlight_digits",
            "dim_completed_digits",
            "highlight_peers",
            "drag_answers_as_candidates",
            "cleanup_notes",
            "show_timer",
            "daily_enabled",
        ):
            if type(data.get(name)) is bool:
                setattr(result, name, data[name])
        return result


@dataclass(frozen=True)
class Snapshot:
    """One reversible board state, including verified hint eliminations."""

    values: tuple[int, ...]
    notes: tuple[frozenset[int], ...]
    excluded: tuple[frozenset[int], ...]
    colors: tuple[int, ...]


@dataclass
class Game:
    """Own all board mutations without depending on the GUI toolkit."""

    puzzle: Puzzle
    values: list[int] = field(default_factory=list)
    notes: list[set[int]] = field(default_factory=lambda: [set() for _ in range(81)])
    excluded: list[set[int]] = field(default_factory=lambda: [set() for _ in range(81)])
    colors: list[int] = field(default_factory=lambda: [0] * 81)
    undo_stack: list[Snapshot] = field(default_factory=list)
    redo_stack: list[Snapshot] = field(default_factory=list)
    elapsed: float = 0.0
    selected: int = 40
    active_digit: int = 1
    note_mode: bool = False
    color_mode: bool = False
    active_color: int = 1
    paused: bool = False
    attempt_id: str = field(default_factory=lambda: uuid4().hex)
    viewed_hint_stages: set[str] = field(default_factory=set)
    revealed_cells: set[int] = field(default_factory=set)
    incorrect_entries: set[tuple[int, int]] = field(default_factory=set)
    solved_at: str | None = None
    _group: Snapshot | None = None

    def __post_init__(self) -> None:
        """Start a new board from its immutable givens when no values were supplied."""
        if not self.values:
            self.values = list(self.puzzle.givens)

    def snapshot(self) -> Snapshot:
        """Capture immutable board content for history and persistence."""
        return Snapshot(
            tuple(self.values),
            tuple(map(frozenset, self.notes)),
            tuple(map(frozenset, self.excluded)),
            tuple(self.colors),
        )

    def restore(self, state: Snapshot) -> None:
        """Restore board content without changing the active tool or timer."""
        self.values = list(state.values)
        self.notes = list(map(set, state.notes))
        self.excluded = list(map(set, state.excluded))
        self.colors = list(state.colors)

    def _record(self, before: Snapshot) -> bool:
        """Record changed content unless a larger painting transaction owns it."""
        changed: bool = before != self.snapshot()
        if changed and self._group is None:
            self.undo_stack.append(before)
            self.undo_stack = self.undo_stack[-200:]
            self.redo_stack.clear()
        return changed

    def begin_gesture(self) -> None:
        """Group a sequence of pointer or keyboard edits into one undo action."""
        if self._group is None:
            self._group = self.snapshot()

    def end_gesture(self) -> bool:
        """Commit the pending gesture, if it changed the board."""
        if self._group is None:
            return False
        before: Snapshot = self._group
        self._group = None
        return self._record(before)

    def can_edit_answer(self, index: int, error_check: str = "Off") -> bool:
        """Protect givens and answers verified by the active solution-checking policy."""
        return (
            not self.paused
            and not self.puzzle.givens[index]
            and not (
                error_check == "Against Solution"
                and self.values[index] == self.puzzle.solution[index]
            )
        )

    def set_value(
        self, index: int, digit: int, cleanup: bool = True, *, error_check: str = "Off"
    ) -> bool:
        """Enter or clear an answer, optionally cleaning peer notes atomically."""
        if not self.can_edit_answer(index, error_check) or digit not in range(10):
            return False
        before: Snapshot = self.snapshot()
        if self.values[index] == digit:
            return False
        self.values[index] = digit
        if digit and digit != self.puzzle.solution[index]:
            self.incorrect_entries.add((index, digit))
        self.notes[index].clear()
        self.excluded = [set() for _ in range(81)]
        if digit and cleanup:
            for peer in PEERS[index]:
                self.notes[peer].discard(digit)
        return self._record(before)

    def mark(self, index: int, digit: int, operation: str = "toggle") -> bool:
        """Toggle, add, or remove a candidate without editing filled cells."""
        if self.paused or self.values[index] or digit not in DIGITS:
            return False
        before: Snapshot = self.snapshot()
        if operation == "remove" or (operation == "toggle" and digit in self.notes[index]):
            self.notes[index].discard(digit)
        else:
            self.notes[index].add(digit)
        return self._record(before)

    def candidate_stroke_operation(self, index: int, digit: int, force_remove: bool = False) -> str:
        """Choose one add/remove action for a candidate stroke from its first cell."""
        if force_remove or digit in self.notes[index]:
            return "remove"
        return "add"

    def color_stroke_operation(self, index: int) -> str:
        """Choose one color or eraser action for an entire stroke."""
        if self.active_color == 9:
            return "remove"
        return "remove" if self.colors[index] == self.active_color else "add"

    def paint_color(self, index: int, operation: str = "toggle") -> bool:
        """Set or clear a cell highlight, including on givens and filled cells."""
        if self.paused or not 0 <= index < 81:
            return False
        before: Snapshot = self.snapshot()
        if operation == "remove" or self.active_color == 9:
            self.colors[index] = 0
        elif operation == "toggle" and self.colors[index] == self.active_color:
            self.colors[index] = 0
        else:
            self.colors[index] = self.active_color
        return self._record(before)

    def clear_all_colors(self) -> bool:
        """Remove every cell highlight as one reversible board edit."""
        if self.paused:
            return False
        before: Snapshot = self.snapshot()
        self.colors = [0] * 81
        return self._record(before)

    def clear(self, index: int, *, error_check: str = "Off") -> bool:
        """Clear both an editable answer and its notes in one action."""
        if not self.can_edit_answer(index, error_check):
            return False
        before: Snapshot = self.snapshot()
        self.values[index] = 0
        self.notes[index].clear()
        self.excluded = [set() for _ in range(81)]
        return self._record(before)

    def fill_candidates(self) -> bool:
        """Replace notes with legal candidates based only on current constraints."""
        if self.paused:
            return False
        before: Snapshot = self.snapshot()
        self.notes = candidates(self.values)
        return self._record(before)

    def forced_single_placements(self) -> dict[int, int]:
        """Find naked and hidden singles without consulting manual notes or the solution."""
        options: list[set[int]] = self.logical_candidates()
        placements: dict[int, int] = {
            index: next(iter(available))
            for index, available in enumerate(options)
            if len(available) == 1
        }
        for unit in UNITS:
            for digit in sorted(DIGITS):
                cells: list[int] = [index for index in unit if digit in options[index]]
                if len(cells) == 1:
                    index: int = cells[0]
                    existing: int | None = placements.get(index)
                    if existing is not None and existing != digit:
                        return {}
                    placements[index] = digit
        return placements

    def _auto_complete_placements(self) -> dict[int, int]:
        """Combine logical singles with lone pencil marks checked against the solution."""
        placements: dict[int, int] = self.forced_single_placements()
        placements.update(
            {
                index: self.puzzle.solution[index]
                for index, notes in enumerate(self.notes)
                if not self.values[index] and notes == {self.puzzle.solution[index]}
            }
        )
        return placements

    def auto_complete_singles(self, cleanup: bool = True) -> int:
        """Cascade logical singles and correct lone pencil marks as one reversible edit."""
        if self.paused or self.complete or self.wrong_answers():
            return 0
        before: Snapshot = self.snapshot()
        completed: int = 0
        while placements := self._auto_complete_placements():
            for index, digit in sorted(placements.items()):
                if self.values[index]:
                    continue
                self.values[index] = digit
                self.notes[index].clear()
                if cleanup:
                    for peer in PEERS[index]:
                        self.notes[peer].discard(digit)
                completed += 1
            self.excluded = [set() for _ in range(81)]
        self._record(before)
        return completed

    def eliminate(self, removals: tuple[tuple[int, int], ...]) -> bool:
        """Apply verified hint exclusions and show remaining candidates in affected cells."""
        if self.paused:
            return False
        if any(
            self.values[index] or digit == self.puzzle.solution[index] for index, digit in removals
        ):
            raise ValueError("A hint attempted an invalid elimination")
        before: Snapshot = self.snapshot()
        legal: list[set[int]] = self.logical_candidates()
        for index, digit in removals:
            if not self.notes[index]:
                self.notes[index] = legal[index].copy()
            self.notes[index].discard(digit)
            self.excluded[index].add(digit)
        return self._record(before)

    def logical_candidates(self) -> list[set[int]]:
        """Return sound candidates without trusting the player's manual pencil marks."""
        return [
            legal - excluded
            for legal, excluded in zip(candidates(self.values), self.excluded, strict=True)
        ]

    def undo(self) -> bool:
        """Reverse the most recent complete board edit."""
        self.end_gesture()
        if self.paused or not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot())
        self.restore(self.undo_stack.pop())
        return True

    def redo(self) -> bool:
        """Reapply the most recently undone board edit."""
        if self.paused or not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot())
        self.restore(self.redo_stack.pop())
        return True

    def errors(self, mode: str) -> set[int]:
        """Return answer errors for the chosen optional checking policy."""
        if mode == "Rule Conflicts":
            return conflicts(self.values)
        if mode == "Against Solution":
            return self.wrong_answers()
        return set()

    def wrong_answers(self) -> set[int]:
        """Identify incorrect filled answers without treating missing notes as errors."""
        return {
            i for i, value in enumerate(self.values) if value and value != self.puzzle.solution[i]
        }

    @property
    def completed_digits(self) -> frozenset[int]:
        """Count completed digits from filled cells without checking the solution."""
        return frozenset(digit for digit in DIGITS if self.values.count(digit) >= 9)

    @property
    def complete(self) -> bool:
        """Report completion only when every value matches the validated solution."""
        return tuple(self.values) == self.puzzle.solution

    def move(self, row_delta: int, column_delta: int) -> int:
        """Move within board bounds without wrapping rows or columns."""
        row: int = max(0, min(8, self.selected // 9 + row_delta))
        column: int = max(0, min(8, self.selected % 9 + column_delta))
        self.selected = row * 9 + column
        return self.selected
