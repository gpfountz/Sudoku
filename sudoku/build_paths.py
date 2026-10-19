# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Keep local build and installation paths under the invoking user's control."""

import argparse
import ctypes
import errno
import os
import stat
import sys
from pathlib import Path

ACL_WRITE_PERMISSIONS: frozenset[str] = frozenset(
    {
        "write",
        "append",
        "delete",
        "delete_child",
        "writeattr",
        "writeextattr",
        "writesecurity",
        "chown",
    }
)


def directory_acl_text(path: Path) -> str:
    """Read macOS extended ACLs through libc, preserving deny and inheritance information."""
    if sys.platform != "darwin":
        return ""
    library: ctypes.CDLL = ctypes.CDLL(None, use_errno=True)
    library.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.acl_get_file.restype = ctypes.c_void_p
    library.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    library.acl_to_text.restype = ctypes.c_void_p
    library.acl_free.argtypes = [ctypes.c_void_p]
    library.acl_free.restype = ctypes.c_int
    acl: int | None = library.acl_get_file(os.fsencode(path), 0x100)  # ACL_TYPE_EXTENDED
    if acl is None:
        error: int = ctypes.get_errno()
        if error == errno.ENOENT:
            # Darwin reports ENOENT for an existing directory with no extended
            # ACL. Distinguish that case from an actually missing pathname.
            path.lstat()
            return ""
        if error in (errno.ENOTSUP, errno.EOPNOTSUPP):
            return ""
        raise OSError(error, os.strerror(error), path)
    text: int | None = None
    try:
        text = library.acl_to_text(acl, None)
        if text is None:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), path)
        return ctypes.string_at(text).decode("utf-8")
    finally:
        if text is not None:
            library.acl_free(text)
        library.acl_free(acl)


def verify_directory_acl(path: Path) -> None:
    """Reject ACL write grants, including grants inherited by subsequently published files."""
    for entry in directory_acl_text(path).splitlines():
        if not entry or entry.startswith("!#acl "):
            continue
        fields: list[str] = entry.rsplit(":", 2)
        if len(fields) != 3:
            raise ValueError(f"Cannot validate the build path's ACL: {path}")
        flags: set[str] = set(fields[1].split(","))
        permissions: set[str] = set(fields[2].split(","))
        if "allow" in flags and permissions & ACL_WRITE_PERMISSIONS:
            raise ValueError(f"Build path has an ACL write grant: {path}")


def verify_directory(path: Path, *, require_owner: bool = False) -> None:
    """Reject directories another local account could change or replace."""
    metadata: os.stat_result = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"Build path must be a directory, without symlinks: {path}")
    current_user: int = os.getuid()
    if metadata.st_uid not in (0, current_user) or (
        require_owner and metadata.st_uid != current_user
    ):
        raise ValueError(f"Build path has an unexpected owner: {path}")
    shared_system_directory: bool = metadata.st_uid == 0 and bool(metadata.st_mode & stat.S_ISVTX)
    if metadata.st_mode & 0o022 and not shared_system_directory:
        raise ValueError(f"Build path is writable by another account: {path}")
    if require_owner and metadata.st_mode & 0o022:
        raise ValueError(f"Build destination is writable by another account: {path}")
    verify_directory_acl(path)


def prepare_directory(directory: Path) -> Path:
    """Create a user-owned destination beneath safe ancestors and return its canonical path."""
    requested: Path = directory.expanduser().absolute()
    if "\n" in str(requested) or "\r" in str(requested):
        raise ValueError("Build paths cannot contain newline characters.")
    for path in (*reversed(requested.parents), requested):
        try:
            metadata: os.stat_result = path.lstat()
        except FileNotFoundError:
            continue
        # macOS supplies root-owned aliases such as /tmp and /var. User aliases
        # are rejected so resolving them cannot hide an attacker-controlled hop.
        if stat.S_ISLNK(metadata.st_mode) and metadata.st_uid == 0 and path != requested:
            continue
        verify_directory(path)
    canonical: Path = requested.resolve()
    for path in (*reversed(canonical.parents), canonical):
        try:
            verify_directory(path)
        except FileNotFoundError:
            path.mkdir(mode=0o700)
            verify_directory(path, require_owner=True)
    verify_directory(canonical, require_owner=True)
    return canonical


def verify_artifact_paths(directory: Path) -> None:
    """Reject output aliases and wrong file types before replacing build artifacts."""
    for name, is_directory in (
        ("Sudoku.app", True),
        ("Sudoku.zip", False),
        ("build-info.json", False),
    ):
        path: Path = directory / name
        try:
            metadata: os.stat_result = path.lstat()
        except FileNotFoundError:
            continue
        correct_type: bool = (
            stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
        )
        if not correct_type or metadata.st_uid != os.getuid():
            raise ValueError(f"Build artifact has an unsafe owner or file type: {path}")


def main() -> None:
    """Resolve a shell helper's destination through the builder's shared safety checks."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    arguments: argparse.Namespace = parser.parse_args()
    try:
        print(prepare_directory(arguments.directory))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
