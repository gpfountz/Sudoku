# Older macOS support: exploration

Investigated October 21, 2026 on `codex/feature-older-macos-support`, starting
from commit `0b89f3d`. This is a feasibility assessment, not a support claim.
The first implementation step now adds guarded native control styles and an
isolated source preview; see the [testing procedure](older-macos-testing.md).
Dependency pins and standalone release requirements remain unchanged.

## Proposed scope

Use one codebase with macOS Sonoma 14 as the proposed minimum, covering Apple
Silicon and Intel. Preserve the current macOS 27 appearance and behavior. Older
systems would use native rounded controls where glass is unavailable; game
features should remain the same.

Treat operating-system support and processor support as separate tasks. An
Apple Silicon Sonoma build does not establish Intel compatibility, and an Intel
Sequoia test does not establish Sonoma compatibility.

## Findings at the initial assessment

| Area | Current evidence | Work required |
| --- | --- | --- |
| Bundle minimum | `setup.py` sets `LSMinimumSystemVersion` to `27.0`. | Share one minimum-version setting with the builder and set it to `14.0` after validation. |
| Launcher | `scripts/build_app.py` requires SDK 27+, deployment target 27, and `arm64`. | Keep the modern SDK; lower the deployment target and parameterize architecture. Update the verifier and tests. |
| Python runtime | The active Homebrew CPython 3.14.8 framework has Mach-O `minos 27.0`; its configured deployment target is also 27. | Create a separate build environment using a Python distribution whose actual binaries support Sonoma. Changing an environment variable cannot retarget an existing Python binary. |
| Glass controls | Five unguarded glass-style uses occur in `sudoku/app.py`, `sudoku/controls.py`, and `sudoku/layout.py`. | Centralize style selection and check runtime availability before using glass. Preserve the High Contrast rounded style. |
| Native dependencies | Installed PyObjC wheels are universal2; NumPy and OpenCV wheels are ARM-only. | Resolve the same pins for Intel, inspect their actual binaries, and test imports and behavior. |
| License inventory | `sudoku/license_checks.py` verifies dependency versions, Python notices, and exact native-library inventories and hashes. | Review and represent architecture-specific inventories; Intel libraries cannot be assumed to match the ARM hashes. Preserve the existing checks. |
| Automated checks | CI uses one `macos-latest` job. Native layout tests require an explicit desktop-session opt-in. Several tests require glass unconditionally. | Exercise both style paths, add architecture/OS coverage where runners are available, and retain native macOS 27 regression checks. |
| User documentation | README and development guide require macOS 27 and Apple Silicon. | Update only after the claimed configurations have been validated. |

The local SDK declares `NSBezelStyleGlass` available from macOS 26.0. It is not
intrinsically a macOS 27-only API. A compatibility helper should account for the
running OS and whether the bridge exposes a symbol; the presence of an enum
constant alone is insufficient evidence of OS support. Any newer class or
selector found during the full API audit also needs guarded access.

Keep building the modern app against SDK 27 or newer. The SDK used to build and
the oldest OS allowed to run an app are separate settings. Linking against an
older SDK can affect system presentation, so lowering the SDK is not the
proposed approach to preserving the current macOS 27 experience.

## Checks performed

- Compiled py2app's actual launcher source with SDK 27.0 and deployment target
  14.0 for both `arm64` and `x86_64`. Both compilations succeeded; `vtool` reported
  `minos 14.0` and `sdk 27.0` for each. These were temporary launcher probes,
  not complete app builds or older-OS launch tests.
- Inspected Mach-O build commands in the active Python framework and installed
  native files from PyObjC core/Cocoa/Vision/Quartz, NumPy, and OpenCV.
  PyObjC's slices declared 10.15 for Intel and 11.0 for ARM; installed NumPy
  declared 14.0; OpenCV and its bundled libraries declared versions no higher
  than 13.0. These version declarations are promising, but do not establish
  that all imported symbols and transitive libraries work on Sonoma.
- Queried PyPI release metadata for the exact pinned native dependencies.
  CPython 3.14 Intel wheels are listed for PyObjC 12.2.2 and NumPy 2.5.3;
  OpenCV headless 5.0.0.93 lists an Intel stable-ABI wheel targeting macOS 14.0.
  Intel wheel contents, installation, and runtime behavior were not tested.
- Reviewed image recognition: it uses `VNRecognizeTextRequest`, an API predating
  Sonoma, without forcing a new recognition revision. OCR results still need
  comparison on actual older systems, since the OS supplies the recognition
  implementation.

## Recommended implementation order

1. Add a small compatibility module and route all five glass uses through it.
   Keep the current macOS 27 control classes, actions, selected states, focus,
   and theme behavior. Show real fallback previews in Light, Dark, and High
   Contrast before settling on their appearance.
2. Run from source on the Intel Sequoia Mac using its own virtual environment
   and the reviewed dependency pins. Do not copy the M4 virtual environment.
   This first test can identify bridge, import, layout, and input problems
   before tackling standalone packaging.
3. Establish an older-compatible Python build environment alongside the current
   environment. Official python.org framework builds are a candidate; inspect
   the selected release's actual deployment targets and license notice.
4. Parameterize packaging for separate ARM and Intel apps using the same source
   and app version. Inspect every bundled Mach-O file and its dependencies for
   the intended architecture and minimum OS, and validate a clean extracted ZIP.
   Although the launcher cross-compiles on the M4, a complete Intel bundle also
   requires an Intel-capable Python runtime, extensions, and packaging process.
   SDK/tool availability on the Sequoia Mac must be checked before selecting
   native versus cross-architecture packaging.
5. Test Sonoma itself, then update documentation and automated coverage to match
   the configurations actually verified. A universal2 app can be considered
   later; it would require both architectures throughout the native dependency
   tree, not just a universal launcher.

## Validation targets

| Environment | Purpose | Current status |
| --- | --- | --- |
| M4, macOS 27 | Preserve current glass, theme, input, and window behavior. | Native and forced-rounded paths validated locally; detailed results are in the testing procedure. |
| Intel MacBook, Sequoia 15 | Verify Intel installation, fallback controls, OCR, and performance. | Source installation and manual follow-ups tested through OpenCore Legacy Patcher; full run reported 1,084 passes and one synthetic mouse-test failure. Targeted test repair awaits an Intel rerun. |
| Sonoma 14, Apple Silicon | Verify the proposed oldest OS on ARM. | Test environment needed. |
| Sonoma 14, Intel | Verify the proposed oldest OS on Intel. | Test environment needed if claiming this combination. |

On each claimed configuration, check launch; all themes in Light and Dark;
High Contrast; keyboard focus; Control-click/right-click; shifted candidate
entry; mode and selection controls; hints; pause/resume; undo/redo; save/reopen;
history and statistics; full screen and resizing; daily games; and clipboard
and file image imports using shared, known-answer OCR fixtures. Run native
regression tests in a desktop session. Record OS, architecture, Python,
dependency versions, and the tested commit with results.

The expected work is a focused compatibility and packaging project, not a UI
rewrite. Most uncertainty lies in the complete Python/native dependency bundle
and real older-OS behavior. Nothing found requires removing the macOS 27 path.
Public binary distribution remains a separate decision under the existing
[licensing and provenance requirements](licensing.md).

## Upstream references

- [PyObjC: distributing to older versions of macOS](https://pyobjc.readthedocs.io/en/latest/install.html#distributing-to-older-versions-of-macos)
- [Python: official macOS framework installers and universal2 support](https://docs.python.org/3.14/using/mac.html#using-python-on-macos-from-python-org)
- Exact wheel metadata checked: [NumPy 2.5.3](https://pypi.org/pypi/numpy/2.5.3/json),
  [OpenCV headless 5.0.0.93](https://pypi.org/pypi/opencv-python-headless/5.0.0.93/json),
  [PyObjC core 12.2.2](https://pypi.org/pypi/pyobjc-core/12.2.2/json).
