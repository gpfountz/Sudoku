# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise release-path controls against other-account ownership, aliases, and write access."""

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from sudoku.build_paths import prepare_directory, verify_artifact_paths


def test_create_private_output_beneath_owned_parents(tmp_path: Path) -> None:
    """Create missing output folders privately while retaining existing ordinary permissions."""
    parent: Path = tmp_path / "owned parent"
    parent.mkdir(mode=0o755)
    output: Path = prepare_directory(parent / "release")
    assert output == (parent / "release").resolve()
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert prepare_directory(output) == output


def test_new_ancestors_are_private_with_permissive_umask(tmp_path: Path) -> None:
    """Keep every newly created ancestor private even when the shell permits shared writes."""
    previous_mask: int = os.umask(0)
    try:
        output: Path = prepare_directory(tmp_path / "new parent" / "release")
        assert stat.S_IMODE(output.stat().st_mode) == 0o700
        assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    finally:
        os.umask(previous_mask)


@pytest.mark.parametrize("ancestor", [False, True])
@pytest.mark.parametrize("mode", [0o775, 0o777, 0o1777])
def test_reject_other_account_write_access(tmp_path: Path, ancestor: bool, mode: int) -> None:
    """Refuse writable output or ancestors, even when a user-owned sticky bit is present."""
    unsafe: Path = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(mode)
    try:
        with pytest.raises(ValueError, match="writable by another account"):
            prepare_directory(unsafe / "release" if ancestor else unsafe)
        if ancestor:
            assert not (unsafe / "release").exists()
    finally:
        unsafe.chmod(0o700)


@pytest.mark.parametrize("ancestor", [False, True])
def test_reject_foreign_directory_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ancestor: bool
) -> None:
    """Model another UID owning an otherwise non-writable directory without privileged chown."""
    unsafe: Path = tmp_path / "foreign"
    unsafe.mkdir()
    original_lstat: Callable[[Path], os.stat_result] = Path.lstat

    def report_foreign_owner(path: Path) -> os.stat_result:
        """Keep actual filesystem metadata except for the selected directory's owner."""
        metadata: os.stat_result = original_lstat(path)
        if path == unsafe:
            fields: list[int | float] = list(metadata)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return metadata

    monkeypatch.setattr(Path, "lstat", report_foreign_owner)
    with pytest.raises(ValueError, match="unexpected owner"):
        prepare_directory(unsafe / "release" if ancestor else unsafe)


@pytest.mark.parametrize("ancestor", [False, True])
def test_reject_user_symlink_and_dangling_alias(tmp_path: Path, ancestor: bool) -> None:
    """Reject symlink hops before resolution can hide them, including missing destinations."""
    target: Path = tmp_path / "actual"
    if ancestor:
        target.mkdir()
    alias: Path = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        prepare_directory(alias / "release" if ancestor else alias)
    assert not (target / "release").exists()


def test_root_sticky_ancestor_allows_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permit the system temporary-directory model while requiring an owned output child."""
    shared: Path = tmp_path / "shared"
    shared.mkdir()
    original_lstat: Callable[[Path], os.stat_result] = Path.lstat

    def report_system_temporary_directory(path: Path) -> os.stat_result:
        """Model a root-owned sticky parent without modifying the host temporary directory."""
        metadata: os.stat_result = original_lstat(path)
        if path == shared:
            fields: list[int | float] = list(metadata)
            fields[0] = stat.S_IFDIR | 0o1777
            fields[4] = 0
            return os.stat_result(fields)
        return metadata

    monkeypatch.setattr(Path, "lstat", report_system_temporary_directory)
    assert prepare_directory(shared / "release").is_dir()


@pytest.mark.parametrize("name", ["Sudoku.app", "Sudoku.zip"])
def test_reject_artifact_symlinks(tmp_path: Path, name: str) -> None:
    """Prevent archive and application aliases, including dangling links, from being followed."""
    (tmp_path / name).symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="unsafe owner or file type"):
        verify_artifact_paths(tmp_path)


def test_reject_archive_directory(tmp_path: Path) -> None:
    """Do not treat an existing ZIP directory as a container for a new archive."""
    (tmp_path / "Sudoku.zip").mkdir()
    with pytest.raises(ValueError, match="unsafe owner or file type"):
        verify_artifact_paths(tmp_path)


@pytest.mark.parametrize("suffix", ["\n", "\r", "\n\n"])
def test_reject_newline_paths_before_shell_conversion(tmp_path: Path, suffix: str) -> None:
    """Do not let shell command substitution change a validated destination's identity."""
    with pytest.raises(ValueError, match="newline characters"):
        prepare_directory(tmp_path / ("release" + suffix))
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended ACLs")
@pytest.mark.parametrize("ancestor", [False, True])
@pytest.mark.parametrize(
    "permissions",
    [
        "add_file,delete_child",
        "add_file,delete_child,file_inherit,directory_inherit,only_inherit",
        "writesecurity",
    ],
)
def test_reject_real_acl_write_grants(tmp_path: Path, ancestor: bool, permissions: str) -> None:
    """Reject real macOS ACLs even though ordinary mode bits report no shared writes."""
    unsafe: Path = tmp_path / "acl-writable"
    unsafe.mkdir(mode=0o755)
    subprocess.run(["/bin/chmod", "+a", f"everyone allow {permissions}", str(unsafe)], check=True)
    try:
        assert stat.S_IMODE(unsafe.stat().st_mode) == 0o755
        with pytest.raises(ValueError, match="ACL write grant"):
            prepare_directory(unsafe / "release" if ancestor else unsafe)
    finally:
        subprocess.run(["/bin/chmod", "-N", str(unsafe)], check=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended ACLs")
@pytest.mark.parametrize("entry", ["everyone deny delete", "everyone allow read,readattr"])
def test_preserve_harmless_acl_entries(tmp_path: Path, entry: str) -> None:
    """Accept normal macOS deny-delete ACLs and read-only grants without altering them."""
    directory: Path = tmp_path / "safe-acl"
    directory.mkdir()
    subprocess.run(["/bin/chmod", "+a", entry, str(directory)], check=True)
    try:
        assert prepare_directory(directory) == directory.resolve()
    finally:
        subprocess.run(["/bin/chmod", "-N", str(directory)], check=True)
