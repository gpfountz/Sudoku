# Source publication checks — 2026-10-18

Verified from a fresh local clone of the clean-history publication copy on Apple Silicon,
macOS 27.0.1, and CPython 3.14.6. The clone used a newly created virtual environment;
both installation commands in the README completed successfully:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .
```

- All 880 tests passed with `RUN_NATIVE_LAYOUT_TESTS=1`, including AppKit and Apple Vision.
- The default suite passed 476 tests and skipped the 404 opt-in native tests.
- Ruff lint and formatting, Mypy across 71 source files, dependency consistency, and the
  reviewed license/dependency inventory passed.
- A real source launch opened a visible window and loaded all 893,916 bundled puzzles.
  With isolated progress and a separate native window-autosave name, an answer edit and
  its undo history survived quitting and relaunching with the same puzzle and attempt ID.
  The paused state was restored, and the Resume button resumed play successfully.
- File imports reject images larger than 128 MiB before reading their contents. A bounded
  read also rejects files that grow past the limit. Regression checks cover oversized
  and unreadable files, exact-limit acceptance, and unchanged clipboard/file image bytes.
- Development pip was updated and pinned to 26.2.1. An OSV query of all 25 installed
  third-party PyPI package versions in the fresh environment found no known advisory matches
  on the verification date. This check does not assess native-library or operating-system advisories.
- All local documentation links and referenced headings resolved. The GPL text matched
  the SPDX GPL-3.0-only reference after whitespace normalization; the puzzle dedication
  matched its upstream license byte for byte. Recorded third-party notice and native-library
  hashes matched the fresh environment.

These checks cover source publication and optional local-build guidance. No standalone app
was built or installed during this verification. The OpenCV binary provenance limitation
remains documented in [licensing](docs/licensing.md#publishing-a-standalone-app).
GitHub CI against the final public commit remains pending the first authorized push.

# Puzzle import source validation — 2026-10-03

Verified on the user's Apple Silicon Mac running macOS 27 with Python 3.14.6,
using the isolated `codex/puzzle-import` worktree and its own dependencies and test data.

- 560 automated tests passed with `RUN_NATIVE_LAYOUT_TESTS=1`, including native AppKit and Vision.
- Ruff lint and formatting, Mypy across 60 source files, dependency checks, and `git diff --check`
  passed.
- Import coverage includes direct clipboard images and text grids, native file selection,
  editable clue review, uncertain digits, unique-solution validation, difficulty selection,
  stable imported IDs, duplicate handling, autosave, restoration, and History replay.
- Transition tests cover abandonment of regular, daily, and imported games, completed outcomes,
  failed-save compensation, restart, and fresh attempts when an abandoned daily puzzle reopens.
- Recognition checks include larger pages, small embedded boards, perspective correction,
  dark backgrounds, multiple boards, printed macOS fonts, and ignoring small pencil marks.
- A regression fixture preserves the bottom-row 8 that Vision initially misread. The supplied
  screenshot was also verified through both native review paths: identical clues, no flagged
  cells, exactly one solution, and Play enabled after explicit difficulty selection.
- The user reported no problems after manual testing of the updated import preview.

Build preparation includes pinned Apple Vision/Quartz wrappers, headless OpenCV, and NumPy.
The py2app configuration explicitly includes Vision and Quartz, and copies OpenCV and NumPy
as complete filesystem packages so OpenCV's dynamic loader retains its extension and config files.
No application bundle was built or deployed during this feature's validation. Signature checks
and a smoke test of the extracted bundle remain part of the next build and deployment.

The merged primary `main` checkout was then verified with its updated virtual environment:
all 560 native and automated tests passed again, along with lint, formatting, type checks,
dependency consistency, and merge whitespace checks. A separate build-input check confirmed
the bundle options, installed native import modules and OpenCV loader files, icon and license,
consistent project/bundle version, all 893,916 catalog puzzles, and macOS SDK 27.0 availability.

# Historical version 0.3.3 validation

Verified on the user's Apple Silicon Mac running macOS 27 with Python 3.14.6.

- 189 standard pytest tests passed; 44 GUI tests were skipped in the standard run.
- 67 native layout tests passed with AppKit access.
- Ruff lint and formatting, Mypy, and `git diff --check` passed.
- Daily tests covered catalog-count weighting, inclusive six-level range, one assigned game per date,
  reopening progress, completion lockout, separate regular progress, and damaged-save protection.
- The standalone app built with macOS SDK 27.0 and passed strict deep code-signature verification.
- The installed Sudoku.app reports version 0.3.3, build 23.

# Historical version 0.2.0 validation

Verified on the user's Apple Silicon Mac running macOS 27, with Python 3.14.6 and PyObjC 12.2.2.

## Automated checks

- 65 pytest tests passed.
- Ruff lint and formatting checks passed.
- Mypy passed for application, preparation/build scripts, and tests.
- Every one of the 3,000 included puzzles passed independent uniqueness validation during preparation.
- Real-puzzle hint sequences were exercised across all six difficulty levels. Every emitted placement
  and elimination preserved the known solution, with explicit termination when techniques ran out.
- Save tests cover undo/redo restoration, candidates, preferences, elapsed time, corruption,
  backup recovery, protected givens, and write failures.

## Native app checks

Performed against the actual Cocoa interface and standalone app, using isolated test saves:

- Native launch and accessibility labels for all 81 cells.
- Keyboard candidate entry and Shift-arrow painting, including skipping givens.
- Pointer dragging across multiple empty cells, with one-step undo.
- Cell-first and number-first entry controls.
- Visible rule-conflict feedback for an invalid answer.
- Progressive hint nudge, explanation, and application.
- Pause hides board content and disables entry.
- Dark appearance, then System appearance matching the Mac's current light appearance.
- Relaunch restores puzzle progress, notes, paused state, elapsed time, preferences, and undo/redo.

Off/Against Solution error policies, all supported logical techniques, note cleanup, and edge-clamped
movement also have model-level tests. An operating-system-wide appearance change was not forced;
System appearance uses native inherited Cocoa appearance and dynamic system colors.

## Delivery

- A standalone Apple Silicon `Sudoku.app` was installed and launched from `~/Applications`.
- `codesign --verify --deep --strict` passed on that installed copy after launch.
- The app created and updated its normal Application Support game and preference files.
- `dist/Sudoku.zip` contains the clean bundle for archiving or copying. The extracted project-folder
  copy may receive Finder metadata from Synology; the local installed copy avoids that interference.

This is an ad-hoc-signed local build, not a notarized public release. Extreme-level hints intentionally
offer an explicitly labeled reveal when the implemented logical techniques cannot advance the board.
