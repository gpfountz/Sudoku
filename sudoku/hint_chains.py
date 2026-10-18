# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Alternating-inference proofs using single candidates and grouped candidates."""

from collections import deque
from collections.abc import Iterator

from sudoku.engine import DIGITS, PEERS, UNITS, cell_name
from sudoku.hint_types import Hint, HintLink, removal_hint
from sudoku.hint_types import HintNode as Node


def inference_graph(
    options: list[set[int]],
    grouped: bool,
) -> tuple[list[Node], list[list[int]]]:
    """Encode weak links as true-to-false and strong links as false-to-true edges."""
    nodes: set[Node] = {Node((cell,), digit) for cell in range(81) for digit in options[cell]}
    strong: set[tuple[Node, Node]] = set()
    for cell, digits in enumerate(options):
        if len(digits) == 2:
            first, second = sorted(digits)
            strong.add((Node((cell,), first), Node((cell,), second)))
    for unit in UNITS:
        for digit in sorted(DIGITS):
            places: tuple[int, ...] = tuple(cell for cell in unit if digit in options[cell])
            if len(places) == 2:
                strong.add((Node((places[0],), digit), Node((places[1],), digit)))
            if grouped and len(places) > 2:
                # Partition a unit at another unit's intersection (line/box group links).
                for crossing in UNITS:
                    part: tuple[int, ...] = tuple(cell for cell in places if cell in crossing)
                    rest: tuple[int, ...] = tuple(cell for cell in places if cell not in crossing)
                    if part and rest and len(part) <= 3 and len(rest) <= 3:
                        a, b = Node(part, digit), Node(rest, digit)
                        nodes.update((a, b))
                        strong.add((a, b))
    ordered: list[Node] = sorted(nodes)
    indices: dict[Node, int] = {node: index for index, node in enumerate(ordered)}
    edges: list[set[int]] = [set() for _ in range(2 * len(ordered))]
    for a, b in strong:
        first, second = indices[a] * 2, indices[b] * 2
        edges[first].add(second + 1)
        edges[second].add(first + 1)
    for first, a in enumerate(ordered):
        for second in range(first + 1, len(ordered)):
            b = ordered[second]
            exclusive: bool = (
                a.digit == b.digit and all(y in PEERS[x] for x in a.cells for y in b.cells)
            ) or (len(a.cells) == len(b.cells) == 1 and a.cells == b.cells and a.digit != b.digit)
            if exclusive:
                edges[first * 2 + 1].add(second * 2)
                edges[second * 2 + 1].add(first * 2)
    return ordered, [sorted(neighbors) for neighbors in edges]


def contradiction_path(edges: list[list[int]], start: int, max_links: int = 32) -> list[int]:
    """Find the shortest alternating path to the opposite literal, with a depth bound."""
    queue: deque[int] = deque([start])
    parents: dict[int, int] = {start: -1}
    depths: dict[int, int] = {start: 0}
    target: int = start ^ 1
    while queue:
        current: int = queue.popleft()
        if depths[current] >= max_links:
            continue
        for neighbor in edges[current]:
            if neighbor in parents:
                continue
            parents[neighbor] = current
            depths[neighbor] = depths[current] + 1
            if neighbor == target:
                path: list[int] = [target]
                while parents[path[-1]] != -1:
                    path.append(parents[path[-1]])
                return path[::-1]
            queue.append(neighbor)
    return []


def inference_chain_hints(options: list[set[int]], grouped: bool = False) -> Iterator[Hint]:
    """Find AIC and nice-loop consequences as explainable opposite-literal paths."""
    nodes, edges = inference_graph(options, grouped)
    deductions: list[tuple[list[int], int, bool]] = []
    for index, node in enumerate(nodes):
        if len(node.cells) != 1:
            continue
        for assumed in (True, False):
            path: list[int] = contradiction_path(edges, index * 2 + int(assumed))
            if path:
                # Grouped searches add only proofs that actually use a group.
                uses_group: bool = any(len(nodes[literal // 2].cells) > 1 for literal in path)
                if not grouped or uses_group:
                    deductions.append((path, index, assumed))
    for path, index, assumed in sorted(
        deductions, key=lambda item: (len(item[0]), item[1], item[2])
    ):
        node = nodes[index]
        technique: str = "Grouped AIC / Nice Loop" if grouped else "AIC / Nice Loop"
        links: tuple[HintLink, ...] = tuple(
            HintLink(nodes[previous // 2], nodes[literal // 2], previous % 2 == 0)
            for previous, literal in zip(path, path[1:], strict=False)
        )
        focus: tuple[int, ...] = tuple(
            sorted({cell for literal in path for cell in nodes[literal // 2].cells})
        )
        reason: str = (
            "Assume " + node.describe(assumed) + ".\n"
            "The loop contradicts this, so " + node.describe(not assumed) + "."
        )
        nudge: str = f"Follow alternating strong and weak links from {cell_name(node.cells[0])}."
        if assumed:
            yield removal_hint(
                technique, nudge, reason, focus, [(node.cells[0], node.digit)], links
            )
        else:
            yield Hint(
                technique,
                nudge,
                reason,
                focus,
                placements=((node.cells[0], node.digit),),
                links=links,
            )
