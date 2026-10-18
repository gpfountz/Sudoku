# Repository guidance

## Version policy

- Use `sudoku/version.py` as the single application version source. Package metadata, the
  app bundle, and About Sudoku read it; do not add separate version literals.
- Install this clone's local automation after creating its virtual environment:
  `.venv/bin/python -m scripts.versioning install`.
- On `main`, the first commit in a new batch increments the patch number once. Additional
  commits retain it until a successful push to `origin/main`. Failed pushes do not end a batch.
- A genuine new feature receives one minor increment, resetting patch to zero. After creating
  its branch and before committing, run `.venv/bin/python -m scripts.versioning kind feature`.
  Names beginning `feature/` or `codex/feature-` also identify new features automatically.
- Bug fixes, PR repairs, and unclassified branches use patch batches. Mark a repair explicitly
  with `.venv/bin/python -m scripts.versioning kind fix` when needed. Working on an existing
  feature PR is not a new feature: after each push, its first follow-up fix increments patch
  once, then holds that version through the remaining unpushed commits.
- Merging a feature into `main` preserves its version; do not add an extra patch for the merge.
- Never change major automatically. Only an explicit user request authorizes a major change.
  For that approved change, edit the shared version and use
  `git -c sudoku.versioning.manual=true commit ...`.
- Leave the internal macOS build identifier separate from this source-version policy.

## Delivery

- Preserve the user's GitHub noreply identity in all public commits.
- Work on `main` unless the user requests a branch. Push when appropriate, then verify the
  exact commit's GitHub CI. Administrator bypass permits direct pushes; CI must still be checked.
- Repository secret-scanning alerts and Dependabot alerts are enabled. Keep repository push
  protection disabled unless the user explicitly changes that preference.
- Publish source only. A built-app release requires separate user authorization and resolution
  of the binary provenance work described in `docs/licensing.md`.
