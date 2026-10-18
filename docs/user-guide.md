# User guide

[Back to the README](../README.md)

Detailed instructions for playing Sudoku, importing puzzles, and making the app your own.

- [Launch](#launch)
- [Playing](#playing)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Import puzzles](#import-puzzles)
- [Daily games](#daily-games)
- [Game history](#game-history)
- [Statistics](#statistics)
- [Settings and appearance](#settings-and-appearance)
- [Hints](#hints)

## Launch

Double-click **Sudoku.app** in your local Applications folder. The standalone bundle contains
its Python runtime and puzzle catalog, so a separate Python installation is unnecessary.
For source launches and packaging, see the [development guide](development.md).

## Playing

### Entry and selection

- **Cell First:** select a cell with the pointer or arrow keys, then enter a digit using the keyboard
  or number palette.
- **Number First:** choose a digit, then click a cell or select it with the arrow keys and press
  **Space** or **Return**.
- **Answers / Candidates:** choose independently from the entry order. **N** switches between them.
- Matching-digit highlighting follows the active digit in both entry orders and modes.
  **Shift + 1–9**, **Shift-click**, or **right-click** on a keypad digit selects that digit without
  changing answers or pencil marks.
- Right-click a puzzle cell to choose an answer, toggle a candidate, or paint a color. Answer and
  Candidate highlight the active digit; checkmarks show what is already in the cell. Color opens
  a 3×3 palette with the active color outlined and a Clear tile. Choosing the cell's current color
  clears it. The current entry mode stays selected, and each palette remembers its digit or color.

### Pencil marks and automatic entry

In Candidates mode, the selected cell has a lighter 3×3 guide grid inside its outline, and the
pointer becomes a pencil. Candidate positions are fixed: `1 2 3` on top, `4 5 6` in the middle,
and `7 8 9` on the bottom.

- A **Cell First** click selects the cell; enter notes with a number key or the keypad.
  A **Number First** click toggles the active candidate.
- **Drag** or **Shift + arrow keys** paints the active candidate in visited empty cells. Small pointer
  movements during a click are ignored. Once a drag starts, it paints the starting cell even when
  the entire stroke stays within that cell. Diagonal drags follow cell interiors; grazing a corner
  does not add that cell to the stroke.
- A stroke adds when its first cell is unmarked and removes when that cell already has the
  candidate. Repeating a stroke erases it; hold **Option** to force removal. Filled cells are
  skipped, and a complete gesture is one undo action.
- By default, dragging or pressing **Shift + arrow keys** also paints candidates while **Answers**
  is selected, without changing the active mode. This can be disabled in Settings.
- **Shift + Space** or **Shift + Return/Enter** toggles the active candidate without moving
  the selection. In Answers mode this follows the same Settings option as dragging; it works
  with either entry order. Hold **Option** as well to force removal.

Candidate entry is manual. By default, an answer removes matching notes from its peers; this can
be disabled in Settings. **Fill Candidates** replaces notes with all possibilities legal under the
current answers. It is undoable and does not continuously refill.

**Auto Complete** repeatedly fills cells with one legal candidate and digits with one legal position
in a row, column, or box. It also fills a cell with a single pencil mark when that mark matches the
saved solution; incorrect lone marks are skipped. New singles created by those answers or note
cleanup are filled in the same cascade, using one undo action.

### Cell colors

Press **C** to enter Color mode and press it again to return to the previous entry mode. Keys
**1–8** choose colors; **9** chooses Clear. Cell First applies a color immediately; Number First
chooses a color for the next click or Space/Return action. Drag or **Shift + arrow keys** paints
across crossed cells, including givens and filled cells. Starting on a cell with the chosen color
removes that color across the stroke. Choose Clear twice in a row to remove all cell colors.
Color changes can be undone.

### Pause, restart, and restoration

The timer stops while paused, minimized, or outside the app. **Undo**, **Erase**,
**Fill Candidates**, **Auto Complete**, and **Get Hint** are disabled while paused or complete.
The **Pause** button changes to **Resume** while paused; click it or press **Command-P** to resume.
**Restart…** resets the current puzzle after confirmation.

Closing the app saves progress. Relaunching restores answers, candidates, colors, timer, tools,
and undo/redo history. Native macOS Full Screen is also remembered: closing the window or quitting
in Full Screen restores that mode; leaving Full Screen before closing restores a normal window.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Arrow keys | Move, without wrapping at edges |
| 1–9 | Enter or choose a digit according to the entry order; choose a color in Color mode |
| Shift + 1–9 | Choose the active digit without editing answers or candidates |
| Space or Return | Place the active digit or candidate in Number First mode, or toggle a color |
| Shift + Space or Shift + Return | Toggle the active candidate without moving; in Answers mode, requires the candidate painting setting |
| N | Toggle candidate mode |
| C | Enter or leave Color mode |
| Delete or 0 | Clear the selected editable cell or color |
| Command-Z / Shift-Command-Z | Undo / redo |
| Command-A | Auto Complete |
| Command-F | Fill Candidates |
| Command-J | Request or expand a hint |
| Command-N | New game and difficulty choice |
| Command-D | Open or resume today’s daily game |
| Command-I | Import a puzzle from the clipboard or an image file |
| Command-P | Pause / resume |
| Command-comma | Settings |
| Escape | Dismiss hint highlights |

## Import puzzles

Click **Import Game**, choose **Game → Import Puzzle…**, or press **Command-I**.

- **Read Clipboard** reads the clipboard when clicked. Images take precedence over text grids.
  Text grids use 81 characters or nine rows, with digits `1–9` for clues and `0` or `.` for blanks.
- **Choose Image File…** opens the native macOS file picker for PNG, JPEG, HEIC/HEIF, or TIFF.

The app locates a 9×9 board within a larger image and straightens its perspective. If several
boards are detected, choose one. To correct the detected boundary, drag the four orange corner
handles and click **Read This Board**. Use **Rotate Board** for sideways or upside-down digits.

Before playing:

1. Compare the editable clue grid with the source image. Select a cell to enlarge its image area,
   then use the digit buttons or keyboard to correct or confirm it. Delete or **Clear** confirms
   a blank. Orange outlined cells need confirmation; red cells contain rule conflicts.
2. Keep the original clues and remove any entered answers mistaken for clues. Recognition ignores
   small pencil marks, but every cell remains available for correction.
3. Use the difficulty buttons to choose Easy, Medium, Hard, Expert, Master, or Extreme. Medium is
   selected by default; an already imported puzzle selects its saved difficulty, which you can
   change. **Play** becomes available after flagged cells are reviewed and the clues have exactly
   one solution.

The review checks the exact clue layout against all built-in puzzles in the background. A match
shows the built-in ID, difficulty, and whether you have already played it (including unfinished
games). Its difficulty is fixed to the catalog level. **Play** starts a fresh attempt using that
built-in identity and rating, so History and Statistics treat it as a built-in game. Existing
attempts keep their progress. Different clue layouts remain separate puzzles, even when they
share a solution.

**Play** saves the puzzle and starts a fresh game immediately. Unmatched imports receive permanent
IDs such as `IMP-000001`. Reimporting identical normalized clues reuses the saved ID and starts
another attempt. Changing the difficulty updates its saved level when you press **Play**.
Imports have a selected difficulty without a numeric catalog rating. Source images are discarded
when the review closes.

Starting the imported game marks the currently displayed unfinished regular, daily, or imported
attempt **Abandoned**. A completed attempt remains Completed. Cancelling, recognition errors,
invalid clues, or failed saves leave the current attempt and its History outcome unchanged.
Imported progress autosaves and restores after quitting; ended attempts can be replayed from History.

Recognition uses Apple Vision and OpenCV locally, without a cloud service or API key. Clear printed
puzzles and screenshots are supported when the entire board is visible. Obscured boards and severe
page curvature are outside scope. Always compare the clues: a unique solution does not prove that
the extraction matches the image.

## Daily games

Enable **Daily Game** in Settings and choose an inclusive minimum and maximum difficulty from the
six levels. Press **Daily Game** or **Command-D** to start today's puzzle. Difficulty is selected
at random, weighted by the catalog size of each included level, so every puzzle in the selected
range has an equal chance of supplying the day's game.

One puzzle is assigned per local calendar day. The button reopens that puzzle while it is unfinished
and becomes unavailable after completion. A new day makes a new game available. Daily progress is
saved independently, including answers, candidates, timer, and undo history.

Use **Game → Return to Regular Game** to switch back. Starting a daily game preserves regular
progress. An unfinished imported attempt becomes Abandoned; returning to that imported puzzle
starts a fresh attempt on its saved ID. Reopening an abandoned daily puzzle also starts a fresh
attempt on the same clues.

## Game history

**Game → History…** shows ended attempts, newest first, with each puzzle's ID, difficulty, status,
and ending date and time. Every ended attempt has its own row. **Replay** starts a fresh attempt
using the saved ID, original clues, and difficulty, including for imported puzzles. The list reads
small pages from SQLite as you scroll.

- **Completed:** the puzzle was solved. The completion message shows difficulty, elapsed time,
  hint stages viewed, revealed cells, and incorrect answers.
- **Restarted:** an unfinished puzzle was restarted, ending its old attempt.
- **Abandoned:** an unfinished regular or imported attempt was replaced by New Game, or an
  unfinished imported attempt was replaced by Daily Game. Import and Replay end the currently
  displayed unfinished attempt, including a daily game.

Switching between regular and daily games normally keeps both resumable. Quitting does not end
an attempt, and History does not reconstruct ended attempts from older legacy saves.

A hint stage counts once for a given deduction and board state. Viewing it again is free; changing
the board makes it a new hint. Reveals count once per cell, and incorrect answers count each
distinct cell and wrong digit once, including after Undo. These counters survive relaunches.

## Statistics

**Game → Statistics…** shows Easy through Extreme and a **Total** row, with games played,
average time, average hints, reveals, incorrect answers, restarts, and abandons, and games remaining.
**Include imported games** is unchecked by default. Toggle it to include or exclude imported
attempts from every history measurement. **Refresh** updates the table; reopening Statistics also
refreshes it.

Games played counts each ended attempt in History, including Completed, Restarted, and Abandoned.
Unfinished attempts are excluded. Every average divides by the number of included ended attempts;
average restarts and abandons are fractions of attempts ending with those outcomes (for example,
0.25 means one in four). Total averages use all included attempts rather than averaging the level
averages. Unplayed levels show a dash for averages. Average times are rounded to the nearest second.

Games remaining is the number of unused puzzles in each difficulty's current shared regular/daily
rotation, including levels with no recorded outcomes. Imports and replays do not consume rotation
slots, so the imported-games filter does not affect availability. An exhausted rotation shows zero
until the next new puzzle begins another cycle. Older attempts absent from History are not rebuilt.

## Settings and appearance

Open **Sudoku → Settings…** or press **Command-comma**. Settings includes **System**, **Light**,
and **Dark** appearance, themes, matching-digit and row/column/box highlighting, candidate dragging
in answer mode, note cleanup, timer visibility, and daily-game difficulty limits. System appearance
is the default.

### Themes and board cues

Choose **Default**, **Warm Paper**, **Sage Linen**, **Coastal Mist**, **Lavender Slate**,
**Tangerine Cream**, **Rose Clay**, **Peony Pink**, **High Contrast**, **Autumn Harvest**, or
**Winter Frost**. Default uses adaptive macOS colors. **Default Teal**, **Default Forest**, **Default Plum**, **Default Bronze**,
**Default Olive**, **Default Espresso**, **Default Graphite**, and **Default Orchid** keep Default's native backgrounds, grid,
hint markings, and annotation colors while replacing its accent. Their Light/Dark accents color
entered answers, selected controls, focus outlines, and matching-digit highlights. The other
themes color the board, keypad, controls, menus, and hint markings. Every theme follows the
separate appearance choice.

High Contrast uses opaque action controls, stronger grids, outlined matching digits, and underlined
entered answers. These provide cues beyond color. The selected cell has a focus outline that
preserves its other background highlights. When the window grows, the board and entry controls
remain centered together. Main game actions and the compact menu use macOS 27 AppKit glass buttons.

Givens and entered answers use semibold digits; pencil marks use bold digits in inset 3×3 positions.
Color distinguishes editable answers from givens, and candidate highlights and hint markings follow
the corresponding pencil-mark positions.

**Dim digits used in nine filled cells** is enabled by default. It counts givens and entered answers,
without checking them against the solution, and excludes pencil marks. Dimmed digits remain
selectable and brighten if an entry is erased or undone.

### Error checking

- **Off:** no answer errors are highlighted.
- **Rule Conflicts** (default): highlight duplicates in a row, column, or box.
- **Against Solution:** highlight entered answers that differ from the unique solution and protect
  correctly answered cells from replacement or erasure. Undo and cell colors remain available.

Givens cannot be edited. Incorrect entries are allowed and remain editable in every error mode.
Visible errors use the theme's error color and a circled X over the answer. Pencil marks are allowed
as entered and can be reviewed by the hint system.

## Hints

### Candidate review

**Get Hint** first checks for a pencil mark conflicting with a filled digit or an earlier applied
elimination. A two-step Candidate Review identifies the mark and explains why it must be erased;
**Apply** removes it as one undoable change. For example, a marked 1 at R5C7 is reviewed before an
XY-Chain when R2C7 already contains 1.

If no conflict exists, Candidate Review checks marked empty cells for missing correct candidates
using the saved solution. It first flags the problem, then identifies the missing candidates;
**Apply** fills those cells with their answers as one undoable change. Cells without pencil marks
are skipped. Logical hints resume after the note issue is resolved.

### Logical explanations

Logical hints have three steps: where to look, why the pattern works, and what to change. Use
**Next Step** and **Back** to move through them. Orange circles identify candidate evidence, green
circles show proposed answers, and red circled Xs show removals. **Apply** becomes available at the
final step and performs one undoable edit. **Show Another Hint** offers a distinct deduction,
starting with simpler techniques and cycling when all available hints have been shown.

Hints derive from current answers and verified deductions rather than potentially incomplete
player notes. Overlays leave notes unchanged; applying an elimination removes only candidates
currently present. The search carries independently proven, already-absent removals forward to a
fixed point within each technique tier, checking newly exposed simpler hints before advancing.
These internal deductions do not alter your notes, saved eliminations, or undo history.

Chain and coloring diagrams use solid lines for strong links (at least one endpoint is true) and
dotted lines for weak links (both endpoints cannot be true). Lines appear at the explanation step
and remain through the final deduction. They connect exact candidate positions, including temporary
evidence marks for candidates absent from your notes. Boxed groups represent one OR node: at least
one member is true. A link to a group does not assert a separate strong link to each member.
Back, Escape, and board edits update or clear the diagram together with the hint.

### Supported techniques and limits

- Naked and hidden singles; locked candidates (pointing and claiming).
- Naked and hidden pairs, triples, and quads.
- X-Wing, Swordfish, and Jellyfish, including finned and sashimi variants.
- Non-overlapping Franken and Mutant fish of sizes two through four, including finned variants
  whose fins lie in one box; searches allow 30,000 cover-search visits per size.
- XY-Wing, XYZ-Wing, W-Wing, Skyscraper, Two-String Kite, and Turbot Chain.
- Simple coloring: Color Trap and Color Wrap.
- XY-Chains through 24 cells, using shortest-path searches with a 60,000-state limit.
- Multi-digit alternating-inference chains (AICs), nice-loop consequences, and grouped AICs using
  line/box groups of up to three cells. Chains trace alternating strong/weak links to a contradiction
  with a maximum of 32 links. Diagrams show the proof and explanations describe the contradiction.
- Unique Rectangle types 1–4, Avoidable Rectangle type 1, and BUG+1. These require an independent
  check that the original clues have exactly one solution; explanations identify that assumption.

Complex fish with fins across boxes, endo-fin and cannibalistic fish, fish larger than Jellyfish,
additional rectangle variants, ALS techniques, multi-coloring/3D Medusa, forcing nets, and nested
contradictions remain unsupported. An ordinary AIC does not branch into a forcing net, and search
limits can leave deductions undiscovered. Wrong answers trigger optional mistake assistance before
logical hints.

When the supported techniques cannot advance the board, the app explains the limitation and offers
**Reveal Selected Cell**. This supplies an answer without a logical explanation; it does not mean
the puzzle requires guessing.

Technique references: HoDoKu's [fish principles](https://hodoku.sourceforge.net/en/tech_fishg.php),
[chains and loops](https://hodoku.sourceforge.net/en/tech_chains.php),
[uniqueness](https://hodoku.sourceforge.net/en/tech_ur.php),
[wings](https://hodoku.sourceforge.net/en/tech_wings.php), and
[coloring](https://hodoku.sourceforge.net/en/tech_col.php).

For save locations, backups, and recovery, see the [development guide](development.md#local-data-and-recovery).
