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
from importlib.resources import files
from pathlib import Path

from sudoku.build_paths import prepare_directory, verify_artifact_paths
from sudoku.license_checks import verify_build_licenses, verify_packaged_licenses

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


def publish_build(staging: Path, output: Path) -> None:
    """Replace output from trusted staging, restoring the previous app on publication failure."""
    output = prepare_directory(output)
    verify_artifact_paths(output)
    destination: Path = output / "Sudoku.app"
    previous: Path = staging / "previous.app"
    if destination.exists():
        shutil.move(str(destination), previous)
    try:
        shutil.move(str(staging / "dist/Sudoku.app"), destination)
        verify_bundle(destination)
        # Copy on the output filesystem before an atomic rename. This supports
        # other volumes and never follows an existing archive symlink.
        with tempfile.TemporaryDirectory(prefix=".sudoku-archive-", dir=output) as temporary:
            archive: Path = Path(temporary) / "Sudoku.zip"
            shutil.copy2(staging / "Sudoku.zip", archive)
            archive.replace(output / "Sudoku.zip")
    except (OSError, subprocess.CalledProcessError):
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
