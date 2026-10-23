# Native Intel packaging review

The shared `scripts/build_and_deploy.sh` command builds one app for the active native Python
environment. On Sequoia, the app and launcher target macOS 15.0. On macOS 27, they target 27.0,
retaining the selected modern SDK. Each build checks every packaged Mach-O binary for the
selected architecture and a minimum macOS no newer than the app advertises.

## Dependency inventory

On October 22, 2026, downloaded the pinned Intel wheels with pip's binary-only download mode,
for CPython 3.14 / `macosx_15_0_x86_64`, without installing or executing them:

| Wheel | SHA-256 |
| --- | --- |
| `numpy-2.5.3-cp314-cp314-macosx_14_0_x86_64.whl` | `54a115e5a73b8fc44f0cebef486365a1894b5c9760685d4558b72b7c3eb846e0` |
| `opencv_python_headless-5.0.0.93-cp37-abi3-macosx_14_0_x86_64.whl` | `1e55af3abfb462eeeabe5c775f12bdb36216d8a93a3583d69e6bd6e1d6ba7d00` |

All included license/notice texts matched existing checked-in notice hashes. NumPy had no
`.dylibs` payload. OpenCV contained 11 `.dylibs` files, whose names and SHA-256 hashes are recorded
under `bundled_libraries.x86_64` in `sudoku/data/licenses/inventory.json`. The existing ARM64
inventory is preserved under `bundled_libraries.arm64`; one architecture never uses the other's
hashes. Unknown architectures, changed package versions, added/removed libraries, and altered
library bytes remain build failures.

All 31 native `.so` and `.dylib` files in the two Intel wheels were inspected with `lipo` and
`otool`. Each has an `x86_64` slice and deployment metadata compatible with macOS 15.0. This
static check does not prove the complete packaged app runs; the Intel Mac's Python and other
dependencies must pass the same checks when its app is built.

The Intel OpenCV wheel's native-library membership differs from the 99-library ARM64 wheel.
The existing [ARM64 FFmpeg provenance issue](opencv-binary-audit.md) remains unresolved. This
inventory review is a dependency-drift check for local builds and does not authorize public
binary distribution or certify complete third-party licensing obligations.

## Packaged-app validation

The first Intel build reached py2app completion but failed while signing the main launcher:
`Contents/MacOS/python` was unsigned. Inspection of the pinned py2app 0.28.10 implementation
confirmed it automatically signs ARM64/universal2 apps but skips that step for `x86_64`.
The shared builder now signs nested native code and framework containers explicitly, then signs
the outer app after metadata and catalog changes. It no longer signs the main launcher early.
Regression fixtures use actual unsigned Intel and ARM executables, reproduce that premature-signing
failure, and pass strict verification after the corrected signing sequence. All 119 focused
packaging/deployment/license/path checks pass after the repair, including failure propagation
and signing-order coverage. The user confirmed the Intel build and deployment succeeded with
1.1.19 after this repair.

The M4/macOS 27.0.1 validation used the shared shell script with private output and installation
directories under `/private/tmp`, leaving the regular installed app untouched. It produced one
ARM64 app targeting 27.0 with SDK 27.0 and CPython 3.14.8. The app extracted from its ZIP passed
strict signature verification, complete native-payload checks, and packaged-notice verification.
Build, installed, and extracted apps had metadata identical to the ZIP's sidecar.

The extracted app launched and displayed the modern native controls. A separate probe using
only its bundled packages checked Default and High Contrast control styles in Light and Dark,
import-window creation, save/restore with isolated player data, and the actual source-review
3/9/5 OCR fixtures. All three digits were correct without review flags on the M4. This probe
does not replace manual clipboard/file-import and interaction checks on Intel.

The initial 115 focused packaging, deployment, path, metadata, and license tests passed, together
with Ruff lint/format, Mypy, and whitespace checks. The later signing repair increased that
focused set to 119 tests. The user subsequently confirmed that the installed Intel app passed
the requested manual checks except for selected choice-label contrast in Dark mode. The reported
checks covered About/version, appearances/themes, entry controls/dropdowns/hints, clipboard/file
import, and save/quit/relaunch. These are user-reported results from the Sequoia/OCLP MacBook.

### Selected choice labels in Sequoia Dark mode

The selected Number First/Answers labels were difficult to read on the Intel Mac, while macOS 27
looked correct. The rounded push-on/push-off cells had a styled normal title but no styled alternate
title, and retained AppKit's gray-change state flags. The compatibility path now explicitly uses
the theme's selected title for alternate contents and limits state/highlight changes to the native
background and press feedback. Glass controls keep their existing setup. Regression checks cover
all themes, both choice rows, every selection, and Light/Dark/Light transitions. The Intel visual
retry remains pending; the M4 cannot establish Sequoia's exact rendered pixels.

Local validation of this repair passed all 461 native-layout tests and 136 theme/compatibility
tests, plus lint, formatting, typing, and whitespace checks. An isolated M4 preview forced the
rounded compatibility path with Dark appearance, Number First, and Answers selected; its window
capture showed readable selected labels. The native glass path is outside this rendering change.

For the Intel handoff, run the usual command on that Mac after updating the checkout and its
development dependencies:

```sh
./scripts/build_and_deploy.sh
```

Confirm the printed target is `x86_64`, macOS `15.0+`, with the selected SDK. Launch the installed
`~/Applications/Sudoku.app` and check Light/Dark and High Contrast, entry controls, hints, file
and clipboard import, and save/quit/relaunch. Retain the printed ZIP path and `build-info.json`.
