# Older macOS testing: first step

Branch: `codex/feature-older-macos-support`.

This step adds native rounded-button fallbacks for older systems while retaining
glass on macOS 26 and newer. High Contrast keeps its opaque controls. Standalone
packaging still targets macOS 27 and Apple Silicon; run this experiment from
source. Sonoma and Intel Sequoia support remain unverified until tested there.

Local automated validation on October 21, 2026, using the M4 on macOS 27.0.1
and CPython 3.14.8: the complete desktop-enabled suite passed **1,021 tests**.
Ruff lint and formatting, Mypy, and the dependency-license checks also passed.
The control fallback was previewed in Light, Dark, and High Contrast. The
maintainer completed hands-on local validation on October 21, 2026; this step
is ready for source-based testing on the Intel Sequoia MacBook.

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
