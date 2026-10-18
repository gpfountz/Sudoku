# Catalog maintenance and recovery

[Development guide](docs/development.md) · [Puzzle catalog](docs/puzzle-catalog.md)

The prepared six-database catalog is included in the repository. Normal source launches and
app builds use it directly. These instructions are for regenerating catalog data, checking
resources, and backing up or recovering local progress. Run commands from the repository root
with the development environment from the [setup guide](docs/development.md#setup-and-source-launch).

## Prepare a catalog from the upstream bank

Quit Sudoku and back up your user data before replacing a catalog used by an installed app.
Use a separate feature branch for catalog changes. The preparation script reads local supplied
files; the following clone command is the network step:

```sh
SUDOKU_BANK_DIR=$(mktemp -d /private/tmp/sudoku-puzzle-bank.XXXXXX)
git clone --depth 1 https://github.com/grantm/sudoku-exchange-puzzle-bank.git "$SUDOKU_BANK_DIR"
.venv/bin/python scripts/prepare_puzzles.py --source "$SUDOKU_BANK_DIR" --output sudoku/data/catalog
```

If the bank is already available locally, set `SUDOKU_BANK_DIR` to its checkout and skip cloning.
All rows in `easy.txt`, `medium.txt`, `hard.txt`, and `diabolical.txt` are read. The app's six
rating bands and SHA-256-derived IDs remain stable. Preparation checks formats, identities,
duplicate IDs/clues, unique solutions, ratings, SQLite integrity, and the 100 MiB per-file limit.
A failure leaves the previous manifest active. Review a size-limit failure before changing how
catalog data is distributed; do not silently discard puzzles.

An optional small smoke import writes separate resources:

```sh
SUDOKU_SMALL_DIR=$(mktemp -d /private/tmp/sudoku-catalog-small.XXXXXX)
.venv/bin/python scripts/prepare_puzzles.py --source "$SUDOKU_BANK_DIR" --output "$SUDOKU_SMALL_DIR" --limit-per-level 12
```

The tool also accepts supplied JSONL records with `id`, `givens`, `solution`, `rating`, `level`,
and `source`, plus optional source metadata. Boards use 81 digits, with zeros for empty clues.
Version-1 JSON catalogs remain accepted for legacy conversion when that source file is supplied;
there is no legacy `sudoku/data/puzzles.json` in the current checkout.

## Verify and review the prepared resources

```sh
.venv/bin/python scripts/verify_sqlite.py --catalog sudoku/data/catalog --selections 1000 --integrity-check
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy sudoku tests scripts setup.py launch.py
git diff --stat
git status --short
```

The verifier reads all six database row counts and integrity results, measures selection latency
and memory, and checks save/resume in temporary player storage. It does not read personal saves.
Its final line should be `PASS: catalog resources and isolated save/resume verified`.
Automated tests prepare a twelve-puzzle subset per difficulty; they do not replace full-catalog
verification. The checked-in catalog currently has 893,916 puzzles, not one million.

Preparation publishes a UUID-named generation through `sudoku/data/catalog/manifest.json`.
Only the active generation is required for runtime or app packaging. Inspect any old generations
before removing them, and preserve stable IDs needed by existing saves. Never remove the directory
named by the current manifest. Only puzzle catalog databases belong under `sudoku/data/catalog/`;
never copy player, imported, daily, or History data there.

## Build and inspect the standalone resources

Use the exact [packaging environment](docs/development.md#packaging-python), including the
license checks. Before publishing a binary, resolve the documented
[OpenCV provenance requirement](docs/licensing.md#publishing-a-standalone-app).
To build and extract without installing:

```sh
SUDOKU_BUILD_DIR=$(mktemp -d /private/tmp/sudoku-release.XXXXXX)
.venv/bin/python -m sudoku.license_checks
.venv/bin/python scripts/build_app.py --output-dir "$SUDOKU_BUILD_DIR"
SUDOKU_EXTRACT_DIR=$(mktemp -d /private/tmp/sudoku-extracted.XXXXXX)
ditto -x -k "$SUDOKU_BUILD_DIR/Sudoku.zip" "$SUDOKU_EXTRACT_DIR"
codesign --verify --deep --strict "$SUDOKU_EXTRACT_DIR/Sudoku.app"
.venv/bin/python scripts/verify_sqlite.py --catalog "$SUDOKU_EXTRACT_DIR/Sudoku.app/Contents/Resources/catalog" --selections 100 --integrity-check
```

The bundle must contain exactly six SQLite catalog files, only under
`Contents/Resources/catalog/<generation>/`, without duplicate package-data catalogs. Check About,
View License, and Third-Party Notices offline. Local signature checks verify integrity; these
builds are ad-hoc signed and are not notarized.

For a packaged save/resume smoke test, create the test directory once:

```sh
SUDOKU_GUI_TEST_DIR=$(mktemp -d /private/tmp/sudoku-gui-test.XXXXXX)
SUDOKU_DATA_DIR="$SUDOKU_GUI_TEST_DIR" SUDOKU_WINDOW_AUTOSAVE_NAME=SudokuCatalogTest \
  "$SUDOKU_EXTRACT_DIR/Sudoku.app/Contents/MacOS/Sudoku"
```

Start a game, enter answers/notes, and quit normally. Relaunch with the same command and the
same test directory; progress and history should resume. Keep the exact directory paths for
later terminal sessions. Finder launches use normal user saves instead of this test directory.
Use the [deployment helper](docs/development.md#building-and-installing) when ready to install.
It performs signature checks and rollback, but it does not perform this gameplay smoke test.

## Back up and recover user data

Quit the app before copying data. Back up the whole Application Support directory together:

```sh
SUDOKU_BACKUP_DIR=$(mktemp -d "$HOME/Sudoku-backup.XXXXXX")
ditto "$HOME/Library/Application Support/Sudoku" "$SUDOKU_BACKUP_DIR/user-data"
```

If the data directory does not exist, there is no existing user data to back up. Keep any previous
app separately when testing a migration; it may not understand newer saved data.
See [local data and recovery](docs/development.md#local-data-and-recovery) for current filenames.

First launch with legacy JSON validates the original or its valid backup, resolves stable puzzle
IDs, and imports regular progress into SQLite. Original JSON files remain as migration backups.
Historical played IDs retain unknown completion status without invented timestamps. Failed or
interrupted migration preserves the originals and can be retried after the reported error is fixed.
Legacy `statistics.sqlite3` is migrated to `history.sqlite3`.

Restore a known-good copy of the entire data directory with Sudoku closed when recovering SQLite
corruption or a broken active pointer. Preserve the damaged directory separately before restoring.
The JSON Recover Saving action does not repair SQLite. An older app may read stale JSON rather
than newer SQLite progress, so reopening it is not a rollback of current player data.
