# py2app launcher warning review — October 31, 2026

The two Clang deprecation warnings originate in py2app 0.28.10's native app launcher,
not Sudoku's Python code or the PyObjC 13 update. The upstream launcher declares and
dynamically loads `LSFindApplicationForInfo` and `LSOpenFSRef` to implement **Open Console**
in its startup-error dialogs. These declarations trigger the warnings while Sudoku's
builder recompiles the launcher for the current architecture and SDK.

Research during this review:

- [py2app's latest release](https://github.com/ronaldoussoren/py2app/releases/tag/v0.28.10)
  remains 0.28.10. Its [tagged launcher source](https://github.com/ronaldoussoren/py2app/blob/v0.28.10/py2app/apptemplate/src/main.c)
  still contains both legacy calls. Updating the dependency therefore does not resolve them.
- Apple's [legacy application lookup documentation](https://developer.apple.com/documentation/coreservices/1449588-lsfindapplicationforinfo)
  confirms its deprecation. The older suggested replacement,
  [LSCopyApplicationURLsForBundleIdentifier](https://developer.apple.com/documentation/coreservices/1449290-lscopyapplicationurlsforbundleid),
  is also now deprecated.
- The current SDK and Apple's [NSWorkspace application lookup documentation](https://developer.apple.com/documentation/appkit/nsworkspace/urlforapplication%28withbundleidentifier%3A%29?language=objc)
  support finding an application URL by bundle identifier. `NSWorkspace`'s `openURL:`
  method opens that URL; both methods are available throughout Sudoku's supported macOS range.

## Change

`scripts/build_app.py` prepares a private copy of the installed launcher source beside its
temporary output executable. In that copy it removes the two obsolete symbol declarations
and dynamic lookups, then changes the error dialog's Console helper to:

1. Obtain `NSWorkspace.sharedWorkspace` using the launcher's existing Objective-C bridge.
2. Find Console using `URLForApplicationWithBundleIdentifier:` and `com.apple.Console`.
3. Call `openURL:` with the returned URL, retaining a nonzero error result if lookup or
   opening fails.

The system Console application's `Info.plist` confirms this bundle identifier. Normal Python
startup, game behavior, error-dialog choices, dependency versions, and installed py2app files
are unchanged. No compiler diagnostics are disabled. The existing upstream launcher notice
continues to be included in packaged resources.

Each reviewed source fragment must occur exactly once before replacement. Missing or duplicate
fragments stop the build with a request to review the changed launcher. Revisit or remove this
adaptation when upgrading py2app; an upstream migration should not be patched blindly.

## Verification

Verified on Apple Silicon, CPython 3.14.8, macOS 27.0.1, macOS SDK 27.2:

- Added real compiler regression checks for ARM and Intel launchers targeting macOS 15.
  Both compile with empty compiler stderr and pass architecture, SDK, and minimum-OS checks.
  The tests also verify that installed upstream source bytes remain unchanged.
- Added rejection checks for changed Console-helper signatures and duplicated legacy
  declarations. The build test module passes: **42 passed**.
- A native C/Objective-C probe compiled with `-Werror=deprecated-declarations` executes
  the adapted Console helper through the real Objective-C runtime and a test workspace.
  Successful opening returns 0, a missing Console returns -10814 without opening anything,
  and a failed opening returns -10810. No actual Console application was launched.
- Full suite: **653 passed, 524 skipped** in 47.97 seconds. Native UI tests are skipped by
  this standard command; this build-only change does not alter their application code.
- Ruff lint and formatting: passed, **98 files already formatted**. Mypy: passed for
  **81 source files**. `git diff --check`: passed.
- Completed an isolated ARM app/ZIP build using the normal builder with a macOS 27.0
  deployment target and SDK 27.2. The build log contains no references to either reported
  deprecated API. Payload, license, signing, and archive checks passed; an additional
  `codesign --verify --deep --strict` check passed on the final app.
- Launched the resulting packaged app with temporary saved-data and window settings,
  observed its main window, then terminated only that test process. The startup log is empty.

The full build still emits existing `strip` warnings about invalidating input signatures;
the builder subsequently signs the nested code and final bundle and verifies the signatures.
Those warnings are separate from the two Clang warnings addressed here.

Intel validation covers launcher compilation and Mach-O metadata, not execution on an Intel
Mac. The test build remains under `/private/tmp/sudoku-launcher-warning-review/`; it was not
installed or published. Delivery is a local commit at the user's request; no push is included.
