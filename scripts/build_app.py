# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Build a clean, standalone app without mixing old artifacts into the result."""

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from sudoku.build_paths import prepare_directory, verify_artifact_paths
from sudoku.license_checks import verify_build_licenses, verify_packaged_licenses
from sudoku.version import APP_VERSION

ROOT: Path = Path(__file__).resolve().parents[1]
MINIMUM_MACOS_VERSION: str = "15.0"


@dataclass(frozen=True)
class BuildTarget:
    """Describe one native build, preserving the host's SDK-era AppKit behavior."""

    architecture: str
    minimum_macos: str
    sdk: str
    host_macos: str


def native_build_target() -> BuildTarget:
    """Choose the interpreter architecture and host major release without cross-compiling."""
    architecture: str = platform.machine()
    host: str = platform.mac_ver()[0]
    if platform.system() != "Darwin" or architecture not in {"arm64", "x86_64"}:
        raise RuntimeError("Build Sudoku on macOS with an arm64 or x86_64 Python environment.")
    major: int = int(host.split(".")[0])
    if major < int(MINIMUM_MACOS_VERSION.split(".")[0]):
        raise RuntimeError("Building Sudoku requires macOS Sequoia 15 or newer.")
    sdk: str = subprocess.check_output(
        ["xcrun", "--sdk", "macosx", "--show-sdk-version"], text=True
    ).strip()
    if int(sdk.split(".")[0]) < major:
        raise RuntimeError(
            f"Building on macOS {major} requires macOS SDK {major} or newer; selected {sdk}. "
            "Update or select compatible Xcode or Command Line Tools."
        )
    return BuildTarget(architecture, f"{major}.0", sdk, host)


def build_launcher(destination: Path, target: BuildTarget) -> None:
    """Compile a native launcher with the selected SDK, leaving py2app untouched."""
    source: Path = Path(str(files("py2app.apptemplate").joinpath("src/main.c")))
    subprocess.run(
        [
            "xcrun",
            "--sdk",
            "macosx",
            "clang",
            "-arch",
            target.architecture,
            f"-mmacosx-version-min={target.minimum_macos}",
            str(source),
            "-o",
            str(destination),
            "-framework",
            "Cocoa",
        ],
        check=True,
    )
    verify_launcher_sdk(destination, target)


def verify_launcher_sdk(executable: Path, target: BuildTarget) -> None:
    """Require the selected SDK, architecture, and deployment target in the launcher."""
    commands: str = subprocess.check_output(
        ["xcrun", "vtool", "-show-build", str(executable)], text=True
    )
    versions: list[str] = re.findall(r"^\s*sdk\s+(\S+)", commands, re.MULTILINE)
    if versions != [target.sdk]:
        raise RuntimeError(f"Launcher SDK mismatch: expected {target.sdk}, found {versions}")
    minimum_versions: list[str] = re.findall(r"^\s*minos\s+(\S+)", commands, re.MULTILINE)
    if minimum_versions != [target.minimum_macos]:
        raise RuntimeError(
            f"Launcher minimum macOS mismatch: expected {target.minimum_macos}, "
            f"found {minimum_versions}"
        )
    architectures: list[str] = subprocess.check_output(
        ["lipo", "-archs", str(executable)], text=True
    ).split()
    if architectures != [target.architecture]:
        raise RuntimeError(f"Launcher architecture mismatch: {architectures}")


def verify_native_payload(bundle: Path, target: BuildTarget) -> None:
    """Check every Mach-O payload slice against the app's advertised native target."""
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        information: dict[str, object] = plistlib.load(stream)
    if information.get("LSMinimumSystemVersion") != target.minimum_macos:
        raise RuntimeError("Bundle minimum macOS differs from the launcher target.")
    for path in native_payload_files(bundle):
        verify_native_binary(path, target)


def native_payload_files(bundle: Path) -> list[Path]:
    """Find each actual Mach-O file once, excluding resources and duplicate symlink paths."""
    magic_numbers: set[bytes] = {
        bytes.fromhex(value)
        for value in (
            "feedface",
            "cefaedfe",
            "feedfacf",
            "cffaedfe",
            "cafebabe",
            "bebafeca",
            "cafebabf",
            "bfbafeca",
        )
    }
    native_files: set[Path] = set()
    for path in bundle.rglob("*"):
        if not path.is_file() or path.resolve() in native_files:
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in magic_numbers:
                continue
        native_files.add(path.resolve())
    return sorted(native_files)


def sign_bundle(bundle: Path) -> None:
    """Sign py2app's nested native code and frameworks before sealing the outer app."""
    executable: Path = (bundle / "Contents/MacOS/Sudoku").resolve()
    targets: set[Path] = set(native_payload_files(bundle)) - {executable}
    targets.update(path.resolve() for path in bundle.rglob("*.framework") if path.is_dir())
    # Signing the main executable also seals its app. Defer it until Python and all
    # extensions/frameworks are signed; py2app skips automatic signing on Intel.
    for path in sorted(targets, key=lambda item: (-len(item.parts), str(item))):
        sign_code(path)
    sign_code(bundle)


def sign_code(path: Path) -> None:
    """Apply a local ad-hoc signature while retaining existing code metadata."""
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            "--preserve-metadata=identifier,entitlements,flags,runtime",
            str(path),
        ],
        check=True,
    )


def verify_native_binary(path: Path, target: BuildTarget) -> None:
    """Reject missing native slices or dependencies requiring a newer macOS than advertised."""
    architectures: list[str] = subprocess.check_output(
        ["lipo", "-archs", str(path)], text=True
    ).split()
    if target.architecture not in architectures:
        raise RuntimeError(f"Missing {target.architecture} slice in {path}")
    commands: str = subprocess.check_output(
        ["otool", "-arch", target.architecture, "-l", str(path)], text=True
    )
    minimums: list[tuple[str, str]] = re.findall(
        r"cmd LC_BUILD_VERSION\b(?:(?!\nLoad command).)*?\bminos\s+(\S+)"
        r"|cmd LC_VERSION_MIN_MACOSX\b(?:(?!\nLoad command).)*?\bversion\s+(\S+)",
        commands,
        re.DOTALL,
    )
    if not minimums:
        raise RuntimeError(f"Missing macOS deployment metadata in {path}")
    for modern, legacy in minimums:
        minimum: str = modern or legacy
        if macos_version_tuple(minimum) > macos_version_tuple(target.minimum_macos):
            raise RuntimeError(
                f"{path} requires macOS {minimum}, above the app's {target.minimum_macos} target. "
                "Use a Python environment and dependencies compatible with this Mac."
            )


def macos_version_tuple(version: str) -> tuple[int, ...]:
    """Normalize omitted minor and patch numbers for deployment-target comparisons."""
    parts: list[int] = [int(part) for part in version.split(".")]
    return tuple((parts + [0, 0])[:3])


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
    """Keep only the explicit resource copy before the finished app is signed."""
    for data in bundle.glob("Contents/Resources/lib/python*/sudoku/data"):
        duplicate: Path = data / "catalog"
        if duplicate.exists():
            shutil.rmtree(duplicate)
        legacy: Path = data / "puzzles.json"
        if legacy.exists():
            legacy.unlink()


def write_build_info(bundle: Path, target: BuildTarget) -> None:
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
        "architecture": target.architecture,
        "minimum_macos": target.minimum_macos,
        "sdk_version": target.sdk,
        "build_macos": target.host_macos,
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
    target: BuildTarget = native_build_target()
    print(
        f"Building {target.architecture} for macOS {target.minimum_macos}+ with SDK {target.sdk}",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="sudoku-build-") as temporary:
        staging: Path = Path(temporary)
        launcher: Path = staging / "Sudoku-launcher"
        build_launcher(launcher, target)
        stage_catalog(staging / "catalog")
        environment: dict[str, str] = {
            **os.environ,
            "SUDOKU_BUILD_CATALOG": str(staging / "catalog"),
            "MACOSX_DEPLOYMENT_TARGET": target.minimum_macos,
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
                target.architecture,
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        bundle: Path = staging / "dist/Sudoku.app"
        executable: Path = bundle / "Contents/MacOS/Sudoku"
        shutil.copy2(launcher, executable)
        verify_launcher_sdk(executable, target)
        verify_native_payload(bundle, target)
        write_build_info(bundle, target)
        remove_duplicate_catalog(bundle)
        verify_packaged_licenses(bundle)
        sign_bundle(bundle)
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
        print(
            f"Built {output / 'Sudoku.app'} ({target.architecture}, macOS {target.minimum_macos}+)"
        )


if __name__ == "__main__":
    main()
