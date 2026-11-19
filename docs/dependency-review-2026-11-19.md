# Dependency review — November 19, 2026

Reviewed the Sudoku source repository on `main`, starting at `534abef`. The working tree was
clean apart from an untracked `CLAUDE.md`, which this review leaves untouched. Scope: exact
development/packaging pins, project and build-system requirements, the full resolved Python
dependency closure, packaged notices and native-library inventory, and GitHub Actions. There
are no npm manifests, container pins, or production lockfiles. Queried official PyPI metadata
for all 25 resolved third-party distributions and upstream release endpoints during this run.

## Selected updates

| Dependency | Previous | Selected | Review |
| --- | --- | --- | --- |
| opencv-python-headless | 5.0.0.93 | 5.1.0.95 | OpenCV 5.1.0, FFmpeg 9.0.2, macOS 15 minimum, and "Fixed FFmpeg GPL dependencies". The app already targets macOS 15.0. The native payload changes substantially; see below. [Release notes](https://github.com/opencv/opencv-python/releases/tag/95), [OpenCV 5.1.0 changelog](https://github.com/opencv/opencv/wiki/OpenCV-Change-Logs#version510), [metadata](https://pypi.org/pypi/opencv-python-headless/5.1.0.95/json). |
| NumPy | 2.5.4 | 2.5.5 | Patch release with string, threading, `ufunc`, and `SeedSequence` fixes. One compatibility note: casting structured or subarray dtypes to `StringDType` now raises `TypeError`, a pattern Sudoku does not use. [Release notes](https://github.com/numpy/numpy/releases/tag/v2.5.5), [metadata](https://pypi.org/pypi/numpy/2.5.5/json). |
| pip | 26.2.2 | 26.3 | Blocks unexpected imports during installation, refuses redirects to `file:` URLs, honours supplied hashes with `--no-require-hashes`, and fixes Homebrew-Python virtual-environment configuration on macOS. [Changelog](https://github.com/pypa/pip/blob/26.3/NEWS.rst), [metadata](https://pypi.org/pypi/pip/26.3/json). |
| Ruff | 0.17.3 | 0.17.6 | Three patch releases: parser fixes for semicolon-separated statements, a BOM renderer panic fix, autofix corrections, `NO_COLOR`/`CLICOLOR` handling, and a `B008` frozen-dataclass exemption. Existing lint selection and formatting pass unchanged. [0.17.4](https://github.com/astral-sh/ruff/releases/tag/0.17.4), [0.17.5](https://github.com/astral-sh/ruff/releases/tag/0.17.5), [0.17.6](https://github.com/astral-sh/ruff/releases/tag/0.17.6). |

Unpinned transitive Mypy dependencies resolve to newer releases without manifest changes:
librt 0.16.0 → 0.17.0 and mypy-extensions 1.1.0 → 1.2.0. The source ranges and build-system
requirements in `pyproject.toml` already admit every selected version and remain unchanged.
The application version remains subject to the existing commit-time policy.

## Retained dependencies

Current registry metadata confirms the retained latest stable versions:

- PyObjC core, Cocoa, Quartz, Vision, and transitive CoreML 13.0; py2app 0.28.10; setuptools
  84.2.1; pytest 9.2.0; Mypy 2.4.1.
- Transitive packages: altgraph 0.17.5, modulegraph 0.19.7, macholib 1.16.4, packaging 26.3,
  ast-serialize 0.13.1, iniconfig 2.3.1, pathspec 1.1.1, pluggy 1.7.0, Pygments 2.21.0, and
  typing-extensions 4.16.0.
- [actions/checkout 7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) and
  [actions/setup-python 7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0)
  remain the latest releases and keep their existing commit pins.

No published stable update was deferred.

## Integrity, native payloads, and notices

Resolved and downloaded all requirements in binary-only mode for CPython 3.13 and 3.14 on
macOS 15 `arm64` and `x86_64`. Each target resolves 25 distributions. All 100 downloaded
artifacts match SHA-256 values from non-yanked version-specific PyPI metadata.

| Wheel | SHA-256 |
| --- | --- |
| `opencv_python_headless-5.1.0.95-cp37-abi3-macosx_15_0_arm64.whl` | `512f5c704eeedd0c550cf2daca42e4312f6d30bb047680f1563c661eb9ee7e82` |
| `opencv_python_headless-5.1.0.95-cp37-abi3-macosx_15_0_x86_64.whl` | `1193ffb8a60d0496dbac652f052791dc0f0da6a298e215c93d1d8c9dd67b89e9` |
| `numpy-2.5.5-cp314-cp314-macosx_14_0_arm64.whl` | `229743571f901a082f031f511dc4f926b4b4a714075d98b1ff2af62d836365ac` |
| `numpy-2.5.5-cp314-cp314-macosx_14_0_x86_64.whl` | `1c24be6a82f5f257afc4dbefde4c3b56dee02146dfed2be2811940e79576b237` |
| `pip-26.3-py3-none-any.whl` | `f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13` |
| `ruff-0.17.6-py3-none-macosx_11_0_arm64.whl` | `9fbddc08577592e283c265d865e0182de6e33db185494db7b06290d989d888e5` |
| `librt-0.17.0-cp314-cp314-macosx_11_0_arm64.whl` | `810c55c2248af580c248114e3a8529677bb27fed541fdebbdad4e37339915f08` |
| `mypy_extensions-1.2.0-py3-none-any.whl` | `993e7a20aa5671eb41a7132cf555af30062da99729601601b9a8382b11cae768` |

### OpenCV

The bundled `cv2/.dylibs/` payload drops from 99 to **16** libraries on ARM64 and changes from
11 to **19** on Intel. The inventory's per-architecture names and hashes were regenerated from
the inspected wheels. The installed ARM64 `avcodec_license()` now returns
**LGPL version 2.1 or later**. The build reports Homebrew `ffmpeg-lgpl/9.0.2_1`, without
`--enable-gpl` or `--enable-version3`. Intel strings report the same configuration. New
components include OpenSSL 4.1.0. All 37 native files in both wheels have the expected single
architecture and deployment targets of macOS 15.0 or lower. Full observations are in the
[binary audit](opencv-binary-audit.md).

`LICENSE.txt` is unchanged. `LICENSE-3RD-PARTY.txt` adds one dav1d BSD section; its new bytes
have SHA-256 `62e642873f509a614458665c9e75522545bc6120ff45bda27617958725e22ff3` and are
identical in both architecture wheels. The upstream notice still omits libX11, libXdmcp, xz,
and VMAF. Its OpenSSL section is the legacy OpenSSL/SSLeay text rather than OpenSSL 4's
Apache-2.0 license. The summary in `THIRD_PARTY_NOTICES.txt` and the
[licensing guide](licensing.md) now state these current limits. The GPL-FFmpeg discrepancy no
longer applies to the selected wheel; its history and the still-open
[upstream issue #1260](https://github.com/opencv/opencv-python/issues/1260) are retained.
`tests/test_legal.py` now requires the current LGPL observation and the
incomplete-inventory qualification in the offline notices.

### NumPy

The macOS NumPy wheels still bundle no native libraries. Of 17 inventoried notice files, only the
top-level `LICENSE.txt` changed (SHA-256
`853f260937a63b0db91c5c9ea99a5c3bbe82e88834ada124a7415502403d1600`). Upstream removed the
libquadmath section and reworded the GCC runtime entry to describe libgfortran statically
linked into OpenBLAS; both entries concern non-macOS OpenBLAS builds. The other 16 notice
files are byte-identical. Updated notice origins and the one hash from the inspected wheel.

There is no notice generator in this repository; canonical snapshots and the inventory are
maintained directly and checked by `sudoku.license_checks` and the legal tests. This review
does not clear the [standalone binary release restrictions](licensing.md#publishing-a-standalone-app).

## Validation

Local environment: Apple Silicon macOS, Homebrew CPython 3.14.8. Installed the complete
requirements file into a new isolated environment, then installed the project editable without
build isolation, using the pinned build dependencies.

- `python -m pytest -q`: **707 passed, 530 skipped** in 54.68 seconds.
- `RUN_NATIVE_LAYOUT_TESTS=1 python -m pytest -q tests/test_import_images.py
  tests/test_ocr_experiment.py`: **75 passed** in 36.85 seconds, exercising local Vision
  and OpenCV recognition with the new wheel.
- Ruff lint and format checks: passed; **105 files already formatted**.
- Mypy: passed for **86 source files**.
- `python -m pip check` and `python -m sudoku.license_checks`: passed.
- `pip-audit` 2.10.1 against the clean environment: no known vulnerabilities. The local
  `pfountz-sudoku` distribution is the sole skipped entry because it is not on PyPI. Embedded
  native libraries are outside this audit's scope.
- Built the Python package wheel. All **43 inventoried notices** are included verbatim.
- `git diff --check`: passed. No file-mode changes or deleted snapshots.

The full native desktop UI suite (`tests/test_native_layout.py`, `tests/test_import_ui.py`,
`tests/test_statistics_ui.py`) was not run, because it takes window focus. Intel and Python
3.13 checks establish resolution and artifact metadata, not execution on those targets. No
standalone app was built, installed, deployed, or published. Hosted CI is pending until these
changes are committed and pushed.
