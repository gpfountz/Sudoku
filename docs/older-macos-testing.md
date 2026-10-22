# Older macOS testing: first step

Branch: `codex/feature-older-macos-support`.

This step adds native rounded-button fallbacks for older systems while retaining
glass on macOS 26 and newer. High Contrast keeps its opaque controls. Standalone
packaging still targets macOS 27 and Apple Silicon; run this experiment from
source. Sonoma remains unverified, and Intel Sequoia testing is in progress.

Local automated validation on October 21, 2026, using the M4 on macOS 27.0.1
and CPython 3.14.8: the complete desktop-enabled suite passed **1,021 tests**.
Ruff lint and formatting, Mypy, and the dependency-license checks also passed.
The control fallback was previewed in Light, Dark, and High Contrast. The
maintainer completed hands-on local validation on October 21, 2026; this step
is ready for source-based testing on the Intel Sequoia MacBook.

## Reported Sequoia progress

The Intel Haswell MacBook running macOS 15.8.1 through OpenCore Legacy Patcher
successfully installed the source package and displayed the board. Manual
visual and functional testing is still in progress.

The first targeted native run reported 48 passed and two failures. Both failures
were the same compact-menu assertion: its native frame measured 54 by 52 points
instead of 40 by 40. A local native regression model reproduces those dimensions
using alignment insets of 6 points vertically and 7 points horizontally. The
assertion now checks the 40-by-40 Auto Layout alignment rectangle, allowing native
decoration outside it. All 54 targeted control and compact-menu checks pass locally
with this correction. The Sequoia MacBook rerun at commit `93c562f` also passed:
**54 passed, 362 deselected in 25.75 seconds**, as reported by the maintainer.
The subsequent full desktop-enabled run at that commit reported **1,016 passed
and 9 failed in 962.59 seconds**. The failures were:

- Four OCR confidence assertions: the expected digits were recognized, but some
  required review rather than receiving the expected high confidence.
- Two image-import UI checks whose background jobs exceeded the test's 15-second
  wait. Their eventual result and duration have not yet been established.
- One synthetic mouse-selection check for the themed Appearance dropdown.
  The maintainer confirmed that selecting Dark manually with the mouse works.
- Two active-digit menu badge checks: a hardcoded 24-point custom row enlarged
  Sequoia's 22-point native row by two points.

The follow-up at `199578f` measures the native menu row before inserting the badge, retaining
the modern row size on macOS 27. A native regression model reproduces the shorter
row. The synthetic dropdown test now waits for the menu row to appear and posts
a hover followed by clicks using current event timestamps. The Sequoia rerun
reported **19 passed and 1 failed in 8.13 seconds**: the badge and other menu
checks pass, but synthetic mouse selection still fails. The reported menu row
was visible and had positive dimensions; manual mouse selection works.

The next test adjustment positions the actual pointer over the target row and
allows a tracking-loop iteration between hover and click, then restores the
pointer. Whether that resolves older AppKit tracking still needs a Sequoia rerun.

The Intel OCR traces use the same Python and package versions and Vision request
revision 3 as the M4. For the bottom 8, only the compact patches were recognized,
with confidence 0.50 and 1.00; the production rule correctly requires review
because both must reach 0.85. The three thin-digit cells were read correctly as
9, 4, and 5, each with confidence about 0.30 on all three attempts. They took
about 1.72–2.20 seconds per cell, and the 8 took 2.97 seconds. These results do
not establish whether OS version, hardware, or patched graphics caused the
differences.

Recognition settings and the 0.85 review threshold remain unchanged. The tests
retain the strict no-review fixture expectations on macOS 27 and newer. On older
systems they still require every digit and blank to match exactly, while allowing
low-confidence results to require review. The image-import tests now confirm each
flagged clue using its digit button, verify Play stays disabled until all flags
are cleared, and preserve every recognized value. Separate decision tests replay
the reported 0.30 and 0.50 confidence patterns. Only the two real image-import
integration cases receive a 180-second wait per OCR phase, accommodating the
measured Intel timings; other background-job waits remain 15 seconds. The full
import duration and remaining manual visual checks still need Intel validation.

These graphics diagnostics were also reported during launch:

```text
Could not initialize cikl2metal preamble file
Can't create the cikl2metal preamble string
```

The board appeared despite these messages. Their relationship to the patched
graphics stack and any effect on themes or image recognition remain unverified;
the messages are not suppressed by this compatibility work.

## Local preview on macOS 27

From this checkout, launch either preview:

```sh
.venv/bin/python -m scripts.run_compatibility_preview
.venv/bin/python -m scripts.run_compatibility_preview --rounded-controls
```

Quit one preview before starting the other. Each uses its own progress directory
under `.preview-data/older-macos/` and its own window geometry, independently of
the installed app's player data. The rounded preview changes only control-style
availability; it does not emulate an older OS's frameworks or drawing engine.

Use Settings to compare Light, Dark, and High Contrast. Check action buttons,
the Number First/Cell First and Answers/Candidates/Color choices, and the compact
game-actions menu that appears when the window is narrow.

## Intel MacBook running Sequoia

Connect using RustDesk and open Terminal on the MacBook. Use an Intel CPython
3.14 installation and a virtual environment created on that machine. If Python
is needed, the [official macOS installer](https://docs.python.org/3.14/using/mac.html)
is a candidate. Do not copy the M4's virtual environment or application bundle.
The source preview does not require the builder's SDK 27 launcher compilation.

For a new checkout:

```sh
git clone --branch codex/feature-older-macos-support https://github.com/gpfountz/Sudoku.git
cd Sudoku
```

For an existing, clean checkout, fetch and switch to the feature branch instead:

```sh
git fetch origin
git switch codex/feature-older-macos-support
git pull --ff-only
```

Create the environment if this checkout does not already have a suitable Intel
environment, then install the same reviewed dependencies:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.versioning install
```

The source preview runs directly from this checkout; an editable installation is
optional. If you want the installed `sudoku` command or package metadata, install
the reviewed requirements first, then run:

```sh
.venv/bin/python -m pip install --no-deps -e .
```

Using `--no-deps` retains the dependency versions just installed from
`requirements-dev.txt`. That requirements file also restores its reviewed pip
version if pip was upgraded separately.

Record the tested environment and source revision:

```sh
sw_vers
uname -m
.venv/bin/python --version
git rev-parse HEAD
```

`uname -m` should report `x86_64` on this MacBook. First run the normal tests,
then the desktop tests from the logged-in graphical session:

```sh
.venv/bin/python -m pytest -q
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q
```

The desktop suite exercises the actual OS-selected controls and forced rounded
controls, along with Vision OCR fixtures. Report failures with the environment
details and full failure output; a passing suite on this MacBook establishes
evidence for Sequoia, not Sonoma.

For the current follow-up, run the affected menu tests before repeating the full
suite, then capture a small OCR trace:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_native_layout.py -k 'active_digit_badge or cell_menu or themed_dropdown'
.venv/bin/python -m scripts.diagnose_ocr
.venv/bin/python -m scripts.diagnose_ocr --fixture thin-digits
```

After collecting those traces, validate OCR and review with:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_import_images.py tests/test_import_ui.py -k 'bottom_eight or thin_digits or uncertain_cell or recognition_rechecks or compact_recognition' --durations=6
```

The real image-import cases can take several minutes on the Intel MacBook. Keep
the pointer still while running the synthetic menu test; it briefly moves and
restores the pointer to exercise native tracking.

The diagnostic prints JSON containing the OS, architecture, package versions,
Vision request revision, recognized digits, confidence, and per-attempt timings.
It uses the production recognition path and the same fixture pixels as the
failing tests without changing recognition settings or review decisions. The
default checks one 8; the thin-digit option checks three cells flagged for review
on Sequoia. Neither command scans the whole board. On the M4, the 8 required
three attempts and about 0.28 seconds, while the three thin-digit cells each took
one attempt and about 0.04–0.14 seconds. These timings exclude process startup.

Launch the source preview using automatic style selection:

```sh
.venv/bin/python -m scripts.run_compatibility_preview
```

On Sequoia this should select rounded controls automatically. Check:

- Light, Dark, and High Contrast: readable titles, visible selection, keyboard
  focus, and usable action and compact-menu buttons.
- Number First/Cell First and Answers/Candidates/Color: one selected choice,
  correct actions, and no unintended board edits.
- Answer and candidate entry, Control-click/right-click, Shift-Space/Shift-Enter,
  undo/redo, hints, and pause/resume.
- Resizing and full screen; Settings, History, Statistics, and About windows.
- Image import from file and clipboard, including review and correction.
- Daily games and save/reopen. Preview progress should persist without changing
  the installed app's progress.

Keep this source-testing step separate from changing the bundle deployment
target, Python distribution, or architecture-specific license inventory. Those
are later steps after the native compatibility path is validated.
