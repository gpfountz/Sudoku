# OpenCV macOS binary audit

[Licensing guide](licensing.md) · [Back to the README](../README.md)

Reviewed locally on October 18, 2026: installed `opencv-python-headless==5.0.0.93`,
macOS ARM64, CPython 3.14.6. This records a dependency-release limitation, not a finding
about the licensing of the original Sudoku source code.

## Observations

- The installed `cv2/.dylibs/` directory contains **99 native libraries**. Their names and
  SHA-256 hashes are recorded in the [notice inventory](../sudoku/data/licenses/inventory.json).
- `otool -L cv2/cv2.abi3.so` shows direct links to bundled FFmpeg libraries, including
  `libavcodec.61.19.101.dylib` and `libavformat.61.7.100.dylib`.
- Calling `avcodec_license()` in that installed library returns **GPL version 3 or later**.
- Calling `avcodec_configuration()` reports `--enable-version3`, `--enable-gpl`,
  `--enable-libx264`, `--enable-libx265`, `--enable-librubberband`, and `--enable-libvidstab`,
  among other enabled components. The recorded prefix is Homebrew's `ffmpeg/7.1.1_3`.
- The wheel's `LICENSE-3RD-PARTY.txt` describes FFmpeg as LGPLv2.1. That upstream text is
  preserved verbatim; preserving it does not resolve the discrepancy or prove it covers
  every embedded component.

The same platform/version discrepancy is described in
[upstream issue #1260](https://github.com/opencv/opencv-python/issues/1260), where a maintainer
attributes it to the Homebrew packages used by the wheel build. The report concerns
`opencv-python`; the observations above independently check the installed **headless** wheel.

## Before public binary distribution

Resolve the license, notice, matching source, and build-material obligations for the actual
99-library payload, or use an independently reviewed replacement build. Switching the
application's license to GPLv3 is not sufficient on its own. An inference that all embedded
components are LGPL, based solely on the wheel's top-level metadata, is not supported.

The source-repository licensing work preserves available notices and checks dependency drift.
It does not claim to have completed this native-library source and license reconciliation.
