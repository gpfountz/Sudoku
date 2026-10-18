# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Verify offline legal resources and release checks against missing or changed notices."""

import shutil
import sys
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


def test_metadata_declares_gpl_and_license_resources() -> None:
    """Keep the package's public license identifier and runtime resource rules aligned."""
    configuration: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project: dict[str, Any] = configuration["project"]
    assert project["license"] == "GPL-3.0-only"
    assert "LICENSE" in project["license-files"]
