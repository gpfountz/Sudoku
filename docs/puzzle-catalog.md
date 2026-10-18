# Puzzle catalog

[Back to the README](../README.md)

## Puzzle provenance

The bundled catalog comes from the [Sudoku Exchange Puzzle Bank](https://github.com/grantm/sudoku-exchange-puzzle-bank), dedicated to the public domain.
Its original license is included in [`sudoku/data/PUZZLE-LICENSE.txt`](../sudoku/data/PUZZLE-LICENSE.txt).

The upstream puzzles were generated with QQWing and rated using Sukaku Explainer.
All supplied puzzles are included in these bands:

| App level | Published rating band |
| --- | --- |
| Easy | below 1.5 |
| Medium | 1.5–2.4 |
| Hard | 2.5–4.9 |
| Expert | 5.0–6.9 |
| Master | 7.0–8.9 |
| Extreme | 9.0 and above |

`scripts/prepare_puzzles.py` reads all four files in a local bank checkout without a per-level cap.
It also accepts the old prepared JSON catalog or streaming JSONL records. It does not download or
generate puzzles. An explicit `--limit-per-level` prepares a small test catalog.

Preparation checks unique solutions, stable IDs, duplicates, difficulty assignments, SQLite
integrity, and the 100 MiB ordinary-Git file limit. Six read-only databases retain IDs, boards,
solutions, ratings, and normalized source metadata. An atomic manifest publishes a fully validated
generation; failed preparation leaves the previous generation active. Old generations remain
until removed, while app builds package only the active generation.

Runtime opens the SQLite catalog read-only and retrieves puzzles by index. A sparse Fisher-Yates
selection pool avoids repeats without loading or randomly sorting a difficulty's rows. A new cycle
preserves previous attempts. Rebuilding the catalog reconciles the current cycle by stable ID once;
unchanged catalogs do not scan played history at startup.

For catalog preparation, validation, and recovery commands, see
[catalog maintenance and recovery](../SQLITE_MIGRATION.md).
