# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify the application license and the reviewed build's upstream notice snapshots."""

import hashlib
import json
import sys
import sysconfig
from importlib import metadata
from pathlib import Path
from typing import TypedDict

ROOT: Path = Path(__file__).resolve().parents[1]
LICENSES: Path = ROOT / "sudoku/data/licenses"


class NoticeRecord(TypedDict):
    """Identify a verbatim upstream notice and its recorded checksum."""

    file: str
    origin: str
    sha256: str


class LibraryRecord(TypedDict):
    """Identify a native library in a reviewed dependency wheel."""

    package: str
    file: str
    sha256: str


class LicenseInventory(TypedDict):
    """Describe the pinned environment used for the checked-in license inventory."""

    versions: dict[str, str]
    notices: list[NoticeRecord]
    bundled_libraries: list[LibraryRecord]


def verify_notice_files(directory: Path = LICENSES) -> LicenseInventory:
    """Require complete, unmodified notices and matching copies of the project licenses."""
    inventory: LicenseInventory = json.loads((directory / "inventory.json").read_text())
    for name, original in (
        ("GPL-3.0.txt", ROOT / "LICENSE"),
        ("PUZZLE-LICENSE.txt", ROOT / "sudoku/data/PUZZLE-LICENSE.txt"),
    ):
        if (directory / name).read_bytes() != original.read_bytes():
            raise ValueError(f"License copy differs from its original: {name}")
    for name in ("NOTICE.txt", "THIRD_PARTY_NOTICES.txt"):
        if not (directory / name).read_text().strip():
            raise ValueError(f"Missing license notice: {name}")
    for notice in inventory["notices"]:
        path: Path = directory / "third-party" / notice["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != notice["sha256"]:
            raise ValueError(f"Upstream license notice differs from its inventory: {path.name}")
    return inventory


def verify_python_build(expected: str) -> None:
    """Accept stable CPython patches from the baseline while requiring the reviewed notice."""
    baseline: tuple[int, ...] = tuple(int(part) for part in expected.split("."))
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:2] != baseline[:2]
        or sys.version_info[:3] < baseline
        or sys.version_info[3] != "final"
    ):
        raise ValueError(
            f"Packaging requires stable CPython {baseline[0]}.{baseline[1]}.x >= {expected}; "
            f"installed {sys.implementation.name} {sys.version.split()[0]}. "
            "See docs/licensing.md."
        )
    installed_notice: Path = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    reviewed_notice: Path = LICENSES / "third-party/Python--LICENSE.txt"
    if installed_notice.read_bytes() != reviewed_notice.read_bytes():
        raise ValueError(
            "Review and refresh the license inventory for Python: installed LICENSE.txt "
            "differs from the reviewed notice. See docs/licensing.md."
        )


def verify_build_licenses() -> None:
    """Require reviewed dependencies and notices, allowing compatible stable Python patches."""
    inventory: LicenseInventory = verify_notice_files()
    for name, expected in inventory["versions"].items():
        if name == "Python":
            verify_python_build(expected)
            continue
        actual: str = metadata.version(name)
        if actual != expected:
            raise ValueError(
                f"Review and refresh the license inventory for {name}: "
                f"expected {expected}, installed {actual}. See docs/licensing.md."
            )
    for name, package in (("opencv-python-headless", "cv2"), ("numpy", "numpy")):
        directory: Path = Path(str(metadata.distribution(name).locate_file(package))) / ".dylibs"
        expected_files: set[str] = {
            library["file"]
            for library in inventory["bundled_libraries"]
            if library["package"] == name
        }
        actual_files: set[str] = {path.name for path in directory.glob("*") if path.is_file()}
        if actual_files != expected_files:
            raise ValueError(f"Review the changed native library inventory for {name}.")
    for library in inventory["bundled_libraries"]:
        distribution: metadata.Distribution = metadata.distribution(library["package"])
        package_name: str = "cv2" if library["package"] == "opencv-python-headless" else "numpy"
        path: Path = Path(str(distribution.locate_file(package_name))) / ".dylibs" / library["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != library["sha256"]:
            raise ValueError(f"Review the changed bundled library before packaging: {path.name}")


def verify_packaged_licenses(bundle: Path) -> None:
    """Require every reviewed notice in the standalone bundle before it is archived."""
    destination: Path = bundle / "Contents/Resources/licenses"
    for original in LICENSES.rglob("*"):
        if original.is_file():
            relative: Path = original.relative_to(LICENSES)
            if (destination / relative).read_bytes() != original.read_bytes():
                raise ValueError(f"Packaged license differs from its source: {relative}")


if __name__ == "__main__":
    verify_build_licenses()
    print("License notices, Python patch policy, and reviewed dependency versions verified.")
