# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Bounded fish searches with explicit base, cover, and fin proofs."""

from collections.abc import Iterator
from itertools import combinations

from sudoku.engine import DIGITS, PEERS, UNITS, cell_name
from sudoku.hint_types import Hint, removal_hint, unit_name

UNIT_MASKS: tuple[int, ...] = tuple(sum(1 << cell for cell in unit) for unit in UNITS)
PEER_MASKS: tuple[int, ...] = tuple(sum(1 << cell for cell in peers) for peers in PEERS)
FISH_NAMES: dict[int, str] = {2: "X-Wing", 3: "Swordfish", 4: "Jellyfish"}


def cells(mask: int) -> tuple[int, ...]:
    """Decode a cell mask in stable board order."""
    result: list[int] = []
    while mask:
        bit: int = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return tuple(result)


def fish_hint(
    name: str,
    digit: int,
    bases: tuple[int, ...],
    covers: tuple[int, ...],
    base_mask: int,
    removals: int,
    fins: int = 0,
) -> Hint:
    """Explain the occupancy argument and both alternatives for any fins."""
    reason: str = (
        f"For {digit}, the base units are "
        + ", ".join(map(unit_name, bases))
        + ". The cover units are "
        + ", ".join(map(unit_name, covers))
        + ".\n\n"
        + f"Each of the {len(bases)} base units needs one {digit}, in distinct cells. "
        + "The cover units each hold at most one. With all base candidates covered, "
        + "every cover must be occupied by a base candidate, excluding other cells there."
    )
    if fins:
        reason += (
            "\n\nThe uncovered candidates (fins) are "
            + "; ".join(cell_name(cell) for cell in cells(fins))
            + ". If all fins are false, the fish applies. If any fin is true, it excludes "
            + f"{digit} from each target, because each target sees every fin."
        )
    return removal_hint(
        name,
        f"Compare the base and cover units for {digit}.",
        reason,
        cells(base_mask),
        [(cell, digit) for cell in cells(removals)],
    )


def finned_fish_hints(options: list[set[int]], size: int) -> Iterator[Hint]:
    """Find finned and sashimi basic fish in both orientations, including multiple fins."""
    for digit in sorted(DIGITS):
        available: int = sum(1 << cell for cell in range(81) if digit in options[cell])
        for offset in (0, 9):
            masks: dict[int, int] = {
                u: UNIT_MASKS[u] & available for u in range(offset, offset + 9)
            }
            eligible: list[int] = [u for u, mask in masks.items() if mask.bit_count() >= 2]
            other: range = range(9, 18) if offset == 0 else range(9)
            for bases in combinations(eligible, size):
                base_mask: int = sum(masks[u] for u in bases)
                for covers in combinations(other, size):
                    cover_mask: int = sum(UNIT_MASKS[u] for u in covers)
                    fins: int = base_mask & ~cover_mask
                    if not fins:
                        continue
                    removals: int = available & cover_mask & ~base_mask
                    for cell in cells(fins):
                        removals &= PEER_MASKS[cell]
                        if not removals:
                            break
                    if not removals:
                        continue
                    # Each base must retain a covered position when all fins are false.
                    counts: list[int] = [(masks[u] & cover_mask).bit_count() for u in bases]
                    if 0 in counts:
                        continue
                    prefix: str = "Sashimi" if 1 in counts else "Finned"
                    yield fish_hint(
                        f"{prefix} {FISH_NAMES[size]}",
                        digit,
                        bases,
                        covers,
                        base_mask,
                        removals,
                        fins,
                    )


def cover_sets(
    remaining: int,
    candidates: tuple[tuple[int, int], ...],
    chosen: tuple[int, ...],
    size: int,
) -> Iterator[tuple[int, ...]]:
    """Enumerate exact covers of disjoint base candidates without permuting equivalent sets."""
    if not remaining:
        if len(chosen) == size:
            yield tuple(sorted(chosen))
        return
    slots: int = size - len(chosen)
    if slots <= 0:
        return
    fitting: tuple[tuple[int, int], ...] = tuple(
        (unit, mask) for unit, mask in candidates if mask & remaining == mask
    )
    if (
        not fitting
        or sum(sorted((m.bit_count() for _, m in fitting), reverse=True)[:slots])
        < remaining.bit_count()
    ):
        return
    first: int = remaining & -remaining
    for unit, mask in fitting:
        if mask & first:
            yield from cover_sets(remaining ^ mask, fitting, chosen + (unit,), size)


def complex_fish_hints(options: list[set[int]], size: int) -> Iterator[Hint]:
    """Find non-overlapping Franken and Mutant fish using rows, columns, and boxes."""
    for digit in sorted(DIGITS):
        available: int = sum(1 << cell for cell in range(81) if digit in options[cell])
        masks: tuple[int, ...] = tuple(mask & available for mask in UNIT_MASKS)
        eligible: list[int] = [
            u for u, mask in enumerate(masks) if 2 <= mask.bit_count() <= size * 3
        ]
        for bases in combinations(eligible, size):
            base_mask: int = 0
            for unit in bases:
                if base_mask & masks[unit]:
                    break
                base_mask |= masks[unit]
            else:
                candidates: tuple[tuple[int, int], ...] = tuple(
                    (unit, mask & base_mask)
                    for unit, mask in enumerate(masks)
                    if unit not in bases and mask & base_mask
                )
                for covers in cover_sets(base_mask, candidates, (), size):
                    base_axes: set[int] = {unit // 9 for unit in bases}
                    cover_axes: set[int] = {unit // 9 for unit in covers}
                    if (base_axes, cover_axes) in (({0}, {1}), ({1}, {0})):
                        continue
                    removals: int = available & ~base_mask
                    cover_mask: int = 0
                    for unit in covers:
                        cover_mask |= UNIT_MASKS[unit]
                    removals &= cover_mask
                    if not removals:
                        continue
                    franken: bool = any(
                        base_axes <= {axis, 2} and cover_axes <= {1 - axis, 2} for axis in (0, 1)
                    )
                    yield fish_hint(
                        f"{'Franken' if franken else 'Mutant'} {FISH_NAMES[size]}",
                        digit,
                        bases,
                        covers,
                        base_mask,
                        removals,
                    )


def finned_cover_sets(
    remaining: int,
    candidates: tuple[tuple[int, int], ...],
    chosen: tuple[int, ...],
    used: int,
    size: int,
    budget: list[int],
) -> Iterator[tuple[int, ...]]:
    """Cover every non-fin candidate, optionally covering more, under a shared visit limit."""
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if len(chosen) == size:
        if not remaining:
            yield tuple(sorted(chosen))
        return
    first: int = remaining & -remaining
    for position, (unit, mask) in enumerate(candidates):
        if mask & used or (first and not mask & first):
            continue
        # Once all required cells are covered, enumerate optional covers in sorted order.
        following: tuple[tuple[int, int], ...] = candidates if first else candidates[position + 1 :]
        yield from finned_cover_sets(
            remaining & ~mask,
            following,
            chosen + (unit,),
            used | mask,
            size,
            budget,
        )


def finned_complex_fish_hints(options: list[set[int]], size: int) -> Iterator[Hint]:
    """Find finned Franken/Mutant fish with all exo fins in one box; bound search visits."""
    budget: list[int] = [30000]
    seen: set[tuple[int, tuple[int, ...], tuple[int, ...]]] = set()
    for digit in sorted(DIGITS):
        available: int = sum(1 << cell for cell in range(81) if digit in options[cell])
        masks: tuple[int, ...] = tuple(mask & available for mask in UNIT_MASKS)
        eligible: list[int] = [
            unit for unit, mask in enumerate(masks) if 2 <= mask.bit_count() <= size * 3
        ]
        for bases in combinations(eligible, size):
            base_mask: int = 0
            for unit in bases:
                if base_mask & masks[unit]:
                    break
                base_mask |= masks[unit]
            else:
                candidates: tuple[tuple[int, int], ...] = tuple(
                    (unit, mask & base_mask)
                    for unit, mask in enumerate(masks)
                    if unit not in bases and mask & base_mask
                )
                for box in UNIT_MASKS[18:]:
                    required: int = base_mask & ~box
                    if required == base_mask or not required:
                        continue
                    for covers in finned_cover_sets(required, candidates, (), 0, size, budget):
                        key: tuple[int, tuple[int, ...], tuple[int, ...]] = (digit, bases, covers)
                        if key in seen:
                            continue
                        seen.add(key)
                        base_axes: set[int] = {unit // 9 for unit in bases}
                        cover_axes: set[int] = {unit // 9 for unit in covers}
                        if (base_axes, cover_axes) in (({0}, {1}), ({1}, {0})):
                            continue
                        cover_mask: int = 0
                        for unit in covers:
                            cover_mask |= UNIT_MASKS[unit]
                        fins: int = base_mask & ~cover_mask
                        if not fins:
                            continue
                        removals: int = available & cover_mask & ~base_mask
                        for cell in cells(fins):
                            removals &= PEER_MASKS[cell]
                        if removals:
                            franken: bool = any(
                                base_axes <= {axis, 2} and cover_axes <= {1 - axis, 2}
                                for axis in (0, 1)
                            )
                            yield fish_hint(
                                f"Finned {'Franken' if franken else 'Mutant'} {FISH_NAMES[size]}",
                                digit,
                                bases,
                                covers,
                                base_mask,
                                removals,
                                fins,
                            )
                    if budget[0] <= 0:
                        return
