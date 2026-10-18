# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Human-style deductions and an explicitly solution-based candidate review."""

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from itertools import chain, combinations

from sudoku.engine import BOXES, COLUMNS, DIGITS, PEERS, ROWS, UNITS, candidates, cell_name
from sudoku.hint_chains import inference_chain_hints
from sudoku.hint_fish import complex_fish_hints, finned_complex_fish_hints, finned_fish_hints
from sudoku.hint_types import Hint, HintLink, candidate_link, removal_hint, unit_name
from sudoku.hint_uniqueness import uniqueness_hints
from sudoku.model import Game


def singles(options: list[set[int]]) -> Hint | None:
    """Return the first matching deduction for this technique."""
    return next(singles_hints(options), None)


def singles_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find a cell with one candidate or a digit with one place in a unit."""
    for index, available in enumerate(options):
        if len(available) == 1:
            digit: int = next(iter(available))
            yield Hint(
                "Naked Single",
                f"Inspect the candidates at {cell_name(index)}.",
                f"Only {digit} remains possible at {cell_name(index)}. "
                "Every other digit is excluded by its peers or earlier verified deductions.",
                (index,),
                ((index, digit),),
            )
    for unit_index, unit in enumerate(UNITS):
        for digit in sorted(DIGITS):
            cells: tuple[int, ...] = tuple(i for i in unit if digit in options[i])
            if len(cells) == 1:
                yield Hint(
                    "Hidden Single",
                    f"Look for places for {digit} in {unit_name(unit_index)}.",
                    f"In {unit_name(unit_index)}, {digit} can appear only at "
                    f"{cell_name(cells[0])}. Place {digit} there.",
                    unit,
                    ((cells[0], digit),),
                )


def locked_candidates(options: list[set[int]]) -> Hint | None:
    """Return the first matching deduction for this technique."""
    return next(locked_candidates_hints(options), None)


def locked_candidates_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find pointing and claiming intersections between boxes and lines."""
    for source_index, source in enumerate(UNITS):
        targets: tuple[tuple[int, ...], ...] = BOXES if source_index < 18 else ROWS + COLUMNS
        for digit in sorted(DIGITS):
            places: tuple[int, ...] = tuple(i for i in source if digit in options[i])
            if len(places) < 2:
                continue
            for target in targets:
                if not set(places).issubset(target):
                    continue
                removals: list[tuple[int, int]] = [
                    (i, digit) for i in target if i not in source and digit in options[i]
                ]
                if removals:
                    target_name: str = unit_name(UNITS.index(target))
                    yield removal_hint(
                        "Locked Candidates",
                        f"Look at where {digit} fits in {unit_name(source_index)}.",
                        f"All possible positions for {digit} in {unit_name(source_index)} "
                        f"also lie in {target_name}. Therefore {digit} cannot occur elsewhere "
                        f"in {target_name}.",
                        places,
                        removals,
                    )


def subsets(options: list[set[int]], size: int, hidden: bool) -> Hint | None:
    """Return the first matching deduction for this technique."""
    return next(subsets_hints(options, size, hidden), None)


def subsets_hints(options: list[set[int]], size: int, hidden: bool) -> Iterator[Hint]:
    """Find naked or hidden pairs, triples, or quads in a row, column, or box."""
    for unit_index, unit in enumerate(UNITS):
        empty: tuple[int, ...] = tuple(i for i in unit if options[i])
        if hidden:
            digit_groups: list[tuple[int, ...]] = list(combinations(sorted(DIGITS), size))
            for group in digit_groups:
                places: tuple[int, ...] = tuple(i for i in empty if options[i].intersection(group))
                if len(places) != size or not all(
                    any(d in options[i] for i in places) for d in group
                ):
                    continue
                removals: list[tuple[int, int]] = [
                    (i, d) for i in places for d in sorted(options[i] - set(group))
                ]
                if removals:
                    yield subset_hint(unit_index, places, group, removals, True)
        else:
            eligible: tuple[int, ...] = tuple(i for i in empty if 2 <= len(options[i]) <= size)
            for places in combinations(eligible, size):
                digits: set[int] = set().union(*(options[i] for i in places))
                if len(digits) != size:
                    continue
                removals = [
                    (i, d) for i in empty if i not in places for d in sorted(options[i] & digits)
                ]
                if removals:
                    yield subset_hint(unit_index, places, tuple(sorted(digits)), removals, False)


def subset_hint(
    unit_index: int,
    places: tuple[int, ...],
    digits: tuple[int, ...],
    removals: list[tuple[int, int]],
    hidden: bool,
) -> Hint:
    """Explain the shared occupancy argument behind pairs, triples, and quads."""
    size_name: str = {2: "Pair", 3: "Triple", 4: "Quad"}[len(places)]
    name: str = f"{'Hidden' if hidden else 'Naked'} {size_name}"
    locations: str = "; ".join(map(cell_name, places))
    numbers: str = ", ".join(map(str, digits))
    reason: str = (
        f"In {unit_name(unit_index)}, digits {numbers} are confined to these cells: {locations}. "
        "Those cells must hold those digits, so their other candidates can be removed."
        if hidden
        else f"These cells in {unit_name(unit_index)} contain only candidates {numbers}: "
        f"{locations}. "
        "They must use those digits between them, excluding them from other cells in the unit."
    )
    return removal_hint(
        name, f"Look for a {name.lower()} in {unit_name(unit_index)}.", reason, places, removals
    )


def x_wing(options: list[set[int]]) -> Hint | None:
    """Return the first matching deduction for this technique."""
    return next(x_wing_hints(options), None)


def x_wing_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find a two-row or two-column fish with matching candidate positions."""
    yield from fish_hints(options, 2)


def xy_wing(options: list[set[int]]) -> Hint | None:
    """Return the first matching deduction for this technique."""
    return next(xy_wing_hints(options), None)


def xy_wing_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find a bivalue pivot whose two wings force a shared candidate."""
    for pivot, pair in enumerate(options):
        if len(pair) != 2:
            continue
        wings: list[int] = [
            i for i in sorted(PEERS[pivot]) if len(options[i]) == 2 and len(options[i] & pair) == 1
        ]
        for first, second in combinations(wings, 2):
            if options[first] & pair == options[second] & pair:
                continue
            common: set[int] = options[first] & options[second] - pair
            if len(common) != 1:
                continue
            digit: int = next(iter(common))
            removals: list[tuple[int, int]] = [
                (i, digit)
                for i in sorted(PEERS[first] & PEERS[second])
                if i not in (pivot, first, second) and digit in options[i]
            ]
            if removals:
                first_digit: int = next(iter(options[first] & pair))
                second_digit: int = next(iter(options[second] & pair))
                yield removal_hint(
                    "XY-Wing",
                    f"Inspect the two-candidate cell at {cell_name(pivot)} and its peers.",
                    f"The pivot at {cell_name(pivot)} sees wings at {cell_name(first)} "
                    f"and {cell_name(second)}. "
                    f"Either value of the pivot forces one wing to be {digit}. "
                    f"Any cell that sees both wings therefore cannot be {digit}.",
                    (pivot, first, second),
                    removals,
                    (
                        candidate_link((first, digit), (first, first_digit), True),
                        candidate_link((first, first_digit), (pivot, first_digit), False),
                        candidate_link((pivot, first_digit), (pivot, second_digit), True),
                        candidate_link((pivot, second_digit), (second, second_digit), False),
                        candidate_link((second, second_digit), (second, digit), True),
                    ),
                )


def explain_hint(game: Game, hint: Hint) -> Hint:
    """Attach concrete row, column, and box evidence to single-cell hints."""
    if hint.technique != "Naked Single":
        return hint
    index: int = hint.placements[0][0]
    evidence: list[str] = []
    witnesses: set[int] = {index}
    for unit_index, unit in enumerate(UNITS):
        if index in unit:
            filled: set[int] = {i for i in unit if game.values[i]}
            digits: str = ", ".join(map(str, sorted({game.values[i] for i in filled})))
            if digits:
                evidence.append(f"{unit_name(unit_index).capitalize()} already contains {digits}.")
                witnesses.update(filled)
    if game.excluded[index]:
        digits = ", ".join(map(str, sorted(game.excluded[index])))
        evidence.append(f"Earlier verified deductions excluded {digits} from this cell.")
    return Hint(
        hint.technique,
        hint.nudge,
        "\n".join(evidence) + f"\n\nOnly {hint.placements[0][1]} remains at {cell_name(index)}.",
        tuple(sorted(witnesses)),
        hint.placements,
    )


def swordfish_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find three lines whose candidate positions occupy exactly three crossing lines."""
    yield from fish_hints(options, 3)


def jellyfish_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find four lines whose candidate positions occupy exactly four crossing lines."""
    yield from fish_hints(options, 4)


def fish_hints(options: list[set[int]], size: int) -> Iterator[Hint]:
    """Apply the shared occupancy proof for basic fish in either orientation."""
    name: str = {2: "X-Wing", 3: "Swordfish", 4: "Jellyfish"}[size]
    for transpose in (False, True):
        lines: tuple[tuple[int, ...], ...] = COLUMNS if transpose else ROWS
        for digit in sorted(DIGITS):
            positions: list[set[int]] = [
                {offset for offset, index in enumerate(line) if digit in options[index]}
                for line in lines
            ]
            eligible: list[int] = [line for line in range(9) if 2 <= len(positions[line]) <= size]
            for selected in combinations(eligible, size):
                crossing: set[int] = set().union(*(positions[line] for line in selected))
                if len(crossing) != size:
                    continue
                removals: list[tuple[int, int]] = [
                    (lines[line][offset], digit)
                    for line in range(9)
                    if line not in selected
                    for offset in sorted(crossing)
                    if digit in options[lines[line][offset]]
                ]
                if removals:
                    axis: str = "columns" if transpose else "rows"
                    other: str = "rows" if transpose else "columns"
                    focus: tuple[int, ...] = tuple(
                        lines[line][offset]
                        for line in selected
                        for offset in sorted(positions[line])
                    )
                    yield removal_hint(
                        name,
                        f"Compare the positions for {digit} in {axis} "
                        + ", ".join(str(line + 1) for line in selected)
                        + ".",
                        f"These {size} {axis} must each contain {digit}. All their possible "
                        f"positions lie in {other} "
                        + ", ".join(str(offset + 1) for offset in sorted(crossing))
                        + f". Those {size} {other} are occupied by these {size} copies of "
                        f"{digit}, excluding it from other cells in those {other}.",
                        focus,
                        removals,
                    )


def strong_links(options: list[set[int]], digit: int) -> list[tuple[int, int, int]]:
    """Find units with exactly two possible positions for a digit."""
    links: list[tuple[int, int, int]] = []
    for unit_index, unit in enumerate(UNITS):
        places: list[int] = [index for index in unit if digit in options[index]]
        if len(places) == 2:
            links.append((places[0], places[1], unit_index))
    return links


def xyz_wing_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Use a three-candidate pivot and two bivalue wings to exclude their shared digit."""
    for pivot, triple in enumerate(options):
        if len(triple) != 3:
            continue
        wings: list[int] = [
            index
            for index in sorted(PEERS[pivot])
            if len(options[index]) == 2 and options[index] < triple
        ]
        for first, second in combinations(wings, 2):
            if options[first] | options[second] != triple:
                continue
            digit: int = next(iter(options[first] & options[second]))
            removals: list[tuple[int, int]] = [
                (index, digit)
                for index in sorted(PEERS[pivot] & PEERS[first] & PEERS[second])
                if digit in options[index]
            ]
            if not removals:
                continue
            cases: list[str] = [f"If {cell_name(pivot)} is {digit}, it supplies {digit} itself."]
            for wing in (first, second):
                other: int = next(iter(options[wing] - {digit}))
                cases.append(
                    f"If {cell_name(pivot)} is {other}, {cell_name(wing)} must be {digit}."
                )
            yield removal_hint(
                "XYZ-Wing",
                f"Inspect the three candidates at {cell_name(pivot)} and its wings.",
                "\n".join(cases) + f"\n\nAt least one of these three cells is {digit}. "
                f"Any cell that sees all three cannot contain {digit}.",
                (pivot, first, second),
                removals,
            )


def w_wing_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Connect identical bivalue cells through a unit's forced pair on one digit."""
    bivalue: list[int] = [index for index, available in enumerate(options) if len(available) == 2]
    links: dict[int, list[tuple[int, int, int]]] = {
        digit: strong_links(options, digit) for digit in sorted(DIGITS)
    }
    for first, second in combinations(bivalue, 2):
        if options[first] != options[second] or second in PEERS[first]:
            continue
        for linked_digit in sorted(options[first]):
            digit: int = next(iter(options[first] - {linked_digit}))
            removals: list[tuple[int, int]] = [
                (index, digit)
                for index in sorted(PEERS[first] & PEERS[second])
                if digit in options[index]
            ]
            if not removals:
                continue
            for start, end, unit_index in links[linked_digit]:
                if len({first, second, start, end}) != 4:
                    continue
                for a, b in ((start, end), (end, start)):
                    if a not in PEERS[first] or b not in PEERS[second]:
                        continue
                    yield removal_hint(
                        "W-Wing",
                        f"Compare the identical pairs at {cell_name(first)} "
                        f"and {cell_name(second)}.",
                        f"In {unit_name(unit_index)}, {linked_digit} can occur only at "
                        f"{cell_name(a)} or {cell_name(b)}. If it is at {cell_name(a)}, "
                        f"{cell_name(first)} must be {digit}. If it is at {cell_name(b)}, "
                        f"{cell_name(second)} must be {digit}.\n\nAt least one of the two "
                        f"pair cells is {digit}; cells seeing both cannot contain {digit}.",
                        (first, a, b, second),
                        removals,
                        (
                            candidate_link((first, digit), (first, linked_digit), True),
                            candidate_link((first, linked_digit), (a, linked_digit), False),
                            candidate_link((a, linked_digit), (b, linked_digit), True),
                            candidate_link((b, linked_digit), (second, linked_digit), False),
                            candidate_link((second, linked_digit), (second, digit), True),
                        ),
                    )


def color_components(links: list[tuple[int, int, int]]) -> Iterator[dict[int, int]]:
    """Assign opposite groups across strong links, rejecting inconsistent components."""
    graph: dict[int, set[int]] = {}
    for first, second, _ in links:
        graph.setdefault(first, set()).add(second)
        graph.setdefault(second, set()).add(first)
    visited: set[int] = set()
    for root in sorted(graph):
        if root in visited:
            continue
        colors: dict[int, int] = {root: 0}
        pending: list[int] = [root]
        consistent: bool = True
        while pending:
            current: int = pending.pop()
            for neighbor in sorted(graph[current]):
                if neighbor not in colors:
                    colors[neighbor] = 1 - colors[current]
                    pending.append(neighbor)
                elif colors[neighbor] == colors[current]:
                    consistent = False
        visited.update(colors)
        if consistent:
            yield colors


def coloring_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Find simple-coloring traps and wraps using only independently forced pairs."""
    for digit in sorted(DIGITS):
        links: list[tuple[int, int, int]] = strong_links(options, digit)
        for colors in color_components(links):
            groups: tuple[set[int], set[int]] = (
                {index for index, color in colors.items() if color == 0},
                {index for index, color in colors.items() if color == 1},
            )
            focus: tuple[int, ...] = tuple(sorted(colors))
            reason: str = coloring_reason(digit, links, groups)
            visual_links: tuple[HintLink, ...] = tuple(
                candidate_link((first, digit), (second, digit), True)
                for first, second, _ in links
                if first in colors and second in colors
            )
            for label, group in zip(("A", "B"), groups, strict=True):
                conflict: tuple[int, int] | None = next(
                    ((a, b) for a, b in combinations(sorted(group), 2) if b in PEERS[a]), None
                )
                if conflict:
                    yield removal_hint(
                        "Color Wrap",
                        f"Follow the linked pairs for {digit}.",
                        reason + f"\n\nIn group {label}, {cell_name(conflict[0])} and "
                        f"{cell_name(conflict[1])} see each other. They cannot both be {digit}, "
                        f"so every candidate in group {label} is false.",
                        focus,
                        [(index, digit) for index in sorted(group)],
                        visual_links
                        + (candidate_link((conflict[0], digit), (conflict[1], digit), False),),
                    )
            removals: list[tuple[int, int]] = [
                (index, digit)
                for index, available in enumerate(options)
                if digit in available
                and index not in colors
                and PEERS[index] & groups[0]
                and PEERS[index] & groups[1]
            ]
            if removals:
                yield removal_hint(
                    "Color Trap",
                    f"Follow the linked pairs for {digit}.",
                    reason + "\n\nEach target cell sees at least one member of both groups. "
                    f"Whichever group is true, it excludes {digit} from that target.",
                    focus,
                    removals,
                    visual_links,
                )


def coloring_reason(
    digit: int, links: list[tuple[int, int, int]], groups: tuple[set[int], set[int]]
) -> str:
    """Explain the actual forced pairs and the two consistent truth assignments."""
    cells: set[int] = groups[0] | groups[1]
    pairs: int = sum(1 for first, second, _ in links if first in cells and second in cells)
    return (
        f"The {pairs} solid links connect forced pairs of {digit}.\n\nGroup A: "
        + "; ".join(map(cell_name, sorted(groups[0])))
        + "\nGroup B: "
        + "; ".join(map(cell_name, sorted(groups[1])))
        + f"\n\nFollowing those pairs, either every member of A is {digit} and B is false, "
        "or every member of B is true and A is false."
    )


def turbot_chain_hints(options: list[set[int]]) -> Iterator[Hint]:
    """Link two forced pairs to find skyscrapers, two-string kites, and other turbot chains."""
    for digit in sorted(DIGITS):
        links: list[tuple[int, int, int]] = strong_links(options, digit)
        for first, second in combinations(links, 2):
            if len(set(first[:2] + second[:2])) != 4:
                continue
            for a, b in (first[:2], first[:2][::-1]):
                for c, d in (second[:2], second[:2][::-1]):
                    if c not in PEERS[b]:
                        continue
                    removals: list[tuple[int, int]] = [
                        (index, digit)
                        for index in sorted(PEERS[a] & PEERS[d])
                        if index not in (a, b, c, d) and digit in options[index]
                    ]
                    if not removals:
                        continue
                    axes: tuple[int, int] = (first[2] // 9, second[2] // 9)
                    name: str = (
                        "Skyscraper"
                        if axes in ((0, 0), (1, 1))
                        else "Two-String Kite"
                        if set(axes) == {0, 1} and any(b in box and c in box for box in BOXES)
                        else "Turbot Chain"
                    )
                    yield removal_hint(
                        name,
                        f"Follow the two linked pairs of {digit} candidates.",
                        f"If {cell_name(a)} is not {digit}, {cell_name(b)} must be {digit}. "
                        f"That excludes {digit} at {cell_name(c)}, forcing {cell_name(d)} "
                        f"to be {digit}. So at least one end ({cell_name(a)} or "
                        f"{cell_name(d)}) is {digit}. Cells that see both ends cannot be {digit}.",
                        (a, b, c, d),
                        removals,
                        (
                            candidate_link((a, digit), (b, digit), True),
                            candidate_link((b, digit), (c, digit), False),
                            candidate_link((c, digit), (d, digit), True),
                        ),
                    )


def xy_chain_hints(
    options: list[set[int]], max_cells: int = 24, min_cells: int = 4
) -> Iterator[Hint]:
    """Search shortest bivalue paths first, up to 24 cells and 60,000 visited states."""
    bivalue: set[int] = {index for index, available in enumerate(options) if len(available) == 2}
    budget: int = 60000
    for start in sorted(bivalue):
        for target in sorted(options[start]):
            first: int = next(iter(options[start] - {target}))
            queue: deque[tuple[tuple[int, ...], int]] = deque([((start,), first)])
            seen: set[tuple[int, int]] = {(start, first)}
            while queue and budget > 0:
                path, forced = queue.popleft()
                budget -= 1
                end: int = path[-1]
                if len(path) >= 4 and forced == target:
                    removals: list[tuple[int, int]] = [
                        (index, target)
                        for index in sorted(PEERS[start] & PEERS[end])
                        if index not in path and target in options[index]
                    ]
                    if removals and len(path) >= min_cells:
                        steps: list[str] = [
                            f"Suppose {cell_name(start)} is not {target}. It must be {first}."
                        ]
                        previous: int = first
                        visual_links: list[HintLink] = [
                            candidate_link((start, target), (start, first), True)
                        ]
                        previous_cell: int = start
                        for index in path[1:]:
                            value: int = next(iter(options[index] - {previous}))
                            steps.append(f"Then r{index // 9 + 1}c{index % 9 + 1} = {value}.")
                            visual_links.extend(
                                (
                                    candidate_link(
                                        (previous_cell, previous), (index, previous), False
                                    ),
                                    candidate_link((index, previous), (index, value), True),
                                )
                            )
                            previous = value
                            previous_cell = index
                        yield removal_hint(
                            "XY-Chain",
                            f"Follow the two-candidate cells starting at {cell_name(start)}.",
                            "\n".join(steps)
                            + f"\n\nEither the first or last cell must be {target}. "
                            "Any cell that sees both endpoints cannot contain it.",
                            path,
                            removals,
                            tuple(visual_links),
                        )
                    continue
                if len(path) >= max_cells:
                    continue
                for neighbor in sorted(PEERS[end] & bivalue - set(path)):
                    if forced in options[neighbor]:
                        next_digit: int = next(iter(options[neighbor] - {forced}))
                        state: tuple[int, int] = (neighbor, next_digit)
                        if state not in seen:
                            seen.add(state)
                            queue.append((path + (neighbor,), next_digit))


def invalid_candidate_hint(game: Game) -> Hint | None:
    """Find the first pencil mark ruled out by an answer or an applied elimination."""
    legal: list[set[int]] = candidates(game.values)
    logical: list[set[int]] = game.logical_candidates()
    for index, notes in enumerate(game.notes):
        if game.values[index]:
            continue
        for digit in sorted(notes - logical[index]):
            blocker: int | None = next(
                (peer for peer in sorted(PEERS[index]) if game.values[peer] == digit), None
            )
            if blocker is not None:
                relation: str = (
                    "row"
                    if index // 9 == blocker // 9
                    else "column"
                    if index % 9 == blocker % 9
                    else "box"
                )
                reason: str = (
                    f"{digit} at {cell_name(index)} conflicts with the {digit} already "
                    f"placed at {cell_name(blocker)} in the same {relation}. "
                    "Remove this pencil mark before following another deduction."
                )
                focus: tuple[int, ...] = (index, blocker)
            elif digit in game.excluded[index] and digit in legal[index]:
                reason = (
                    f"An earlier applied hint ruled out {digit} at {cell_name(index)}, "
                    "but that pencil mark is still on the board. Remove it before "
                    "following another deduction."
                )
                focus = (index,)
            else:
                continue
            return Hint(
                "Candidate Review",
                f"Check the {digit} penciled into {cell_name(index)}.",
                reason,
                focus,
                eliminations=((index, digit),),
            )
    return None


def candidate_review(game: Game) -> Hint | None:
    """Prioritize invalid marks, then find marked cells missing their answer digit."""
    invalid: Hint | None = invalid_candidate_hint(game)
    if invalid:
        return invalid
    missing: tuple[tuple[int, int], ...] = tuple(
        (index, game.puzzle.solution[index])
        for index, notes in enumerate(game.notes)
        if not game.values[index] and notes and game.puzzle.solution[index] not in notes
    )
    if not missing:
        return None
    detail: str = "\n".join(
        f"{cell_name(index)} is missing candidate {digit}." for index, digit in missing
    )
    return Hint(
        "Candidate Review",
        "Some candidate marks are invalid: one or more marked cells are missing their "
        "correct answer. Review your pencil marks. This check uses the saved solution.",
        detail + "\n\nThese candidates match the saved solution. Apply fills these cells "
        "with their answers as one undoable change.",
        tuple(index for index, _ in missing),
        placements=missing,
    )


def hint_searches(game: Game) -> tuple[Callable[[list[set[int]]], Iterator[Hint]], ...]:
    """Order technique tiers explicitly, keeping expensive general searches last."""
    return (
        singles_hints,
        locked_candidates_hints,
        lambda options: subsets_hints(options, 2, False),
        lambda options: subsets_hints(options, 2, True),
        lambda options: subsets_hints(options, 3, False),
        lambda options: subsets_hints(options, 3, True),
        lambda options: subsets_hints(options, 4, False),
        lambda options: subsets_hints(options, 4, True),
        x_wing_hints,
        xy_wing_hints,
        xyz_wing_hints,
        w_wing_hints,
        swordfish_hints,
        jellyfish_hints,
        turbot_chain_hints,
        coloring_hints,
        lambda options: uniqueness_hints(game, options),
        lambda options: xy_chain_hints(options, max_cells=8),
        lambda options: finned_fish_hints(options, 2),
        lambda options: finned_fish_hints(options, 3),
        lambda options: finned_fish_hints(options, 4),
        lambda options: xy_chain_hints(options, min_cells=9),
        lambda options: complex_fish_hints(options, 2),
        lambda options: complex_fish_hints(options, 3),
        lambda options: complex_fish_hints(options, 4),
        lambda options: finned_complex_fish_hints(options, 2),
        lambda options: finned_complex_fish_hints(options, 3),
        lambda options: finned_complex_fish_hints(options, 4),
        inference_chain_hints,
        lambda options: inference_chain_hints(options, grouped=True),
    )


def iter_hints(game: Game) -> Iterator[Hint]:
    """Exhaust simpler tiers and their already-completed deductions before advancing."""
    if game.wrong_answers() or game.complete or game.paused:
        return
    review: Hint | None = candidate_review(game)
    if review:
        yield review
        return
    options: list[set[int]] = game.logical_candidates()
    seen: set[tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]] = set()
    verified: set[tuple[int, int]] = set()
    prerequisites: list[str] = []
    searches: tuple[Callable[[list[set[int]]], Iterator[Hint]], ...] = hint_searches(game)
    cache: dict[int, list[Hint]] = {}
    for tier in range(len(searches)):
        while True:
            pending: set[tuple[int, int]] = set()
            reasons: list[str] = []
            available: list[Hint] = []
            for index in range(tier + 1):
                if index not in cache:
                    cache[index] = list(searches[index](options))
            for hint in chain.from_iterable(cache[index] for index in range(tier + 1)):
                absent: tuple[tuple[int, int], ...] = tuple(
                    (index, digit)
                    for index, digit in hint.eliminations
                    if digit in options[index] and digit not in game.notes[index]
                )
                if set(absent) - pending:
                    pending.update(absent)
                    proof: Hint = removal_hint(
                        hint.technique,
                        hint.nudge,
                        hint.explanation.split("\n\nRemove ")[0],
                        hint.focus,
                        list(absent),
                        hint.links,
                    )
                    reasons.append(f"{hint.technique}: {proof.explanation}")
                if hint.eliminations:
                    removals: list[tuple[int, int]] = [
                        (index, digit)
                        for index, digit in hint.eliminations
                        if digit in game.notes[index]
                    ]
                    if not removals:
                        continue
                    hint = removal_hint(
                        hint.technique,
                        hint.nudge,
                        hint.explanation.split("\n\nRemove ")[0],
                        hint.focus,
                        removals,
                        hint.links,
                    )
                available.append(hint)
            if pending:
                # Reach closure first: an already-completed removal may expose a single.
                for index, digit in pending:
                    options[index].discard(digit)
                cache.clear()
                verified.update(pending)
                prerequisites.extend(reasons)
                continue
            for hint in available:
                key = (tuple(sorted(hint.placements)), tuple(sorted(hint.eliminations)))
                if key not in seen:
                    seen.add(key)
                    yield replace(
                        explain_hint(game, hint),
                        verified_eliminations=tuple(sorted(verified)),
                        prerequisites=tuple(prerequisites),
                    )
            break


def next_hint(game: Game) -> Hint | None:
    """Return the simplest supported deduction, or an explicit lack of coverage."""
    return next(iter_hints(game), None)


@dataclass(frozen=True)
class HintStep:
    """One teaching stage with temporary board evidence and proposed changes."""

    title: str
    text: str
    focus: tuple[int, ...]
    candidates: tuple[tuple[int, int], ...] = ()
    placements: tuple[tuple[int, int], ...] = ()
    eliminations: tuple[tuple[int, int], ...] = ()
    links: tuple[HintLink, ...] = ()


def hint_steps(game: Game, hint: Hint) -> tuple[HintStep, ...]:
    """Build an inspect, explain, and apply sequence without editing player notes."""
    if hint.technique == "Candidate Review":
        if hint.eliminations:
            return (
                HintStep("1 of 2 · Check this pencil mark", hint.nudge, hint.focus),
                HintStep(
                    "2 of 2 · Remove invalid candidate",
                    hint.explanation,
                    hint.focus,
                    eliminations=hint.eliminations,
                ),
            )
        return (
            HintStep("1 of 2 · Review candidate marks", hint.nudge, ()),
            HintStep(
                "2 of 2 · Missing candidates",
                hint.explanation,
                hint.focus,
                placements=hint.placements,
            ),
        )
    options: list[set[int]] = game.logical_candidates()
    for index, digit in hint.verified_eliminations:
        options[index].discard(digit)
    relevant: set[int] = (
        {digit for _, digit in hint.placements + hint.eliminations}
        if hint.technique
        in (
            "Hidden Single",
            "Locked Candidates",
            "X-Wing",
            "Swordfish",
            "Jellyfish",
            "Color Trap",
            "Color Wrap",
            "Skyscraper",
            "Two-String Kite",
            "Turbot Chain",
        )
        else set(DIGITS)
    )
    evidence: tuple[tuple[int, int], ...] = (
        tuple(
            sorted(
                {
                    (cell, node.digit)
                    for link in hint.links
                    for node in (link.start, link.end)
                    for cell in node.cells
                }
            )
        )
        if hint.links
        else tuple(
            (index, digit)
            for index in hint.focus
            for digit in sorted(options[index] & game.notes[index] & relevant)
        )
    )
    changes: str = "\n".join(
        f"Place {digit} at {cell_name(index)}." for index, digit in hint.placements
    ) or "\n".join(f"Remove {digit} from {cell_name(index)}." for index, digit in hint.eliminations)
    reason: str = hint.explanation.split("\n\nRemove ")[0]
    legend: str = (
        "Solid: strong (at least one true).\nDotted: weak (cannot both be true)."
        if hint.links
        else "Outlined pencil marks show the evidence on your board."
    )
    if any(len(node.cells) > 1 for link in hint.links for node in (link.start, link.end)):
        legend += "\nA boxed group is true when at least one member is true."
    return (
        HintStep("1 of 3 · Look here", hint.nudge, hint.focus),
        HintStep(
            f"2 of 3 · {hint.technique}",
            legend + "\n\n" + reason,
            hint.focus,
            evidence,
            links=hint.links,
        ),
        HintStep(
            "3 of 3 · Make the deduction",
            changes
            + "\n\n"
            + (
                "Green circles show the answers."
                if hint.placements
                else "Red circled Xs show removals."
            )
            + " Apply makes one undoable change.",
            hint.focus,
            evidence,
            hint.placements,
            hint.eliminations,
            hint.links,
        ),
    )
