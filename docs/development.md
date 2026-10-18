# Development and building

[Back to the README](../README.md)

- [Requirements](#requirements)
- [Setup and source launch](#setup-and-source-launch)
- [Checks](#checks)
- [Theme implementation](#theme-implementation)
- [Building and installing](#building-and-installing)
- [Local data and recovery](#local-data-and-recovery)

## Requirements

The current app and bundle target **macOS 27 or newer on Apple Silicon**. Building requires
Xcode or Command Line Tools with **macOS SDK 27 or newer**, plus Git to clone the repository.
The standalone app includes its Python runtime; Python is needed only for development.

The distribution is `pfountz-sudoku`; the import package and command are `sudoku`. Python 3.13 or
newer is required, and the current source was verified with Python 3.14.6. Application logic is
Python, with Cocoa accessed through PyObjC. The game engine and regular storage can be tested
without the GUI; image recognition uses native Apple Vision and Quartz alongside OpenCV and NumPy.

### Packaging Python

The app builder requires **CPython 3.14.6**, exactly, plus the pinned dependencies in
`requirements-dev.txt`. Other supported Python versions can run the source, but packaging stops
when the interpreter or dependencies differ from the reviewed license inventory.
Homebrew's `python@3.14` can move to a newer patch version.

For a fresh packaging checkout, install the macOS installer from the official
[Python 3.14.6 release](https://www.python.org/downloads/release/python-3146/), then use its explicit
interpreter when creating the environment:

```sh
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 --version
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m sudoku.license_checks
```

Check that the first command reports `Python 3.14.6`; a later installer can replace that framework.
Use a fresh virtual environment rather than changing the interpreter inside an existing one.
The license check is the final check of the actual installed packages and native libraries.
If it fails, review the environment and [notice maintenance](licensing.md#dependency-and-notice-maintenance)
before packaging. Do not update the inventory simply to bypass a failure.

## Setup and source launch

Clone the repository if you have not already done so:

```sh
git clone https://github.com/gpfountz/Sudoku.git
cd Sudoku
```

From the project directory, using Python 3.13 or newer (the pinned setup was verified with 3.14):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .
.venv/bin/python launch.py
```

The prepared catalog is included in the checkout. To regenerate it, follow
[catalog maintenance and recovery](../SQLITE_MIGRATION.md). Close the installed app before running
from source. Source launches use normal user data unless `SUDOKU_DATA_DIR` is set.

For separate test progress, preferences, and window placement:

```sh
SUDOKU_DATA_DIR=/private/tmp/sudoku-testing \
SUDOKU_WINDOW_AUTOSAVE_NAME=SudokuTestingWindow \
SUDOKU_WINDOW_TITLE="Sudoku — Testing" \
.venv/bin/python launch.py
```

Reuse the same command to test restoration. `SUDOKU_CATALOG_DIR` can select a separate prepared
catalog. Setting only the data directory does not isolate native window placement.

## Checks

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy sudoku tests scripts setup.py launch.py
.venv/bin/python -m sudoku.license_checks
```

Native AppKit and Vision checks require a macOS desktop session:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q
```

See [Validation](../VALIDATION.md) for source-check results and historical bundle verification.

## Theme implementation

[`sudoku/theme.py`](../sudoku/theme.py) defines runtime themes, with Light/Dark palette specifications
in [`sudoku/theme_palettes.py`](../sudoku/theme_palettes.py). `Palette.incorrect_answer` supplies error
text, translucent error-cell fills, and hint-removal markings through `theme.hints.error_text`,
`error_fill`, and `removal_stroke`. Named palettes use red error cues: standard Light/Dark values
are `FF0000`/`FF4545`; High Contrast uses `BF0000`/`FF6262`.
`ACCENT_PALETTES` supplies Light/Dark accent pairs for variations of Default; these retain
Default's native error and hint colors.

`AppController.apply_theme()` changes the theme without changing appearance or game progress.
Preferences persist theme names, while saved annotations retain palette numbers. Older settings
default to Default, and an unfamiliar saved theme name falls back to Default without changing
puzzle progress. The board's `Background` object draws the themed surface.

## Building and installing

Use the exact [packaging Python](#packaging-python) and current `requirements-dev.txt` before building.
The build requires Xcode or Command Line Tools with macOS SDK 27 or newer. From the project directory:

```sh
.venv/bin/python -m sudoku.license_checks
./scripts/build_and_deploy.sh
```

Local packaging verifies the included license notices against the reviewed dependency versions.
See the [licensing guide](licensing.md#publishing-a-standalone-app) before publishing any binary;
the current OpenCV wheel has an unresolved native-library provenance issue. A successful local
build or installation does not clear that release requirement.

[`scripts/build_and_deploy.sh`](../scripts/build_and_deploy.sh) runs this checkout's build script,
extracts and verifies the ZIP, asks a running Sudoku to quit, and installs the verified app at
`~/Applications/Sudoku.app`. It restores the previous app if replacement or installed signature
verification fails. Temporary extraction and installation files are cleaned up, and your saved
games and preferences remain in Application Support. Launch the installed app normally afterward.

Build output and `Sudoku.zip` remain in a new private `/private/tmp/sudoku-release.XXXXXX/` directory,
outside cloud sync. The helper prints its exact archive path on success; keep that path for transfers.
`SUDOKU_RELEASE_DIR` and `SUDOKU_APPLICATIONS_DIR` can override the output and installation folders.
Both destinations must be owned by your account and must not be writable by another account.
Their ancestors must be owned by your account or root and must not permit shared writes, except
for root-owned sticky temporary directories. macOS ACL write grants, including inheritable grants,
are rejected; ordinary deny-delete and read-only ACL entries are preserved. User-created symlink
paths and newline characters are rejected; macOS system
aliases such as `/tmp` and `/var` are resolved to their canonical locations. A rejected destination
stops deployment before the build or installed app changes.
Synology and other file providers can add signing-incompatible Finder metadata to unpacked bundles;
use the ZIP for transfer and extract it outside cloud sync.

To build without installing:

```sh
SUDOKU_BUILD_DIR=$(mktemp -d /private/tmp/sudoku-release.XXXXXX)
.venv/bin/python scripts/build_app.py --output-dir "$SUDOKU_BUILD_DIR"
```

The builder stages a fresh bundle and replaces prior output only after verification succeeds;
omitting `--output-dir` uses the project's `dist/` directory.

The py2app configuration includes Apple Vision and Quartz explicitly and copies OpenCV and NumPy
as complete filesystem packages, preserving OpenCV's dynamically loaded extension and configuration
files. The build packages the active catalog generation and removes duplicate catalog resources.
`setup.py` uses dependencies already installed from the project metadata.

Use `scripts/build_app.py` for release builds. It recompiles py2app's launcher for Apple Silicon
with the selected SDK, checks the macOS 27 deployment target, signs the finished bundle, and verifies
its signature. Direct `setup.py py2app` builds omit this launcher replacement and can use legacy
AppKit appearance. `scripts/create_icon.py` renders the code-defined icon with Cocoa.

For catalog conversion, data backups, resource checks, and packaged save/resume testing, see
[catalog maintenance and recovery](../SQLITE_MIGRATION.md). Source validation alone does not verify
a packaged release; the deployment helper checks signatures but does not launch or smoke-test the app.

## Local data and recovery

User data is stored under `~/Library/Application Support/Sudoku/`:

| Location | Contents |
| --- | --- |
| `players/<difficulty>.sqlite` | Regular puzzle progress and selection cycles |
| `imported.sqlite3` | Immutable imported clues, solutions, difficulty, and individual attempt states |
| `regular-index.json` | Active regular or imported attempt and the displayed daily-game pointer |
| `catalog-daily-games/<date>.json` | Each assigned daily puzzle's progress |
| `catalog-daily-index.json` | Daily-game selection state |
| `history.sqlite3` | Ended attempts, including imported games |
| `preferences.json` | Appearance, themes, gameplay, and window-mode preferences |

Saved games retain answers, candidates, colors, undo/redo (up to 200 edits), elapsed time, and
attempt counters. Regular storage also retains earlier games and selection cycles; selecting an
arbitrary older unfinished regular game is outside the current UI's scope. Native window placement
is stored separately in macOS defaults.

On first launch with legacy saves, the app validates `game.json` or its valid backup, resolves played
IDs against the catalog, and imports regular progress into SQLite. Historical played IDs retain
unknown completion status without invented timestamps. Original JSON files remain as migration
backups, and interrupted migrations can be retried. Missing IDs, damaged state, or unsupported
schemas stop startup with an error instead of silently replacing progress.

Daily progress and preferences use JSON with last-good backups. Existing records from the former
`statistics.sqlite3` database move automatically to `history.sqlite3`. SQLite transactions roll
back failed writes. For independent recovery, back up the entire Application Support directory
with the app closed.

See [catalog maintenance and recovery](../SQLITE_MIGRATION.md) for catalog preparation, conversion,
verification, and installation commands.
