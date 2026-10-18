# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Validate the release launcher's stated minimum macOS version."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.build_app import main, publish_build, verify_launcher_sdk


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
    if not archive_failure:
        (staging / "Sudoku.zip").write_bytes(b"new archive")
    output: Path = tmp_path / "output"
    previous: Path = output / "Sudoku.app"
    previous.mkdir(parents=True)
    (previous / "version.txt").write_text("old app")
    (output / "Sudoku.zip").write_bytes(b"old archive")
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
    assert not list(output.glob(".sudoku-archive-*"))
