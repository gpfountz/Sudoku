# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify offline legal resources and release checks against missing or changed notices."""

import shutil
import sys
import sysconfig
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from sudoku.legal import license_text, third_party_text
from sudoku.license_checks import (
    LICENSES,
    ROOT,
    LicenseInventory,
    verify_build_licenses,
    verify_notice_files,
    verify_packaged_licenses,
    verify_python_build,
)


def test_license_contains_author_notice_and_complete_unmodified_gpl() -> None:
    """Expose the complete root license, authorship, and warranty statement offline."""
    content: str = license_text()
    assert "Copyright (C) 2026 Greg Pfountz" in content
    assert "GPL-3.0-only" in content
    assert "WITHOUT ANY WARRANTY" in content
    assert content.endswith((ROOT / "LICENSE").read_text())


def test_upstream_notices_and_puzzle_dedication_are_preserved() -> None:
    """Retain every upstream text and its recorded provenance without relicensing it."""
    inventory: LicenseInventory = verify_notice_files()
    content: str = third_party_text()
    assert (ROOT / "sudoku/data/PUZZLE-LICENSE.txt").read_text() in content
    for notice in inventory["notices"]:
        assert (LICENSES / "third-party" / notice["file"]).read_text() in content
    assert "GPL version 3 or later" in content
    assert "https://github.com/opencv/opencv-python/issues/1260" in content


def test_standalone_app_reads_its_bundled_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read both notice views from extracted bundle resources without the source checkout."""
    bundle: Path = tmp_path / "Sudoku.app"
    resources: Path = bundle / "Contents/Resources/licenses"
    shutil.copytree(LICENSES, resources)
    expected_license: str = license_text()
    expected_third_party: str = third_party_text()
    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "Contents/MacOS/Sudoku"))
    assert license_text() == expected_license
    assert third_party_text() == expected_third_party
    verify_packaged_licenses(bundle)


@pytest.mark.parametrize(
    "filename", ["GPL-3.0.txt", "PUZZLE-LICENSE.txt", "third-party/Python--LICENSE.txt"]
)
def test_missing_packaged_notice_prevents_archiving(tmp_path: Path, filename: str) -> None:
    """Reject a bundle that would hide or omit a required license text."""
    bundle: Path = tmp_path / "Sudoku.app"
    resources: Path = bundle / "Contents/Resources/licenses"
    shutil.copytree(LICENSES, resources)
    (resources / filename).unlink()
    with pytest.raises(FileNotFoundError):
        verify_packaged_licenses(bundle)


def test_changed_packaged_notice_prevents_archiving(tmp_path: Path) -> None:
    """Reject stale or altered legal resources even when the file still exists."""
    bundle: Path = tmp_path / "Sudoku.app"
    resources: Path = bundle / "Contents/Resources/licenses"
    shutil.copytree(LICENSES, resources)
    (resources / "NOTICE.txt").write_text("Unrelated notice")
    with pytest.raises(ValueError, match="Packaged license differs"):
        verify_packaged_licenses(bundle)


def test_changed_upstream_notice_fails_its_inventory(tmp_path: Path) -> None:
    """Detect accidental edits to a third party's copyright and permission text."""
    resources: Path = tmp_path / "licenses"
    shutil.copytree(LICENSES, resources)
    (resources / "third-party/Python--LICENSE.txt").write_text("Altered notice")
    with pytest.raises(ValueError, match="Upstream license notice differs"):
        verify_notice_files(resources)


def test_dependency_version_change_requires_notice_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a dependency upgrade from silently shipping the old notice inventory."""
    inventory: LicenseInventory = {
        "versions": {"opencv-python-headless": "5.0.0.93"},
        "notices": [],
        "bundled_libraries": [],
    }
    monkeypatch.setattr("sudoku.license_checks.verify_notice_files", lambda: inventory)
    monkeypatch.setattr(metadata, "version", lambda name: "999.0")
    with pytest.raises(ValueError, match="Review and refresh.*opencv-python-headless"):
        verify_build_licenses()


@pytest.fixture
def installed_python_notice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Supply a Python installation whose notice matches the reviewed snapshot."""
    notice: Path = tmp_path / "LICENSE.txt"
    shutil.copy2(LICENSES / "third-party/Python--LICENSE.txt", notice)
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(tmp_path))
    return notice


@pytest.mark.parametrize("patch_version", [6, 8, 10, 99])
def test_accept_stable_python_patches(
    installed_python_notice: Path, monkeypatch: pytest.MonkeyPatch, patch_version: int
) -> None:
    """Allow the baseline and later stable patches, including double-digit patch numbers."""
    monkeypatch.setattr(sys, "version_info", (3, 14, patch_version, "final", 0))
    verify_python_build("3.14.6")


@pytest.mark.parametrize(
    "version",
    [
        (3, 14, 5, "final", 0),
        (3, 13, 20, "final", 0),
        (3, 15, 0, "final", 0),
        (3, 14, 9, "alpha", 1),
        (3, 14, 9, "beta", 1),
        (3, 14, 9, "candidate", 1),
    ],
)
def test_reject_unsupported_python_versions(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int, str, int]
) -> None:
    """Reject older patches, other minor releases, and prereleases before packaging."""
    monkeypatch.setattr(sys, "version_info", version)
    with pytest.raises(ValueError, match="requires stable CPython"):
        verify_python_build("3.14.6")


def test_reject_other_python_implementations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the packaging policy specific to the reviewed CPython runtime."""
    monkeypatch.setattr(sys.implementation, "name", "pypy")
    with pytest.raises(ValueError, match="requires stable CPython"):
        verify_python_build("3.14.6")


@pytest.mark.parametrize("missing", [False, True])
def test_changed_or_missing_installed_python_notice_blocks_build(
    installed_python_notice: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    """Prevent a permitted patch from silently bundling an unreviewed Python notice."""
    monkeypatch.setattr(sys, "version_info", (3, 14, 8, "final", 0))
    if missing:
        installed_python_notice.unlink()
        with pytest.raises(FileNotFoundError):
            verify_python_build("3.14.6")
    else:
        installed_python_notice.write_text("Changed upstream license")
        with pytest.raises(ValueError, match="installed LICENSE.txt differs"):
            verify_python_build("3.14.6")


@pytest.mark.parametrize("change", ["none", "version", "library", "hash"])
def test_python_patch_acceptance_preserves_dependency_guards(
    installed_python_notice: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """Continue checking dependency versions, native-library membership, and bytes after upgrade."""
    directory: Path = installed_python_notice.parent
    libraries: Path = directory / "cv2/.dylibs"
    libraries.mkdir(parents=True)
    (libraries / "native.dylib").write_bytes(b"" if change != "hash" else b"changed")
    inventory: LicenseInventory = {
        "versions": {"Python": "3.14.6", "opencv-python-headless": "5.0.0.93"},
        "notices": [],
        "bundled_libraries": [
            {
                "package": "opencv-python-headless",
                "file": "native.dylib",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            }
        ],
    }
    if change == "library":
        (libraries / "extra.dylib").write_bytes(b"extra")
    monkeypatch.setattr(sys, "version_info", (3, 14, 8, "final", 0))
    monkeypatch.setattr("sudoku.license_checks.verify_notice_files", lambda: inventory)
    monkeypatch.setattr(
        metadata, "version", lambda name: "999" if change == "version" else "5.0.0.93"
    )
    monkeypatch.setattr(
        metadata,
        "distribution",
        lambda name: metadata.PathDistribution(directory / "fake.dist-info"),
    )
    if change == "none":
        verify_build_licenses()
    else:
        with pytest.raises(ValueError, match="Review"):
            verify_build_licenses()


def test_metadata_declares_gpl_and_license_resources() -> None:
    """Keep the package's public license identifier and runtime resource rules aligned."""
    configuration: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project: dict[str, Any] = configuration["project"]
    assert project["license"] == "GPL-3.0-only"
    assert "LICENSE" in project["license-files"]
