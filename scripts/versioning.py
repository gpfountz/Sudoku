# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Apply the maintainer's version policy to local Git commit batches."""

import argparse
import ast
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

VERSION_FILE: str = "sudoku/version.py"
ASSIGNMENT: re.Pattern[str] = re.compile(r'(?m)^APP_VERSION: str = "[^"]+"$')


@dataclass(frozen=True, order=True)
class Version:
    """Represent the three independently controlled release components."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        """Require a canonical numeric major.minor.patch version."""
        if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", text):
            raise ValueError(f"Invalid release version: {text!r}")
        major: int
        minor: int
        patch: int
        major, minor, patch = map(int, text.split("."))
        return cls(major, minor, patch)

    def __str__(self) -> str:
        """Render the version used by the application and package metadata."""
        return f"{self.major}.{self.minor}.{self.patch}"


def git(root: Path, *arguments: str, optional: bool = False, raw: bool = False) -> str | None:
    """Run Git against the current index, retaining alternate-index commit support."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True
    )
    if result.returncode:
        if optional:
            return None
        raise ValueError(result.stderr.strip() or f"Git failed: {' '.join(arguments)}")
    return result.stdout if raw else result.stdout.strip()


def version_from_source(source: str) -> Version:
    """Read the version constant without importing application or native modules."""
    for statement in ast.parse(source).body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "APP_VERSION"
            and statement.value is not None
        ):
            value: object = ast.literal_eval(statement.value)
            if isinstance(value, str):
                return Version.parse(value)
    raise ValueError(f"Missing APP_VERSION in {VERSION_FILE}")


def version_at(root: Path, revision: str) -> Version | None:
    """Read modern version metadata or the pre-automation project's static version."""
    source: str | None = git(root, "show", f"{revision}:{VERSION_FILE}", optional=True, raw=True)
    if source is not None:
        return version_from_source(source)
    legacy: str | None = git(root, "show", f"{revision}:pyproject.toml", optional=True)
    if legacy is None:
        return None
    value: object = tomllib.loads(legacy).get("project", {}).get("version")
    return Version.parse(value) if isinstance(value, str) else None


def patch_batch(head: Version, staged: Version, published: Version) -> Version:
    """Bump once beyond the published batch, retaining merged feature versions."""
    if head < published:
        raise ValueError("Update this branch from origin before committing a version change.")
    if staged > head:
        return staged
    if head > published:
        return head
    return Version(head.major, head.minor, head.patch + 1)


def creation_version(root: Path, branch: str, fallback: Version) -> Version:
    """Recover the branch's initial baseline for a batch that has never been pushed."""
    entries: str = git(root, "reflog", "show", "--format=%H", branch, optional=True) or ""
    created: Version | None = version_at(root, entries.splitlines()[-1]) if entries else None
    return created or fallback


def branch_kind(root: Path, branch: str) -> str:
    """Treat unclassified work as fixes, reserving minor increments for explicit features."""
    configured: str | None = git(
        root, "config", "--local", "--get", f"branch.{branch}.sudokuChange", optional=True
    )
    if configured:
        if configured not in ("feature", "fix"):
            raise ValueError(f"Unknown versioning kind: {configured}")
        return configured
    return "feature" if branch.startswith(("feature/", "codex/feature-")) else "fix"


def branch_version(root: Path, branch: str, head: Version, staged: Version) -> Version:
    """Allocate a feature once; use patch batches for fixes and later PR follow-ups."""
    key: str = f"branch.{branch}.sudokuVersion"
    reserved: str | None = git(root, "config", "--local", "--get", key, optional=True)
    published: Version | None = version_at(root, f"refs/remotes/origin/{branch}")
    if (
        reserved
        and branch_kind(root, branch) == "feature"
        and (published is None or Version.parse(reserved) > published)
    ):
        return max(Version.parse(reserved), head, staged)
    if published is not None:
        return patch_batch(head, staged, published)
    baseline: Version = creation_version(root, branch, head)
    if branch_kind(root, branch) == "fix":
        return patch_batch(head, staged, baseline)
    target: Version = (
        max(head, staged) if head > baseline else Version(head.major, head.minor + 1, 0)
    )
    git(root, "config", "--local", key, str(target))
    return target


def main_version(root: Path, head: Version, staged: Version) -> Version:
    """Use origin/main as the successful-push boundary for main's patch batches."""
    published: Version | None = version_at(root, "refs/remotes/origin/main")
    if published is None:
        raise ValueError("Fetch origin/main before using automatic main versioning.")
    return patch_batch(head, staged, published)


def set_branch_kind(root: Path, kind: str) -> None:
    """Mark a new feature explicitly, without increasing the major version."""
    branch: str | None = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True)
    if not branch or branch == "main":
        raise ValueError("Mark a named feature/fix branch; main always uses patch batches.")
    git(root, "config", "--local", f"branch.{branch}.sudokuChange", kind)
    key: str = f"branch.{branch}.sudokuVersion"
    if kind == "feature" and not git(root, "config", "--local", "--get", key, optional=True):
        head: Version | None = version_at(root, "HEAD")
        if head is None:
            raise ValueError("A feature branch needs an initial version.")
        git(root, "config", "--local", key, str(Version(head.major, head.minor + 1, 0)))


def prepare_version(root: Path) -> Version:
    """Stage only the shared version file, preserving unrelated staged or unstaged edits."""
    branch: str | None = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True)
    if not branch:
        for name in ("rebase-merge", "rebase-apply"):
            state: Path = Path(git(root, "rev-parse", "--git-path", name) or "")
            if not state.is_absolute():
                state = root / state
            if state.is_dir():
                return version_from_source((root / VERSION_FILE).read_text())
        raise ValueError("Automatic versioning requires a named branch, not detached HEAD.")
    path: Path = root / VERSION_FILE
    source: str = path.read_text()
    current: Version = version_from_source(source)
    staged_source: str | None = git(root, "show", f":{VERSION_FILE}", optional=True, raw=True)
    if staged_source is None:
        raise ValueError(f"Stage {VERSION_FILE} before enabling automatic versioning.")
    if ASSIGNMENT.sub('APP_VERSION: str = "VERSION"', source) != ASSIGNMENT.sub(
        'APP_VERSION: str = "VERSION"', staged_source
    ):
        raise ValueError(f"Stage your other edits to {VERSION_FILE} before committing.")
    head: Version | None = version_at(root, "HEAD")
    if head is None:
        raise ValueError("Commit an initial version before installing automatic versioning.")
    staged: Version = version_from_source(staged_source)
    manual: bool = (
        git(root, "config", "--bool", "--get", "sudoku.versioning.manual", optional=True) == "true"
    )
    if not manual and (current.major != head.major or staged.major != head.major):
        raise ValueError(
            "Major changes require explicit approval and "
            "git -c sudoku.versioning.manual=true commit."
        )
    target: Version = (
        current
        if manual
        else (
            main_version(root, head, staged)
            if branch == "main"
            else branch_version(root, branch, head, staged)
        )
    )
    if target < head:
        raise ValueError("Automatic versioning will not lower the current release version.")
    if not manual and target.major != head.major:
        raise ValueError(
            "Automatic versioning cannot change major; review this branch's version state."
        )
    updated: str
    count: int
    updated, count = ASSIGNMENT.subn(f'APP_VERSION: str = "{target}"', source)
    if count != 1:
        raise ValueError(f"Expected exactly one annotated APP_VERSION in {VERSION_FILE}")
    if updated != source:
        path.write_text(updated)
    git(root, "add", "--", VERSION_FILE)
    return target


def merge_versions(base: Path, current: Path, incoming: Path) -> None:
    """Merge the higher existing version without discarding unrelated metadata edits."""
    original: str = base.read_text()
    ours: str = current.read_text()
    theirs: str = incoming.read_text()
    selected: Version = max(version_from_source(ours), version_from_source(theirs))
    normalized: list[str] = [
        ASSIGNMENT.sub('APP_VERSION: str = "VERSION"', text) for text in (original, ours, theirs)
    ]
    if normalized[1] == normalized[2] or normalized[2] == normalized[0]:
        template: str = ours
    elif normalized[1] == normalized[0]:
        template = theirs
    else:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "merge-file", str(current), str(base), str(incoming)],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise ValueError("Resolve the non-version edits in sudoku/version.py manually.")
        template = current.read_text()
    current.write_text(ASSIGNMENT.sub(f'APP_VERSION: str = "{selected}"', template))


def install_hooks(root: Path) -> None:
    """Install local commit hooks without replacing other active hook configurations."""
    configured: str | None = git(root, "config", "--get", "core.hooksPath", optional=True)
    if configured:
        raise ValueError("Existing core.hooksPath must be integrated manually; no hooks changed.")
    directory: Path = Path(
        git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks") or ""
    )
    command: str = shlex.quote(str(Path(sys.executable).absolute()))
    content: str = (
        f"#!/bin/sh\n# Sudoku automatic versioning\nexec {command} -m scripts.versioning prepare\n"
    )
    paths: list[Path] = [directory / name for name in ("pre-commit", "pre-merge-commit")]
    for path in paths:
        if path.exists() and path.read_text() != content:
            raise ValueError(f"Existing hook must be integrated manually: {path.name}")
    driver: str = f'{command} -m scripts.versioning merge "%O" "%A" "%B"'
    existing: str | None = git(
        root, "config", "--get", "merge.sudoku-version.driver", optional=True
    )
    if existing and existing != driver:
        raise ValueError("Existing sudoku-version merge driver must be integrated manually.")
    directory.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path.write_text(content)
        path.chmod(0o755)
    git(root, "config", "--local", "merge.sudoku-version.name", "Sudoku release version")
    git(root, "config", "--local", "merge.sudoku-version.driver", driver)


def main() -> None:
    """Install opt-in hooks or prepare the next commit's shared release version."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "prepare", "kind", "merge"))
    parser.add_argument("values", nargs="*")
    arguments: argparse.Namespace = parser.parse_args()
    root: Path = Path(git(Path.cwd(), "rev-parse", "--show-toplevel") or "")
    try:
        if arguments.command == "install":
            install_hooks(root)
            print("Installed Sudoku version hooks for this clone.")
        elif arguments.command == "kind":
            if len(arguments.values) != 1 or arguments.values[0] not in ("feature", "fix"):
                parser.error("kind requires feature or fix")
            set_branch_kind(root, arguments.values[0])
            print(f"Branch versioning kind: {arguments.values[0]}")
        elif arguments.command == "merge":
            if len(arguments.values) != 3:
                parser.error("merge requires base, current, and incoming files")
            merge_versions(*(Path(value) for value in arguments.values))
        else:
            print(f"Sudoku version: {prepare_version(root)}")
    except (OSError, ValueError, SyntaxError) as error:
        parser.exit(1, f"Versioning: {error}\n")


if __name__ == "__main__":
    main()
