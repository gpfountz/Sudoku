# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Validate the release launcher's stated minimum macOS version."""

import json
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.build_app import (
    BuildTarget,
    build_launcher,
    main,
    native_build_target,
    prepare_launcher_source,
    publish_build,
    sign_bundle,
    verify_launcher_sdk,
    verify_native_binary,
    verify_native_payload,
    write_build_info,
)
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
            verify_launcher_sdk(
                Path("/unused/Sudoku"), BuildTarget("arm64", "27.0", "27.0", "27.0.1")
            )


def test_accept_launcher_built_for_macos_27() -> None:
    """Accept the actual minimum and SDK pair required by this release."""
    with patch(
        "scripts.build_app.subprocess.check_output",
        side_effect=["minos 27.0\n    sdk 27.0", "arm64"],
    ):
        verify_launcher_sdk(Path("/unused/Sudoku"), BuildTarget("arm64", "27.0", "27.0", "27.0.1"))


@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
@pytest.mark.parametrize(
    ("host", "sdk"), [("15.8.1", "15.5"), ("26.1", "26.2"), ("27.0.1", "27.0")]
)
def test_select_native_build_target(architecture: str, host: str, sdk: str) -> None:
    """Use one native architecture and the host's major release with its selected SDK."""
    with (
        patch("scripts.build_app.platform.system", return_value="Darwin"),
        patch("scripts.build_app.platform.machine", return_value=architecture),
        patch("scripts.build_app.platform.mac_ver", return_value=(host, (), architecture)),
        patch("scripts.build_app.subprocess.check_output", return_value=sdk),
    ):
        target: BuildTarget = native_build_target()
    assert target == BuildTarget(architecture, host.split(".")[0] + ".0", sdk, host)


@pytest.mark.parametrize(
    ("system", "architecture", "host", "sdk", "message"),
    [
        ("Linux", "x86_64", "", "", "Build Sudoku on macOS"),
        ("Darwin", "i386", "15.8.1", "15.5", "Build Sudoku on macOS"),
        ("Darwin", "x86_64", "14.8", "15.5", "Sequoia 15"),
        ("Darwin", "arm64", "27.0.1", "26.5", "SDK 27 or newer"),
    ],
)
def test_reject_incompatible_build_environment(
    system: str, architecture: str, host: str, sdk: str, message: str
) -> None:
    """Reject unsupported hosts and SDKs that would lose the host's modern AppKit behavior."""
    with (
        patch("scripts.build_app.platform.system", return_value=system),
        patch("scripts.build_app.platform.machine", return_value=architecture),
        patch("scripts.build_app.platform.mac_ver", return_value=(host, (), architecture)),
        patch("scripts.build_app.subprocess.check_output", return_value=sdk),
        pytest.raises(RuntimeError, match=message),
    ):
        native_build_target()


@pytest.mark.parametrize(
    "target",
    [
        BuildTarget("arm64", "27.0", "27.0", "27.0.1"),
        BuildTarget("x86_64", "15.0", "15.5", "15.8.1"),
    ],
)
def test_compile_native_launcher(target: BuildTarget, tmp_path: Path) -> None:
    """Pass the same architecture and deployment target to clang and launcher verification."""
    with (
        patch("scripts.build_app.subprocess.run") as run,
        patch("scripts.build_app.verify_launcher_sdk") as verify,
    ):
        build_launcher(tmp_path / "launcher", target)
    command: list[str] = run.call_args.args[0]
    assert command[command.index("-arch") + 1] == target.architecture
    assert f"-mmacosx-version-min={target.minimum_macos}" in command
    verify.assert_called_once_with(tmp_path / "launcher", target)


@pytest.mark.parametrize("change", ["signature", "duplicate"])
def test_launcher_source_drift_stops_build(tmp_path: Path, change: str) -> None:
    """Reject an unreviewed upstream error handler rather than silently misapplying its fix."""
    upstream: Path = Path(str(files("py2app.apptemplate").joinpath("src/main.c")))
    content: str = upstream.read_text(encoding="utf-8")
    if change == "signature":
        content = content.replace("py2app_openConsole(void)", "py2app_openConsole(int flags)")
    else:
        content = content.replace("USES(LSOpenFSRef);", "USES(LSOpenFSRef);\nUSES(LSOpenFSRef);")
    source: Path = tmp_path / "upstream.c"
    source.write_text(content, encoding="utf-8")
    destination: Path = tmp_path / "launcher.c"
    with pytest.raises(RuntimeError, match="Review the changed py2app launcher"):
        prepare_launcher_source(source, destination)
    assert not destination.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="Requires the macOS SDK and compiler")
@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_native_launcher_compiles_without_warnings(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], architecture: str
) -> None:
    """Compile both native slices with real SDK checks while preserving the installed source."""
    upstream: Path = Path(str(files("py2app.apptemplate").joinpath("src/main.c")))
    original: bytes = upstream.read_bytes()
    sdk: str = subprocess.check_output(
        ["xcrun", "--sdk", "macosx", "--show-sdk-version"], text=True
    ).strip()
    target: BuildTarget = BuildTarget(architecture, "15.0", sdk, "15.8.1")
    build_launcher(tmp_path / "launcher", target)
    assert capfd.readouterr().err == ""
    assert upstream.read_bytes() == original


@pytest.mark.parametrize(
    ("architectures", "commands", "message"),
    [
        ("x86_64", "cmd LC_BUILD_VERSION\n minos 14.0\n sdk 15.5", None),
        ("x86_64 arm64", "cmd LC_VERSION_MIN_MACOSX\n version 10.13\n sdk 14.0", None),
        ("arm64", "", "Missing x86_64 slice"),
        ("x86_64", "cmd LC_BUILD_VERSION\n minos 15.1\n sdk 15.5", "requires macOS 15.1"),
        ("x86_64", "cmd LC_VERSION_MIN_MACOSX\n version 26.0\n sdk 26.0", "requires macOS 26"),
        ("x86_64", "cmd LC_LOAD_DYLIB\n version 1.0", "Missing macOS deployment metadata"),
    ],
)
def test_native_dependency_compatibility(
    architectures: str, commands: str, message: str | None
) -> None:
    """Check the selected slice, including older Mach-O metadata, instead of trusting the plist."""
    target: BuildTarget = BuildTarget("x86_64", "15.0", "15.5", "15.8.1")
    with patch(
        "scripts.build_app.subprocess.check_output", side_effect=[architectures, commands]
    ) as output:
        if message:
            with pytest.raises(RuntimeError, match=message):
                verify_native_binary(Path("dependency.dylib"), target)
        else:
            verify_native_binary(Path("dependency.dylib"), target)
        if architectures == "x86_64 arm64":
            assert output.call_args.args[0][:3] == ["otool", "-arch", "x86_64"]


@pytest.mark.parametrize("plist_minimum", ["15.0", "27.0"])
def test_payload_checks_actual_native_files(tmp_path: Path, plist_minimum: str) -> None:
    """Inspect executable payloads once, skip resources, and reject a misleading app minimum."""
    contents: Path = tmp_path / "Sudoku.app/Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({"LSMinimumSystemVersion": plist_minimum}))
    binary: Path = contents / "Python"
    binary.write_bytes(bytes.fromhex("cffaedfe") + b"native payload")
    (contents / "Python-link").symlink_to(binary)
    (contents / "data.sqlite").write_bytes(b"SQLite data")
    target: BuildTarget = BuildTarget("x86_64", "15.0", "15.5", "15.8.1")
    with patch("scripts.build_app.verify_native_binary") as verify:
        if plist_minimum == "15.0":
            verify_native_payload(contents.parent, target)
            verify.assert_called_once()
            assert verify.call_args.args[0].resolve() == binary
        else:
            with pytest.raises(RuntimeError, match="Bundle minimum macOS"):
                verify_native_payload(contents.parent, target)
            verify.assert_not_called()


def test_sign_nested_code_before_outer_app(tmp_path: Path) -> None:
    """Seal Python, extensions, and framework contents before their containers and outer app."""
    bundle: Path = tmp_path / "Sudoku.app"
    framework: Path = bundle / "Contents/Frameworks/Python.framework"
    binary: Path = framework / "Versions/3.14/Python"
    helper: Path = bundle / "Contents/MacOS/python"
    extension: Path = bundle / "Contents/Resources/lib/python3.14/extension.so"
    launcher: Path = bundle / "Contents/MacOS/Sudoku"
    for path in (binary, helper, extension, launcher):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex("cffaedfe") + b"native payload")
    (framework / "Python").symlink_to(binary)
    with patch("scripts.build_app.sign_code") as sign:
        sign_bundle(bundle)
    signed: list[Path] = [call.args[0] for call in sign.call_args_list]
    assert signed.count(binary) == 1
    assert signed.index(binary) < signed.index(framework) < signed.index(bundle)
    assert signed.index(helper) < signed.index(bundle)
    assert signed.index(extension) < signed.index(bundle)
    assert signed[-1] == bundle
    assert launcher not in signed


@pytest.mark.skipif(sys.platform != "darwin", reason="Requires macOS code-signing tools")
@pytest.mark.parametrize("architecture", ["x86_64", "arm64"])
def test_sign_unsigned_python_in_actual_bundle(tmp_path: Path, architecture: str) -> None:
    """Reproduce unsigned nested Python using real Intel/ARM binaries and strict codesign."""
    bundle: Path = tmp_path / "Sudoku.app"
    contents: Path = bundle / "Contents"
    executables: Path = contents / "MacOS"
    executables.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "Sudoku",
                "CFBundleIdentifier": "com.pfountz.sudoku.signing-test",
                "CFBundlePackageType": "APPL",
            }
        )
    )
    prebuilt: Any = files("py2app.apptemplate").joinpath("prebuilt")
    for name, template in (("Sudoku", "main"), ("python", "secondary")):
        executable: Path = executables / name
        shutil.copy2(str(prebuilt.joinpath(f"{template}-{architecture}")), executable)
        subprocess.run(["codesign", "--remove-signature", str(executable)], check=True)
    unsigned: subprocess.CompletedProcess[str] = subprocess.run(
        ["codesign", "--verify", "--strict", str(executables / "python")],
        capture_output=True,
        text=True,
    )
    assert unsigned.returncode != 0
    premature: subprocess.CompletedProcess[str] = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(executables / "Sudoku")],
        capture_output=True,
        text=True,
    )
    assert premature.returncode != 0
    assert "python" in premature.stderr and "not signed at all" in premature.stderr
    sign_bundle(bundle)
    subprocess.run(["codesign", "--verify", "--strict", str(executables / "python")], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)


def test_nested_signing_failure_stops_before_outer_signature(tmp_path: Path) -> None:
    """Propagate a failed child signature instead of claiming the app is ready to archive."""
    bundle: Path = tmp_path / "Sudoku.app"
    helper: Path = bundle / "Contents/MacOS/python"
    with (
        patch("scripts.build_app.native_payload_files", return_value=[helper]),
        patch(
            "scripts.build_app.sign_code", side_effect=subprocess.CalledProcessError(1, "codesign")
        ) as sign,
        pytest.raises(subprocess.CalledProcessError),
    ):
        sign_bundle(bundle)
    sign.assert_called_once_with(helper)


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


@pytest.mark.parametrize(
    "target",
    [
        BuildTarget("arm64", "27.0", "27.0", "27.0.1"),
        BuildTarget("x86_64", "15.0", "15.5", "15.8.1"),
    ],
)
def test_builder_propagates_one_native_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: BuildTarget
) -> None:
    """Carry one native target through py2app, payload checks, and published metadata."""
    output: Path = tmp_path / "release"
    monkeypatch.setattr(sys, "argv", ["build_app.py", "--output-dir", str(output)])
    setup_calls: list[dict[str, Any]] = []

    def build_stub(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """Supply a small bundle while retaining real publication and metadata generation."""
        if "setup.py" in command:
            setup_calls.append({"command": command, "env": options["env"]})
            bundle: Path = Path(command[command.index("--dist-dir") + 1]) / "Sudoku.app"
            (bundle / "Contents/MacOS").mkdir(parents=True)
            (bundle / "Contents/Resources").mkdir()
            (bundle / "Contents/Info.plist").write_bytes(
                plistlib.dumps(
                    {"LSMinimumSystemVersion": options["env"]["MACOSX_DEPLOYMENT_TARGET"]}
                )
            )
        if command[0] == "ditto":
            Path(command[-1]).write_bytes(b"archive")
        return subprocess.CompletedProcess(command, 0)

    def compile_stub(destination: Path, selected: BuildTarget) -> None:
        """Provide a launcher and ensure its configuration matches the rest of the build."""
        assert selected == target
        destination.write_bytes(b"launcher")

    with (
        patch("scripts.build_app.native_build_target", return_value=target),
        patch("scripts.build_app.build_launcher", side_effect=compile_stub),
        patch("scripts.build_app.stage_catalog"),
        patch("scripts.build_app.verify_build_licenses"),
        patch("scripts.build_app.verify_packaged_licenses"),
        patch("scripts.build_app.verify_launcher_sdk") as launcher_check,
        patch(
            "scripts.build_app.verify_native_payload", wraps=verify_native_payload
        ) as payload_check,
        patch("scripts.build_app.verify_bundle"),
        patch("scripts.build_app.sign_bundle") as sign,
        patch("scripts.build_app.subprocess.check_output", side_effect=["a" * 40, ""]),
        patch("scripts.build_app.subprocess.run", side_effect=build_stub),
    ):
        main()
    assert len(setup_calls) == 1
    command: list[str] = setup_calls[0]["command"]
    assert command[command.index("--arch") + 1] == target.architecture
    assert setup_calls[0]["env"]["MACOSX_DEPLOYMENT_TARGET"] == target.minimum_macos
    assert launcher_check.call_args.args[1] == payload_check.call_args.args[1] == target
    sign.assert_called_once()
    information: dict[str, Any] = json.loads((output / "build-info.json").read_text())
    assert information["architecture"] == target.architecture
    assert information["minimum_macos"] == target.minimum_macos
    assert information == json.loads(
        (output / "Sudoku.app/Contents/Resources/build-info.json").read_text()
    )


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
        write_build_info(resources.parent.parent, BuildTarget("x86_64", "15.0", "15.5", "15.8.1"))
    information: dict[str, Any] = json.loads((resources / "build-info.json").read_text())
    assert information["app_version"] == APP_VERSION
    assert information["python_version"] == sys.version.split()[0]
    assert information["python_implementation"] == sys.implementation.name
    assert information["git_commit"] == commit
    assert information["git_dirty"] is dirty
    assert information["architecture"] == "x86_64"
    assert information["minimum_macos"] == "15.0"
    assert information["sdk_version"] == "15.5"
    assert information["build_macos"] == "15.8.1"
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
