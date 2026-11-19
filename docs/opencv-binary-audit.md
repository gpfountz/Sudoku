# OpenCV macOS binary audit

[Licensing guide](licensing.md) · [Back to the README](../README.md)

This records a dependency-release limitation, not a finding about the licensing of the
original Sudoku source code.

## Current wheel: 5.1.0.95

Reviewed locally on November 19, 2026: `opencv-python-headless==5.1.0.95`, installed on macOS
ARM64 with CPython 3.14.8. The Intel wheel was inspected statically.

- The ARM64 wheel's `cv2/.dylibs/` directory contains **16 native libraries**; the Intel wheel
  contains **19**. Their names and SHA-256 hashes are recorded per architecture in the
  [notice inventory](../sudoku/data/licenses/inventory.json).
- `otool -L cv2/cv2.abi3.so` shows direct links to the bundled FFmpeg libraries
  `libavformat.63.1.102`, `libavcodec.63.1.102`, `libswscale.10.1.102`, `libavutil.61.1.102`,
  and `libavdevice.63.1.102`.
- On ARM64, calling `avcodec_license()` in the installed library returns
  **LGPL version 2.1 or later**. `avcodec_configuration()` reports the Homebrew prefix
  `ffmpeg-lgpl/9.0.2_1` and enables only `libdav1d`, `libvpx`, `openssl`, VideoToolbox, and
  AudioToolbox, without `--enable-gpl`, `--enable-version3`, or `--enable-nonfree`.
  The Intel library's embedded license and configuration strings report the same LGPL build
  under `/usr/local/Cellar/ffmpeg-lgpl/9.0.2_1`; it was not executed.
- Both architectures also bundle OpenSSL 4.1.0 (`libssl.4`, `libcrypto.4`), libX11, libXau,
  libXdmcp, libxcb, xz (`liblzma.5`), libvpx 12, and dav1d 7. Intel adds libaom 3.14.1,
  libavif 16.4.2, and VMAF 3.
- The wheel's `LICENSE-3RD-PARTY.txt` has sections for OpenCV, FFmpeg (LGPLv2.1), libssl and
  libcrypto, libvpx, dav1d, libavif, aom, libXau, and libxcb utilities. Several are labelled as
  Linux-only components, and the OpenSSL section reproduces the legacy OpenSSL/SSLeay
  dual license, while OpenSSL 3 and later are Apache-2.0. It has no sections for libX11,
  libXdmcp, xz, or VMAF. It names macOS components, including librtmp, libsoxr, and libtasn1,
  that these wheels do not contain. That upstream text is preserved verbatim; preserving it
  does not prove it covers every embedded component.
- All 37 native `.so` and `.dylib` files in the two wheels carry only their target
  architecture, with deployment targets of macOS 15.0 or lower. This is static metadata, not
  Intel execution.

The upstream release notes for this build report "Fixed FFmpeg GPL dependencies". The
observations above independently confirm the LGPL FFmpeg configuration for the headless wheels.

## Previous wheel: 5.0.0.93

Reviewed locally on October 18, 2026, on macOS ARM64 with CPython 3.14.6. The installed wheel
contained **99 native libraries**. Its `avcodec_license()` returned **GPL version 3 or later**,
and `avcodec_configuration()` reported `--enable-version3`, `--enable-gpl`, `--enable-libx264`,
`--enable-libx265`, `--enable-librubberband`, and `--enable-libvidstab` under Homebrew's
`ffmpeg/7.1.1_3`. The wheel's notice described FFmpeg as LGPLv2.1. The same discrepancy is
described in [upstream issue #1260](https://github.com/opencv/opencv-python/issues/1260), which
remained open on November 19, 2026. That wheel is no longer selected.

## Before public binary distribution

Resolve the license, notice, matching source, and build-material obligations for the actual
native payload of each shipped architecture, or use an independently reviewed replacement
build. That includes LGPL source and relinking obligations for FFmpeg and complete notices for
the libraries absent from the upstream notice. Switching the application's license to GPLv3 is
not sufficient on its own. Top-level wheel metadata alone does not establish the licenses of all
embedded components.

The source-repository licensing work preserves available notices and checks dependency drift.
It does not claim to have completed this native-library source and license reconciliation.
