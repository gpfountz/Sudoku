# Adaptive window layout

The native window uses Auto Layout and explicit `NSStackView` arrangements around the existing custom board. Input targets, model state, settings, and saved games are unchanged. Window geometry continues to use the `SudokuMainWindow` autosave name; restored frames are clamped to the current screen's visible bounds.

## Arrangements

Dimensions below refer to the play-area viewport, after the header and bottom actions have been laid out, in macOS points.

| Arrangement | Entry condition | Presentation |
| --- | --- | --- |
| Wide | At least 850 wide and 550 tall | Square board beside keypad and hints stacked vertically |
| Smaller landscape | At least 684 wide and 550 tall, with width at least 1.15 times height | Same arrangement with a smaller board; fits a typical half-screen window |
| Short/wide | At least 1000 wide when the stacked sidebar would need too much height | Board, keypad, and hints in three columns |
| Narrow/tall | Otherwise, with width at least 504 | Board above keypad and hints placed side by side |
| Narrow/compact | Remaining widths | Board, keypad, and hints stacked vertically |

Exit thresholds retain the current arrangement through a 24-point band (and a 1.10 aspect ratio for smaller landscape windows). The minimum width required by the components always takes precedence. Constraints resize existing views; mode changes do not replace the board or its controls. Button rows are rebuilt only when their grouping changes.

The board targets at least 288 × 288 points, but fitting entirely onscreen takes precedence when available space is unusually constrained. Cells are approximately 32 points at the minimum, with approximately 8-point candidate digits. Board text, candidate highlights, selection strokes, and hint annotations scale with cell size. The keypad remains a 3×3 grid. Its tile widths, heights, spacing, and digits shrink in proportion to the board, relative to a 588-point board with 44-point-high tiles. Entry-order controls and hint buttons retain their font sizes while their panels can narrow from 260 to 220 points. Below-board panels can widen to 360 points. In vertical arrangements, the board uses as much width as possible while fitting completely in the available height. At least 120 points below the board are reserved for supporting controls. Only the supporting controls scroll; the board remains fixed and fully visible. Hint text scrolls independently of its action buttons.

## Minimum size and tiling

The minimum **content** size is **400 × 720 points**, plus the native title bar. The header wraps its buttons, and the bottom editing actions remain visible. If the supporting panels cannot fit vertically, their separate viewport scrolls. At the narrowest size, scroll between the keypad and hints while the entire board stays onscreen. The increased minimum height provides room for a readable board and access to the controls.

Half-screen windows are supported when their available dimensions satisfy the minimum. Quarter-screen tiling is only possible on displays whose quarter tile is at least the minimum window size. A MacBook's usual logical screen height does not provide 720 content points in a quarter tile, so quarter-screen tiling is not supported at that display setting. macOS may refuse that tile or enforce the minimum size. Larger displays or higher logical resolutions can accommodate it.

## Validation

Run the normal suite and static checks:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy sudoku tests scripts setup.py launch.py
.venv/bin/python -m pytest -q
```

Native constraint and input checks require a macOS WindowServer session:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q
```

These tests create hidden windows, suppress window-default restoration and saving, and never load or write user progress. They check real panel containment and separation, the keypad grid, long hint content, Daily Game visibility, every cell's hit testing, diagonal candidate dragging, selection-only clicks, Shift-arrow entry, and a continuous resize sweep that preserves the board and game state. Native-window tests are opt-in so the normal suite remains usable in a restricted/headless environment.

Visual previews were checked at 1120×820, 700×1000, 1200×640, 720×740, and 520×720 content points, including light/dark appearance, candidates and real hint annotations, long hint text, scrolling to the compact controls, and paused/completed states. These previews used isolated temporary progress and suppressed window autosaving.

## Screenshots

These are native captures of isolated preview windows.

- [Wide](layout-screenshots/wide.png)
- [Narrow/tall](layout-screenshots/narrow.png)
- [Short/wide in dark mode](layout-screenshots/short-wide-dark.png)
- [Half-screen](layout-screenshots/half-screen.png)
- [Minimum size, board visible](layout-screenshots/minimum.png)
- [Minimum size, scrolled to controls](layout-screenshots/minimum-controls.png)

## Vertical action menu

Vertical arrangements keep entry order, answer/candidate mode, and the 3×3 digit keypad visible below the puzzle. The top-right hamburger menu contains the other game, editing, and hint actions. Entry controls and digits are not duplicated in that menu. Space is reserved for the full keypad while keeping the entire puzzle visible. Its actions use the existing handlers and reflect the same disabled and selected states. Daily Game stays absent when disabled in settings. Hint text remains visible below the fixed puzzle; wide arrangements restore their normal controls. Layout decisions use the normal toolbar dimensions to prevent hiding/showing buttons from repeatedly changing the arrangement.
