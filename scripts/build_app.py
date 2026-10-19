# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Build a clean, standalone app without mixing old artifacts into the result."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from sudoku.build_paths import prepare_directory, verify_artifact_paths
from sudoku.license_checks import verify_build_licenses, verify_packaged_licenses
from sudoku.version import APP_VERSION

ROOT: Path = Path(__file__).resolve().parents[1]
MINIMUM_MACOS_VERSION: str = "27.0"


def build_launcher(destination: Path) -> str:
    """Compile py2app's launcher with the selected modern SDK, leaving py2app untouched."""
    sdk: str = subprocess.check_output(
        ["xcrun", "--sdk", "macosx", "--show-sdk-version"], text=True
    ).strip()
    if int(sdk.split(".")[0]) < 27:
        raise RuntimeError("Building Sudoku requires macOS SDK 27 or newer.")
    source: Path = Path(str(files("py2app.apptemplate").joinpath("src/main.c")))
    subprocess.run(
        [
            "xcrun",
            "--sdk",
            "macosx",
            "clang",
            "-arch",
            "arm64",
            f"-mmacosx-version-min={MINIMUM_MACOS_VERSION}",
            str(source),
            "-o",
            str(destination),
            "-framework",
            "Cocoa",
        ],
        check=True,
    )
    verify_launcher_sdk(destination, sdk)
    return sdk


def verify_launcher_sdk(executable: Path, expected: str) -> None:
    """Require the selected SDK and macOS 27 deployment target in the launcher."""
    commands: str = subprocess.check_output(
        ["xcrun", "vtool", "-show-build", str(executable)], text=True
    )
    versions: list[str] = re.findall(r"^\s*sdk\s+(\S+)", commands, re.MULTILINE)
    if versions != [expected]:
        raise RuntimeError(f"Launcher SDK mismatch: expected {expected}, found {versions}")
    minimum_versions: list[str] = re.findall(r"^\s*minos\s+(\S+)", commands, re.MULTILINE)
    if minimum_versions != [MINIMUM_MACOS_VERSION]:
        raise RuntimeError(
            f"Launcher minimum macOS mismatch: expected {MINIMUM_MACOS_VERSION}, "
            f"found {minimum_versions}"
        )


def verify_bundle(bundle: Path) -> None:
    """Remove signing-incompatible Finder metadata and verify generated code resources."""
    for name in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
        # Missing attributes are normal; verification catches any remaining incompatible metadata.
        subprocess.run(
            ["xattr", "-r", "-d", name, str(bundle)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)


def stage_catalog(destination: Path) -> None:
    """Copy only the published generation as standalone native app resources."""
    source: Path = ROOT / "sudoku/data/catalog"
    manifest: dict[str, object] = json.loads((source / "manifest.json").read_text())
    generation: str = str(manifest["generation"])
    if not generation.isalnum():
        raise ValueError("Invalid catalog generation")
    destination.mkdir()
    shutil.copy2(source / "manifest.json", destination / "manifest.json")
    shutil.copytree(source / generation, destination / generation)
    if len(list((destination / generation).glob("*.sqlite"))) != 6:
        raise ValueError("Prepare all six difficulty databases before building")


def remove_duplicate_catalog(bundle: Path) -> None:
    """Keep only the explicit resource copy, then renew the outer ad-hoc signature."""
    for data in bundle.glob("Contents/Resources/lib/python*/sudoku/data"):
        duplicate: Path = data / "catalog"
        if duplicate.exists():
            shutil.rmtree(duplicate)
        legacy: Path = data / "puzzles.json"
        if legacy.exists():
            legacy.unlink()
    subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)


def write_build_info(bundle: Path) -> None:
    """Record the runtime and source identity inside the bundle before it is signed."""
    commit: str = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status: str = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    information: dict[str, str | bool] = {
        "app_version": APP_VERSION,
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "git_commit": commit,
        "git_dirty": bool(status.strip()),
        "built_at_utc": datetime.now(UTC).isoformat(),
    }
    destination: Path = bundle / "Contents/Resources/build-info.json"
    destination.write_text(json.dumps(information, indent=2) + "\n", encoding="utf-8")


def publish_build(staging: Path, output: Path) -> None:
    """Publish the app, archive, and matching metadata, restoring previous outputs on failure."""
    output = prepare_directory(output)
    verify_artifact_paths(output)
    destination: Path = output / "Sudoku.app"
    previous: Path = staging / "previous.app"
    sidecars: tuple[str, ...] = ("build-info.json", "Sudoku.zip")
    replaced: list[str] = []
    # Prepare files and backups on the output filesystem before changing any outputs.
    with tempfile.TemporaryDirectory(prefix=".sudoku-archive-", dir=output) as temporary:
        prepared: Path = Path(temporary)
        shutil.copy2(staging / "Sudoku.zip", prepared / "Sudoku.zip")
        shutil.copy2(
            staging / "dist/Sudoku.app/Contents/Resources/build-info.json",
            prepared / "build-info.json",
        )
        for name in sidecars:
            if (output / name).exists():
                shutil.copy2(output / name, prepared / (name + ".previous"))
        if destination.exists():
            shutil.move(str(destination), previous)
        try:
            shutil.move(str(staging / "dist/Sudoku.app"), destination)
            verify_bundle(destination)
            for name in sidecars:
                (prepared / name).replace(output / name)
                replaced.append(name)
        except (OSError, subprocess.CalledProcessError):
            for name in reversed(replaced):
                backup: Path = prepared / (name + ".previous")
                if backup.exists():
                    backup.replace(output / name)
                else:
                    (output / name).unlink()
            if destination.exists():
                shutil.move(str(destination), staging / "failed.app")
            if previous.exists():
                shutil.move(str(previous), destination)
            raise


def main() -> None:
    """Build in temporary directories and replace the prior bundle only after success."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Output folder; choose a local, unsynced folder to avoid Finder metadata changes.",
    )
    arguments: argparse.Namespace = parser.parse_args()
    output: Path = prepare_directory(arguments.output_dir)
    verify_artifact_paths(output)
    verify_build_licenses()
    with tempfile.TemporaryDirectory(prefix="sudoku-build-") as temporary:
        staging: Path = Path(temporary)
        launcher: Path = staging / "Sudoku-launcher"
        sdk: str = build_launcher(launcher)
        stage_catalog(staging / "catalog")
        environment: dict[str, str] = {
            **os.environ,
            "SUDOKU_BUILD_CATALOG": str(staging / "catalog"),
        }
        subprocess.run(
            [
                sys.executable,
                "setup.py",
                "py2app",
                "--bdist-base",
                str(staging / "build"),
                "--dist-dir",
                str(staging / "dist"),
                "--arch",
                "arm64",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        bundle: Path = staging / "dist/Sudoku.app"
        executable: Path = bundle / "Contents/MacOS/Sudoku"
        shutil.copy2(launcher, executable)
        subprocess.run(["codesign", "--force", "--sign", "-", str(executable)], check=True)
        verify_launcher_sdk(executable, sdk)
        write_build_info(bundle)
        remove_duplicate_catalog(bundle)
        verify_packaged_licenses(bundle)
        verify_bundle(bundle)
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--keepParent",
                "--norsrc",
                str(staging / "dist/Sudoku.app"),
                str(staging / "Sudoku.zip"),
            ],
            check=True,
        )
        publish_build(staging, output)
        print(f"Built {output / 'Sudoku.app'} with macOS SDK {sdk}")


if __name__ == "__main__":
    main()
