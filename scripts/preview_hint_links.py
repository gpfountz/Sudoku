# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Preview the experimental hint diagram on the supplied puzzle without saving progress."""

import argparse
import subprocess
from pathlib import Path
from typing import Any

from sudoku.engine import solve
from sudoku.hints import Hint, HintStep, hint_steps, iter_hints
from sudoku.model import Game, Preferences, Puzzle

PREVIEW_ROWS: tuple[str, ...] = (
    "000104020",
    "200008700",
    "045729603",
    "350000807",
    "000000000",
    "701000032",
    "008003250",
    "523400006",
    "090502300",
)
PREVIEW_NOTES: tuple[str, ...] = (
    "689 37 679 - 356 - 59 - 589",
    "- 13 69 36 356 - - 149 1459",
    "18 - - - - - - 18 -",
    "- - 249 29 149 16 - 169 -",
    "49 68 24 238 347 1567 1459 169 159",
    "- 68 - 89 49 56 459 - -",
    "146 17 - 69 1679 - - - 149",
    "- - - - 1789 17 19 178 -",
    "146 - 467 - 1678 - - 1478 148",
)


def preview_game() -> Game:
    """Recreate the screenshot values and notes without treating notes as proof."""
    values: tuple[int, ...] = tuple(int(digit) for row in PREVIEW_ROWS for digit in row)
    solutions: list[tuple[int, ...]] = solve(values)
    if len(solutions) != 1:
        raise ValueError("The preview puzzle must have one solution")
    givens: tuple[int, ...] = tuple(
        0 if index in (22, 23, 26, 63, 64, 78) else value for index, value in enumerate(values)
    )
    game: Game = Game(Puzzle("hint-link-preview", givens, solutions[0], 7.0, "Master"))
    game.values = list(values)
    game.notes = [
        {int(digit) for digit in cell} if cell != "-" else set()
        for row in PREVIEW_NOTES
        for cell in row.split()
    ]
    game.selected = 39
    game.active_digit = 2
    return game


def preview_hint(game: Game) -> Hint:
    """Select the same r4c3 candidate-2 contradiction shown in the screenshot."""
    return next(
        hint
        for hint in iter_hints(game)
        if hint.technique == "AIC / Nice Loop" and (29, 2) in hint.eliminations
    )


def render_preview(output: Path, appearance: str = "Light", stage: int = 2) -> None:
    """Capture native controls in an isolated window, including translucent surfaces."""
    import AppKit as AK
    from Foundation import NSDate, NSRunLoop

    from sudoku.app import AppController
    from sudoku.theme import WARM_PAPER_THEME

    class PreviewWindow(AK.NSWindow):
        """Keep preview geometry independent of the player's saved window."""

        def setFrameUsingName_(self, name: str) -> bool:
            """Ignore saved window placement."""
            return False

        def setFrameAutosaveName_(self, name: str) -> bool:
            """Disable window geometry persistence."""
            return False

    application: Any = AK.NSApplication.sharedApplication()
    original_window: Any = AK.NSWindow
    AK.NSWindow = PreviewWindow
    controller: Any = AppController.alloc().init()
    controller.game = preview_game()
    controller.preferences = Preferences(
        theme="Warm Paper",
        appearance=appearance,
        input_order="Number First",
        highlight_peers=False,
    )
    controller.controls = {}
    controller.settings_window = None
    hint: Hint = preview_hint(controller.game)
    step: HintStep = hint_steps(controller.game, hint)[stage - 1]
    controller.hint_focus = set(step.focus)
    controller.hint_candidates = set(step.candidates)
    controller.hint_removals = set(step.eliminations)
    controller.hint_placements = set(step.placements)
    controller.hint_links = step.links
    controller.build_window()
    try:
        controller.apply_theme(WARM_PAPER_THEME)
        controller.apply_appearance()
        controller.window.setContentSize_((1180, 870))
        controller.window.setAnimationBehavior_(AK.NSWindowAnimationBehaviorNone)
        content: Any = controller.window.contentView()
        content.layoutSubtreeIfNeeded()
        controller.controls["subtitle"].setStringValue_(
            "Experimental hint links · screenshot puzzle"
        )
        controller.controls["order"].setSelectedSegment_(1)
        controller.controls["mode"].setSelectedSegment_(0)
        controller.controls["palette_label"].setStringValue_("Active digit  2")
        controller.controls["footer"].setStringValue_("Drag or Shift + arrows paint candidates")
        controller.controls["hint"].setTitle_("Next Step")
        controller.controls["apply_hint"].setEnabled_(stage == 3)
        controller.controls["previous_hint"].setEnabled_(stage > 1)
        controller.controls["hint_text"].setString_(f"{step.title}\n\n{step.text}")
        controller.controls["hint_text"].scrollRangeToVisible_((0, 0))
        controller.controls["digit2"].setState_(AK.NSControlStateValueOn)
        content.layoutSubtreeIfNeeded()
        output.parent.mkdir(parents=True, exist_ok=True)
        controller.window.makeKeyAndOrderFront_(None)
        controller.window.makeFirstResponder_(controller.board)
        application.activateIgnoringOtherApps_(True)
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(1.5))
        subprocess.run(
            [
                "/usr/sbin/screencapture",
                "-x",
                "-o",
                "-l",
                str(controller.window.windowNumber()),
                str(output),
            ],
            check=True,
        )
    finally:
        controller.window.setDelegate_(None)
        controller.window.close()
        controller.board.controller = None
        AK.NSWindow = original_window
        application.setDelegate_(None)


def main() -> None:
    """Parse a destination and render a source preview without building the app."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/sudoku-hint-links.png"))
    parser.add_argument("--appearance", choices=("Light", "Dark"), default="Light")
    parser.add_argument("--stage", type=int, choices=(1, 2, 3), default=2)
    arguments: argparse.Namespace = parser.parse_args()
    render_preview(arguments.output, arguments.appearance, arguments.stage)
    print(arguments.output)


if __name__ == "__main__":
    main()
