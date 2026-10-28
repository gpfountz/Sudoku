# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise bundle replacement and recovery without building or touching an installed app."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

MOCK_TOOL_SCRIPT: str = r"""#!/bin/bash
set -euo pipefail
tool="${0##*/}"
case "$tool" in
    python)
        if [[ "$1" == -m && "$2" == sudoku.build_paths ]]; then
            exec "$SUDOKU_TEST_PYTHON" "$@"
        fi
        if [[ "$1" == -m && "$2" == pip ]]; then
            [[ "$*" == '-m pip install -r requirements-dev.txt' ]]
            step=dependencies
        elif [[ "$1" == -m && "$2" == sudoku.license_checks ]]; then
            [[ "$#" == 2 ]]
            step=licenses
        else
            step=build
        fi
        ;;
    ditto)
        if [[ "$1" == -x ]]; then step=extract; else step=copy; fi
        ;;
    codesign)
        if [[ "$4" == "$SUDOKU_APPLICATIONS_DIR/Sudoku.app" ]]; then
            step=verify-installed
        elif [[ "$4" == */.sudoku-install.*/Sudoku.app ]]; then
            step=verify-staged
        else
            step=verify-extracted
        fi
        ;;
    osascript) step=quit ;;
    mv)
        if [[ "$1" == */.sudoku-install.*/Sudoku.app ]]; then
            step=replace
        elif [[ "$1" == */previous.app ]]; then
            step=restore
        else
            step=backup
        fi
        ;;
    *) exit 99 ;;
esac
printf '%s\n' "$step" >> "$SUDOKU_TEST_LOG"
if [[ "$step" == "${SUDOKU_TEST_FAILURE:-}" ]]; then exit 19; fi
case "$tool" in
    python)
        if [[ "$step" != build ]]; then exit 0; fi
        [[ "$2" == --output-dir ]]
        printf '%s\n' "$3" > "$SUDOKU_TEST_RELEASE_FILE"
        mkdir -p "$3/Sudoku.app/Contents/Resources"
        printf 'new bundle\n' > "$3/Sudoku.app/Contents/Resources/version.txt"
        touch "$3/Sudoku.zip"
        ;;
    ditto)
        if [[ "$1" == -x ]]; then
            cp -R "${3%/*}/Sudoku.app" "$4/Sudoku.app"
        else
            [[ "$1" == --norsrc ]]
            cp -R "$2" "$3"
        fi
        ;;
    codesign) test -f "$4/Contents/Resources/version.txt" ;;
    osascript) cat > /dev/null ;;
    mv) /bin/mv "$@" ;;
esac
"""


@dataclass(frozen=True)
class DeploymentCheck:
    """Keep each deployment in temporary folders with native tools replaced by test doubles."""

    script: Path
    applications: Path
    release: Path
    log: Path
    used_release: Path
    environment: dict[str, str]

    def run(self, failure: str = "") -> subprocess.CompletedProcess[str]:
        """Run from outside the project, optionally failing a particular deployment step."""
        return subprocess.run(
            [str(self.script)],
            cwd=self.applications.parent,
            env={**self.environment, "SUDOKU_TEST_FAILURE": failure},
            text=True,
            capture_output=True,
            check=False,
        )


@pytest.fixture
def deployment_check(tmp_path: Path) -> DeploymentCheck:
    """Create a checkout and installation path containing spaces without overriding HOME."""
    project: Path = tmp_path / "project with spaces"
    script: Path = project / "scripts/build_and_deploy.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts/build_and_deploy.sh", script)
    tools: Path = tmp_path / "mock tools"
    tools.mkdir()
    dispatcher: Path = tools / "dispatcher"
    dispatcher.write_text(MOCK_TOOL_SCRIPT)
    dispatcher.chmod(0o755)
    for tool in ("ditto", "codesign", "osascript", "mv"):
        (tools / tool).symlink_to(dispatcher)
    python: Path = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(dispatcher)
    applications: Path = tmp_path / "test Applications"
    resources: Path = applications / "Sudoku.app/Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "version.txt").write_text("previous bundle\n")
    (resources / "retired.txt").write_text("old resource\n")
    release: Path = tmp_path / "release output"
    log: Path = tmp_path / "steps.log"
    used_release: Path = tmp_path / "used-release.txt"
    environment: dict[str, str] = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "SUDOKU_APPLICATIONS_DIR": str(applications),
        "SUDOKU_RELEASE_DIR": str(release),
        "SUDOKU_TEST_LOG": str(log),
        "SUDOKU_TEST_RELEASE_FILE": str(used_release),
        "SUDOKU_TEST_PYTHON": sys.executable,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    return DeploymentCheck(script, applications, release, log, used_release, environment)


def test_build_and_deploy_replaces_bundle(deployment_check: DeploymentCheck) -> None:
    """Install only after verification and quitting, without retaining stale bundle resources."""
    result: subprocess.CompletedProcess[str] = deployment_check.run()
    assert result.returncode == 0, result.stderr
    resources: Path = deployment_check.applications / "Sudoku.app/Contents/Resources"
    assert (resources / "version.txt").read_text() == "new bundle\n"
    assert not (resources / "retired.txt").exists()
    assert (deployment_check.release / "Sudoku.zip").is_file()
    assert deployment_check.log.read_text().splitlines() == [
        "dependencies",
        "licenses",
        "build",
        "extract",
        "verify-extracted",
        "copy",
        "verify-staged",
        "quit",
        "backup",
        "replace",
        "verify-installed",
    ]
    assert not list(deployment_check.applications.glob(".sudoku-install.*"))
    assert str(deployment_check.applications / "Sudoku.app") in result.stdout


@pytest.mark.parametrize(
    "failure",
    [
        "dependencies",
        "licenses",
        "build",
        "extract",
        "verify-extracted",
        "copy",
        "verify-staged",
        "quit",
    ],
)
def test_failed_preparation_keeps_installed_bundle(
    deployment_check: DeploymentCheck, failure: str
) -> None:
    """Preparation failures must stop subsequent steps and leave the existing app untouched."""
    result: subprocess.CompletedProcess[str] = deployment_check.run(failure)
    assert result.returncode != 0
    resources: Path = deployment_check.applications / "Sudoku.app/Contents/Resources"
    assert (resources / "version.txt").read_text() == "previous bundle\n"
    assert (resources / "retired.txt").is_file()
    steps: list[str] = deployment_check.log.read_text().splitlines()
    assert steps[-1] == failure
    assert "backup" not in steps
    if failure in ("dependencies", "licenses"):
        assert "build" not in steps
        assert not deployment_check.used_release.exists()
    assert not list(deployment_check.applications.glob(".sudoku-install.*"))


@pytest.mark.parametrize("failure", ["replace", "verify-installed"])
def test_failed_installation_restores_previous_bundle(
    deployment_check: DeploymentCheck, failure: str
) -> None:
    """Restore the exact previous bundle if the final rename or signature check fails."""
    result: subprocess.CompletedProcess[str] = deployment_check.run(failure)
    assert result.returncode != 0
    resources: Path = deployment_check.applications / "Sudoku.app/Contents/Resources"
    assert (resources / "version.txt").read_text() == "previous bundle\n"
    assert (resources / "retired.txt").is_file()
    assert deployment_check.log.read_text().splitlines()[-1] == "restore"
    assert not list(deployment_check.applications.glob(".sudoku-install.*"))


def test_failed_backup_keeps_previous_bundle(deployment_check: DeploymentCheck) -> None:
    """Do not remove the installed app when moving it into rollback staging fails."""
    result: subprocess.CompletedProcess[str] = deployment_check.run("backup")
    assert result.returncode != 0
    resources: Path = deployment_check.applications / "Sudoku.app/Contents/Resources"
    assert (resources / "version.txt").read_text() == "previous bundle\n"
    assert (resources / "retired.txt").is_file()
    assert deployment_check.log.read_text().splitlines()[-1] == "backup"
    assert not list(deployment_check.applications.glob(".sudoku-install.*"))


def test_build_and_deploy_first_install(deployment_check: DeploymentCheck) -> None:
    """Support a first installation without requiring a previous app to back up."""
    shutil.rmtree(deployment_check.applications)
    result: subprocess.CompletedProcess[str] = deployment_check.run()
    assert result.returncode == 0, result.stderr
    assert (deployment_check.applications / "Sudoku.app/Contents/Resources/version.txt").is_file()
    steps: list[str] = deployment_check.log.read_text().splitlines()
    assert "backup" not in steps
    assert "quit" not in steps


def test_failed_first_install_removes_invalid_bundle(deployment_check: DeploymentCheck) -> None:
    """An invalid first installation must not remain as a usable-looking app."""
    shutil.rmtree(deployment_check.applications)
    result: subprocess.CompletedProcess[str] = deployment_check.run("verify-installed")
    assert result.returncode != 0
    assert not (deployment_check.applications / "Sudoku.app").exists()
    assert not list(deployment_check.applications.glob(".sudoku-install.*"))


def test_default_release_is_private_and_unique(deployment_check: DeploymentCheck) -> None:
    """Build and consume each default archive in its own retained private directory."""
    deployment_check.environment.pop("SUDOKU_RELEASE_DIR")
    directories: list[Path] = []
    try:
        for _ in range(2):
            result: subprocess.CompletedProcess[str] = deployment_check.run()
            assert result.returncode == 0, result.stderr
            directory: Path = Path(deployment_check.used_release.read_text().strip())
            directories.append(directory)
            assert directory.parent == Path("/private/tmp")
            assert directory.name.startswith("sudoku-release.")
            assert directory.stat().st_mode & 0o777 == 0o700
            assert (directory / "Sudoku.zip").is_file()
            assert str(directory / "Sudoku.zip") in result.stdout
        assert directories[0] != directories[1]
    finally:
        for directory in directories:
            shutil.rmtree(directory)


@pytest.mark.parametrize("alias", [False, True])
def test_unsafe_custom_release_stops_before_build(
    deployment_check: DeploymentCheck, alias: bool
) -> None:
    """Reject a writable precreated directory or alias before building or changing the app."""
    if alias:
        target: Path = deployment_check.release.with_name("alias target")
        target.mkdir()
        deployment_check.release.symlink_to(target, target_is_directory=True)
    else:
        deployment_check.release.mkdir()
        deployment_check.release.chmod(0o777)
    result: subprocess.CompletedProcess[str] = deployment_check.run()
    assert result.returncode != 0
    assert not deployment_check.log.exists()
    assert not deployment_check.used_release.exists()
    resources: Path = deployment_check.applications / "Sudoku.app/Contents/Resources"
    assert (resources / "version.txt").read_text() == "previous bundle\n"


def test_unsafe_installation_parent_stops_before_build(deployment_check: DeploymentCheck) -> None:
    """Apply the same directory boundary to a custom installation destination."""
    deployment_check.applications.chmod(0o777)
    result: subprocess.CompletedProcess[str] = deployment_check.run()
    assert result.returncode != 0
    assert not deployment_check.log.exists()


def test_newline_installation_path_cannot_select_stripped_sibling(
    deployment_check: DeploymentCheck,
) -> None:
    """Reject a path ending in a newline before the shell can select an unsafe sibling."""
    deployment_check.applications.chmod(0o777)
    deployment_check.environment["SUDOKU_APPLICATIONS_DIR"] = (
        str(deployment_check.applications) + "\n"
    )
    result: subprocess.CompletedProcess[str] = deployment_check.run()
    assert result.returncode != 0
    assert "newline characters" in result.stderr
    assert not deployment_check.log.exists()
    assert not deployment_check.used_release.exists()
