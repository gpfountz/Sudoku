# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Shared, immutable hint descriptions and coordinate formatting."""

from dataclasses import dataclass

from sudoku.engine import cell_name


@dataclass(frozen=True, order=True)
class HintNode:
    """One candidate, or an OR group of one digit in several cells."""

    cells: tuple[int, ...]
    digit: int

    def describe(self, truth: bool) -> str:
        """Describe a truth assignment without treating a group as individual truths."""
        locations: str = ", ".join(f"r{cell // 9 + 1}c{cell % 9 + 1}" for cell in self.cells)
        if len(self.cells) == 1:
            return f"{locations} {'=' if truth else '≠'} {self.digit}"
        return f"{'at least one' if truth else 'none'} of [{locations}] is {self.digit}"


@dataclass(frozen=True)
class HintLink:
    """A proved relationship: strong means at least one; weak means at most one."""

    start: HintNode
    end: HintNode
    strong: bool


def candidate_link(start: tuple[int, int], end: tuple[int, int], strong: bool) -> HintLink:
    """Create a link between two individual cell/digit candidates."""
    return HintLink(HintNode((start[0],), start[1]), HintNode((end[0],), end[1]), strong)


@dataclass(frozen=True)
class Hint:
    """An explainable deduction and the precise reversible actions it permits."""

    technique: str
    nudge: str
    explanation: str
    focus: tuple[int, ...]
    placements: tuple[tuple[int, int], ...] = ()
    eliminations: tuple[tuple[int, int], ...] = ()
    verified_eliminations: tuple[tuple[int, int], ...] = ()
    prerequisites: tuple[str, ...] = ()
    links: tuple[HintLink, ...] = ()


def unit_name(index: int) -> str:
    """Describe a row, column, or box using one-based numbering."""
    return f"{('row', 'column', 'box')[index // 9]} {index % 9 + 1}"


def removal_hint(
    name: str,
    nudge: str,
    reason: str,
    focus: tuple[int, ...],
    removals: list[tuple[int, int]],
    links: tuple[HintLink, ...] = (),
) -> Hint:
    """Attach explicit candidate removals to a logical pattern explanation."""
    detail: str = "; ".join(f"{digit} from {cell_name(index)}" for index, digit in removals)
    return Hint(
        name,
        nudge,
        f"{reason}\n\nRemove {detail}.",
        focus,
        eliminations=tuple(removals),
        links=links,
    )
