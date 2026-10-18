# Sudoku for macOS

A native Mac Sudoku app built with Python and Cocoa through PyObjC. Play at your own pace,
choose how you enter answers and pencil marks, and get step-by-step help when you need it.
Puzzles, daily games, and image recognition work locally, without a server or API key.

## Why I built it

I wanted a Sudoku app that works the way I like. Building my own also gave me a practical
way to learn Python and explore using AI for app development: starting with an idea, turning it
into a working feature, and testing and refining the result.

If you would enjoy building a Sudoku app that
suits you—learning Python and AI-assisted development along the way—clone the repository and
make it your own.

## What it does

- **893,916 puzzles across six levels**, from Easy to Extreme, plus a daily game.
- **Flexible entry:** cell-first or number-first play, pencil marks, candidate painting, cell
  colors, and keyboard shortcuts.
- **Help when you want it:** optional error checking, progressive logical hints with board
  diagrams, automatic candidate filling, and Auto Complete.
- **Import your own puzzles** from an image or clipboard text, with an editable clue review.
- **Pick up where you left off:** saved progress, undo/redo, History replay, and statistics.
- **Make it comfortable:** Light, Dark, or System appearance, multiple themes, and a resizable
  board with native macOS Full Screen support.

See the [user guide](docs/user-guide.md) for controls, importing, daily games, and hint details.

## Requirements

- **Platform:** an Apple Silicon Mac running **macOS 27 or newer**.
- **To run from source:** **Python 3.13+**; the pinned development setup was verified with Python 3.14.
- **Development tools:** Git and Xcode or Command Line Tools. Optional local app builds require
  **macOS SDK 27+**.

For a fresh development setup, I recommend [Homebrew](https://brew.sh/) to install and manage
Git and Python. First, install Apple's Xcode Command Line Tools if you do not already have them
or Xcode installed:

```sh
xcode-select --install
```

Finish that installation, then follow the [Homebrew installation instructions](https://brew.sh/),
including the shell setup shown under **Next steps**. With Homebrew ready, install Git and Python:

```sh
brew install git python@3.14
```

## Clone and run from source

With the requirements above installed:

```sh
git clone https://github.com/gpfountz/Sudoku.git
cd Sudoku
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .
.venv/bin/python launch.py
```

Source launches use your normal Sudoku saves by default. See the
[development guide](docs/development.md#setup-and-source-launch) for isolated test data.

### Optional: build a local app

This project is published as source; no prebuilt app is provided. You can build your own
standalone `Sudoku.app`, which includes Python and the puzzle catalog.

Packaging requires exactly **CPython 3.14.6** and the dependencies in `requirements-dev.txt`,
matching the reviewed license inventory. Homebrew's current Python 3.14 patch version may differ.
Follow [packaging Python](docs/development.md#packaging-python) before creating the build environment,
then build, verify, and install locally:

```sh
.venv/bin/python -m sudoku.license_checks
./scripts/build_and_deploy.sh
```

The script installs `~/Applications/Sudoku.app` and saves `Sudoku.zip` in
a new private `/private/tmp/sudoku-release.XXXXXX/` directory, printed on success.
Local builds are ad-hoc signed and are not notarized.
Keep unpacked builds outside cloud-synced folders, and use the ZIP for transfers.
See the [development guide](docs/development.md) for build-only options, custom output folders,
and contributor checks.

## Issues and Pull Requests welcome

I welcome Issues and Pull Requests, including bug reports, ideas, documentation improvements,
and code changes. For bugs, include your macOS and Python versions, steps to reproduce the
problem, and what you expected to happen. For code contributions, follow the existing style,
include type annotations and clear docstrings, and run the checks in the
[development guide](docs/development.md#checks).
See [Contributing](CONTRIBUTING.md) for contribution and licensing expectations.

## License

Copyright © 2026 Greg Pfountz. The original application is licensed under
[GNU GPLv3 only](LICENSE). Distributed derivatives must preserve the required notices and
provide corresponding source under GPLv3. The software comes without warranty.
Puzzle data and third-party components retain their separate terms. See the
[licensing guide](docs/licensing.md), including the current OpenCV binary-release limitation.

## More documentation

- [User guide](docs/user-guide.md) — gameplay, shortcuts, imports, settings, and hints.
- [Development guide](docs/development.md) — setup, testing, packaging, and saved-data recovery.
- [Puzzle catalog](docs/puzzle-catalog.md) — sources, difficulty ratings, and catalog design.
- [Licensing](docs/licensing.md) — attribution, reuse, dependencies, and binary releases.
- [Catalog maintenance and recovery](SQLITE_MIGRATION.md) · [Validation history](VALIDATION.md) ·
  [Adaptive layout](docs/adaptive-layout.md) · [Security policy](SECURITY.md).

The bundled puzzles come from the public-domain
[Sudoku Exchange Puzzle Bank](https://github.com/grantm/sudoku-exchange-puzzle-bank).
The original [puzzle license](sudoku/data/PUZZLE-LICENSE.txt) is included.
