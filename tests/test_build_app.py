# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Validate the release launcher's stated minimum macOS version."""

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.build_app import main, publish_build, verify_launcher_sdk, write_build_info
from sudoku.version import APP_VERSION


@pytest.mark.parametrize(
    ("build_version", "message"),
    (
        ("minos 26.0\n    sdk 27.0", "minimum macOS mismatch"),
        ("minos 27.0\n    sdk 26.5", "SDK mismatch"),
    ),
)
def test_reject_launcher_with_old_sdk_or_deployment_target(
    build_version: str, message: str
) -> None:
    """Prevent an accidentally compatible-looking but older launcher from shipping."""
    with patch("scripts.build_app.subprocess.check_output", return_value=build_version):
        with pytest.raises(RuntimeError, match=message):
            verify_launcher_sdk(Path("/unused/Sudoku"), "27.0")


def test_accept_launcher_built_for_macos_27() -> None:
    """Accept the actual minimum and SDK pair required by this release."""
    with patch(
        "scripts.build_app.subprocess.check_output",
        return_value="minos 27.0\n    sdk 27.0",
    ):
        verify_launcher_sdk(Path("/unused/Sudoku"), "27.0")


def test_direct_builder_rejects_unsafe_output_before_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent direct CLI use from bypassing the shell helper's directory checks."""
    output: Path = tmp_path / "release"
    output.mkdir()
    output.chmod(0o777)
    monkeypatch.setattr("sys.argv", ["build_app.py", "--output-dir", str(output)])
    with patch("scripts.build_app.verify_build_licenses") as check_licenses:
        with pytest.raises(ValueError, match="writable by another account"):
            main()
        check_licenses.assert_not_called()


@pytest.mark.parametrize("archive_failure", [False, True])
def test_publish_build_preserves_outputs_on_archive_failure(
    tmp_path: Path, archive_failure: bool
) -> None:
    """Retain matching old outputs on archive failure and publish a complete new pair on success."""
    staging: Path = tmp_path / "staging"
    bundle: Path = staging / "dist/Sudoku.app"
    bundle.mkdir(parents=True)
    (bundle / "version.txt").write_text("new app")
    resources: Path = bundle / "Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "build-info.json").write_text('{"python_version": "3.14.8"}\n')
    if not archive_failure:
        (staging / "Sudoku.zip").write_bytes(b"new archive")
    output: Path = tmp_path / "output"
    previous: Path = output / "Sudoku.app"
    previous.mkdir(parents=True)
    (previous / "version.txt").write_text("old app")
    (output / "Sudoku.zip").write_bytes(b"old archive")
    (output / "build-info.json").write_text("old metadata")
    with patch("scripts.build_app.verify_bundle"):
        if archive_failure:
            with pytest.raises(FileNotFoundError):
                publish_build(staging, output)
        else:
            publish_build(staging, output)
    assert (output / "Sudoku.app/version.txt").read_text() == (
        "old app" if archive_failure else "new app"
    )
    assert (output / "Sudoku.zip").read_bytes() == (
        b"old archive" if archive_failure else b"new archive"
    )
    assert (output / "build-info.json").read_text() == (
        "old metadata" if archive_failure else '{"python_version": "3.14.8"}\n'
    )
    assert not list(output.glob(".sudoku-archive-*"))


@pytest.mark.parametrize("dirty", [False, True])
def test_build_info_records_actual_runtime_and_source(tmp_path: Path, dirty: bool) -> None:
    """Keep exact runtime provenance, the shared app version, and uncommitted state in the app."""
    resources: Path = tmp_path / "Sudoku.app/Contents/Resources"
    resources.mkdir(parents=True)
    commit: str = "a" * 40
    with patch(
        "scripts.build_app.subprocess.check_output",
        side_effect=[commit + "\n", " M scripts/build_app.py\n" if dirty else ""],
    ):
        write_build_info(resources.parent.parent)
    information: dict[str, Any] = json.loads((resources / "build-info.json").read_text())
    assert information["app_version"] == APP_VERSION
    assert information["python_version"] == sys.version.split()[0]
    assert information["python_implementation"] == sys.implementation.name
    assert information["git_commit"] == commit
    assert information["git_dirty"] is dirty
    timestamp: datetime = datetime.fromisoformat(information["built_at_utc"])
    assert timestamp.tzinfo == UTC


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["verify", "archive"])
def test_publication_failure_restores_matching_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool, failure: str
) -> None:
    """Restore or remove sidecar metadata if a later output operation fails."""
    staging: Path = tmp_path / "staging"
    bundle: Path = staging / "dist/Sudoku.app"
    resources: Path = bundle / "Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "build-info.json").write_text("new metadata")
    (staging / "Sudoku.zip").write_bytes(b"new archive")
    output: Path = tmp_path / "output"
    output.mkdir()
    if existing:
        (output / "Sudoku.app").mkdir()
        (output / "Sudoku.app/old.txt").write_text("old app")
        (output / "Sudoku.zip").write_bytes(b"old archive")
        (output / "build-info.json").write_text("old metadata")
    original_replace: Callable[[Path, Path], Path] = Path.replace

    def replace_unless_archive(path: Path, target: Path) -> Path:
        """Simulate an archive failure after the metadata replacement succeeds."""
        if path.name == "Sudoku.zip":
            raise OSError("Cannot replace archive")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_unless_archive)
    with patch("scripts.build_app.verify_bundle") as verify:
        if failure == "verify":
            verify.side_effect = subprocess.CalledProcessError(1, "codesign")
        with pytest.raises((OSError, subprocess.CalledProcessError)):
            publish_build(staging, output)
    if existing:
        assert (output / "Sudoku.app/old.txt").read_text() == "old app"
        assert (output / "Sudoku.zip").read_bytes() == b"old archive"
        assert (output / "build-info.json").read_text() == "old metadata"
    else:
        assert not (output / "Sudoku.app").exists()
        assert not (output / "Sudoku.zip").exists()
        assert not (output / "build-info.json").exists()
    assert not list(output.glob(".sudoku-archive-*"))
