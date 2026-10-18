# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise version batches using real commits, pushes, clones, and merges."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.versioning import VERSION_FILE, install_hooks, set_branch_kind, version_from_source


@dataclass
class Repository:
    """Provide a small isolated checkout and its local bare origin."""

    root: Path
    remote: Path

    def git(self, *arguments: str, success: bool = True) -> str:
        """Invoke real Git without the user's global settings or credentials."""
        environment: dict[str, str] = {
            name: value for name, value in os.environ.items() if not name.startswith("GIT_")
        }
        environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            env=environment,
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout.strip() if success else result.stderr

    def commit(self, message: str, file: str = "changes.txt") -> None:
        """Stage a simple source edit, letting the actual hook update the version."""
        path: Path = self.root / file
        path.write_text((path.read_text() if path.exists() else "") + message + "\n")
        self.git("add", "--", file)
        self.git("commit", "-m", message)

    def version(self) -> str:
        """Read the release version from the same shared file used by the app."""
        return str(version_from_source((self.root / VERSION_FILE).read_text()))


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    """Install real hooks in a tiny clone with no application data or native dependencies."""
    remote: Path = tmp_path / "origin.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
    )
    root: Path = tmp_path / "working copy"
    root.mkdir()
    checkout: Repository = Repository(root, remote)
    checkout.git("init", "--initial-branch=main")
    checkout.git("config", "user.name", "Versioning Test")
    checkout.git("config", "user.email", "versioning@example.invalid")
    checkout.git("config", "commit.gpgsign", "false")
    checkout.git("remote", "add", "origin", str(remote))
    (root / "sudoku").mkdir()
    (root / VERSION_FILE).write_text('APP_VERSION: str = "1.0.0"\n')
    (root / "scripts").mkdir()
    (root / "scripts/__init__.py").write_text('"""Versioning fixture."""\n')
    shutil.copyfile(
        Path(__file__).parents[1] / "scripts/versioning.py", root / "scripts/versioning.py"
    )
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / ".gitattributes").write_text("sudoku/version.py merge=sudoku-version\n")
    checkout.git("add", ".")
    checkout.git("commit", "-m", "initial")
    checkout.git("push", "--set-upstream", "origin", "main")
    install_hooks(root)
    return checkout


def test_main_batches_end_only_after_successful_push(repository: Repository) -> None:
    """Keep several commits at one patch version and increment after a successful push."""
    repository.commit("first")
    assert repository.version() == "1.0.1"
    repository.commit("second")
    assert repository.version() == "1.0.1"
    reject: Path = repository.remote / "hooks/pre-receive"
    reject.write_text("#!/bin/sh\nexit 1\n")
    reject.chmod(0o755)
    repository.git("push", "origin", "main", success=False)
    repository.commit("after rejected push")
    assert repository.version() == "1.0.1"
    reject.unlink()
    repository.git("push", "origin", "main")
    repository.commit("next batch")
    assert repository.version() == "1.0.2"


@pytest.mark.parametrize("allow_empty", [False, True])
@pytest.mark.parametrize("branch", ["main", "codex/feature-empty"])
def test_no_source_changes_do_not_prepare_a_version(
    repository: Repository, allow_empty: bool, branch: str
) -> None:
    """Leave the version alone for empty CI commits and unsuccessful no-change attempts."""
    if branch != "main":
        repository.git("switch", "-c", branch)
    arguments: list[str] = ["commit", "-m", "no source changes"]
    if allow_empty:
        arguments.append("--allow-empty")
    repository.git(*arguments, success=allow_empty)
    assert repository.version() == "1.0.0"
    assert repository.git("status", "--porcelain") == ""
    repository.commit("actual change")
    assert repository.version() == ("1.0.1" if branch == "main" else "1.1.0")


def test_feature_once_then_pr_fixes_use_patch_batches(repository: Repository) -> None:
    """Reserve one minor, then increment patch once for each pushed PR-fix batch."""
    repository.git("switch", "-c", "codex/new-display")
    set_branch_kind(repository.root, "feature")
    repository.commit("new feature")
    assert repository.version() == "1.1.0"
    repository.commit("finish feature")
    assert repository.version() == "1.1.0"
    repository.git("push", "-u", "origin", "HEAD")
    repository.commit("PR correction")
    assert repository.version() == "1.1.1"
    repository.commit("more PR corrections")
    assert repository.version() == "1.1.1"
    repository.git("push", "origin", "HEAD")
    repository.commit("second PR-fix batch")
    assert repository.version() == "1.1.2"


def test_unclassified_pr_branch_defaults_to_patch(repository: Repository) -> None:
    """Treat a branch for PR repair as a fix unless a genuine feature is declared."""
    repository.git("switch", "-c", "codex/repair-pr")
    repository.commit("fix PR")
    assert repository.version() == "1.0.1"
    repository.commit("another correction")
    assert repository.version() == "1.0.1"
    repository.git("push", "-u", "origin", "HEAD")
    repository.commit("next corrections")
    assert repository.version() == "1.0.2"


@pytest.mark.parametrize("squash", [False, True])
def test_merging_feature_preserves_version(repository: Repository, squash: bool) -> None:
    """Retain the feature version in normal and squash merges without adding a patch."""
    repository.git("switch", "-c", "codex/feature-layout")
    repository.commit("feature", "feature.txt")
    assert repository.version() == "1.1.0"
    repository.git("switch", "main")
    if squash:
        repository.git("merge", "--squash", "codex/feature-layout")
        repository.git("commit", "-m", "merge feature")
    else:
        repository.git("merge", "--no-ff", "codex/feature-layout", "-m", "merge feature")
    assert repository.version() == "1.1.0"
    repository.commit("same unpublished batch")
    assert repository.version() == "1.1.0"
    repository.git("push", "origin", "main")
    repository.commit("main follow-up")
    assert repository.version() == "1.1.1"


def test_partial_staging_does_not_capture_unstaged_edits(repository: Repository) -> None:
    """Commit the staged edit and version while retaining unrelated unstaged content."""
    path: Path = repository.root / "changes.txt"
    path.write_text("staged\n")
    repository.git("add", "changes.txt")
    path.write_text("unstaged\n")
    repository.git("commit", "-m", "partial commit")
    assert repository.git("show", "HEAD:changes.txt") == "staged"
    assert path.read_text() == "unstaged\n"
    assert repository.version() == "1.0.1"
    assert repository.git("diff", "--cached") == ""


def test_commit_only_uses_the_active_git_index(repository: Repository) -> None:
    """Include the version even when Git supplies a temporary index for commit --only."""
    repository.commit("initial edit")
    repository.git("push", "origin", "main")
    (repository.root / "changes.txt").write_text("selected edit\n")
    repository.git("commit", "--only", "changes.txt", "-m", "only selected file")
    assert repository.version() == "1.0.2"
    assert '"1.0.2"' in repository.git("show", f"HEAD:{VERSION_FILE}")


@pytest.mark.parametrize("extra", ["# Unstaged personal note\n", "\n"])
def test_other_unstaged_version_edits_are_not_silently_added(
    repository: Repository, extra: str
) -> None:
    """Refuse to stage unrelated changes inside the shared version file."""
    path: Path = repository.root / VERSION_FILE
    path.write_text(path.read_text() + extra)
    (repository.root / "changes.txt").write_text("staged work\n")
    repository.git("add", "changes.txt")
    error: str = repository.git("commit", "-m", "keep unstaged note", success=False)
    assert "Stage your other edits" in error
    assert "personal note" not in repository.git("show", f":{VERSION_FILE}")


def test_major_requires_explicit_manual_override(repository: Repository) -> None:
    """Reject an accidental major change and accept only an explicitly requested override."""
    (repository.root / VERSION_FILE).write_text('APP_VERSION: str = "2.0.0"\n')
    repository.git("add", VERSION_FILE)
    error: str = repository.git("commit", "-m", "unexpected major", success=False)
    assert "Major changes require explicit approval" in error
    repository.git("-c", "sudoku.versioning.manual=true", "commit", "-m", "approved major")
    assert repository.version() == "2.0.0"


def test_existing_hooks_are_preserved(repository: Repository) -> None:
    """Do not replace another hook or partially change the installed hook set."""
    path: Path = repository.root / ".git/hooks/pre-commit"
    path.write_text("#!/bin/sh\n# user's existing hook\n")
    before: bytes = (repository.root / ".git/hooks/pre-merge-commit").read_bytes()
    with pytest.raises(ValueError, match="Existing hook"):
        install_hooks(repository.root)
    assert "user's existing hook" in path.read_text()
    assert (repository.root / ".git/hooks/pre-merge-commit").read_bytes() == before


def test_cloned_feature_continues_with_patch(repository: Repository, tmp_path: Path) -> None:
    """Recover a published feature's version in another clone without local branch markers."""
    repository.git("switch", "-c", "codex/feature-layout")
    repository.commit("feature")
    repository.git("push", "-u", "origin", "HEAD")
    clone: Path = tmp_path / "second clone"
    repository.git("clone", str(repository.remote), str(clone))
    other: Repository = Repository(clone, repository.remote)
    other.git("config", "user.name", "Versioning Test")
    other.git("config", "user.email", "versioning@example.invalid")
    other.git("config", "commit.gpgsign", "false")
    other.git("switch", "codex/feature-layout")
    install_hooks(clone)
    other.commit("PR fix in new clone")
    assert other.version() == "1.1.1"


def test_legacy_metadata_can_transition_to_shared_version(repository: Repository) -> None:
    """Read the previous static pyproject version during the automation's first commit."""
    repository.git("rm", VERSION_FILE)
    (repository.root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    repository.git("add", "pyproject.toml")
    repository.git("-c", "core.hooksPath=/dev/null", "commit", "-m", "legacy fixture")
    (repository.root / "sudoku").mkdir(exist_ok=True)
    (repository.root / VERSION_FILE).write_text('APP_VERSION: str = "1.0.0"\n')
    repository.git("add", VERSION_FILE)
    repository.git("commit", "-m", "introduce shared version")
    assert repository.version() == "1.0.1"


def test_parallel_main_and_feature_versions_merge_cleanly(repository: Repository) -> None:
    """Keep the higher minor version when main has independently advanced its patch."""
    repository.git("switch", "-c", "codex/feature-layout")
    repository.commit("feature", "feature.txt")
    assert repository.version() == "1.1.0"
    repository.git("switch", "main")
    repository.commit("main fix", "main.txt")
    assert repository.version() == "1.0.1"
    repository.git("merge", "--no-ff", "codex/feature-layout", "-m", "merge feature")
    assert repository.version() == "1.1.0"
    assert repository.git("status", "--porcelain") == ""


def test_new_feature_resets_patch_and_nested_feature_gets_new_minor(repository: Repository) -> None:
    """Reset patch to zero and distinguish a new feature from continued work on an old one."""
    repository.commit("main patch")
    repository.git("push", "origin", "main")
    repository.git("switch", "-c", "codex/feature-one")
    repository.commit("first feature")
    assert repository.version() == "1.1.0"
    repository.git("switch", "-c", "codex/feature-two")
    repository.commit("second feature")
    assert repository.version() == "1.2.0"


def test_fix_classification_overrides_feature_name(repository: Repository) -> None:
    """Use a patch for PR repairs even when the branch name resembles a feature."""
    repository.git("switch", "-c", "codex/feature-pr-repair")
    set_branch_kind(repository.root, "fix")
    repository.commit("repair PR")
    assert repository.version() == "1.0.1"


def test_worktree_uses_shared_hooks(repository: Repository, tmp_path: Path) -> None:
    """Install into the common hooks directory and run the policy from a linked worktree."""
    linked: Path = tmp_path / "linked checkout"
    repository.git("worktree", "add", "-b", "codex/feature-linked", str(linked))
    install_hooks(linked)
    other: Repository = Repository(linked, repository.remote)
    other.commit("linked feature")
    assert other.version() == "1.1.0"


def test_merging_multiple_pr_fix_batches_preserves_patch(repository: Repository) -> None:
    """Do not lower a PR's published patch version when it is merged into main."""
    repository.git("switch", "-c", "codex/repair")
    repository.commit("fix", "fix.txt")
    repository.git("push", "-u", "origin", "HEAD")
    repository.commit("PR correction", "fix.txt")
    assert repository.version() == "1.0.2"
    repository.git("switch", "main")
    repository.git("merge", "--no-ff", "codex/repair", "-m", "merge repaired PR")
    assert repository.version() == "1.0.2"


def test_stale_branch_reservation_cannot_change_major(repository: Repository) -> None:
    """Keep the major-version boundary even if stale local branch state requests a higher major."""
    repository.git("switch", "-c", "codex/feature-stale")
    repository.git("config", "branch.codex/feature-stale.sudokuVersion", "2.1.0")
    (repository.root / "changes.txt").write_text("feature work\n")
    repository.git("add", "changes.txt")
    error: str = repository.git("commit", "-m", "feature", success=False)
    assert "cannot change major" in error
    assert repository.version() == "1.0.0"


def test_rebase_amend_preserves_existing_version(repository: Repository) -> None:
    """Replay and amend existing feature history without a new bump or detached-HEAD failure."""
    repository.git("switch", "-c", "codex/feature-rebase")
    repository.commit("feature")
    repository.git("rebase", "--force-rebase", "--exec", "git commit --amend --no-edit", "main")
    assert repository.version() == "1.1.0"
