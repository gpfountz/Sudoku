# Older macOS source support and validation

Implemented on `codex/feature-older-macos-support`, now merged into `main`.

The supported source baseline is **macOS Sequoia 15 or newer**, on Intel or Apple
Silicon. Native controls use rounded fallbacks on Sequoia and retain glass on
macOS 26 and newer. High Contrast keeps its opaque controls. The shared
`./scripts/build_and_deploy.sh` command builds for the host Mac's architecture and
macOS major version; see [Intel packaging validation](intel-packaging-review.md).
Source regression validation has passed on the tested Intel Sequoia/OCLP
setup. Sonoma 14 is untested and outside the supported range. Its possible
compatibility paths remain in the code. Sonoma validation and any expansion of
the supported range are deferred until a tester is available.

## Completed milestone

On October 22, 2026, the maintainer completed the Intel Sequoia 15.8.1/OCLP source and
packaged-app checks. The final choice-button appearance was accepted at **1.1.23 (`69567d6`)**
through `launch.py`, then confirmed after `./scripts/build_and_deploy.sh`. All other requested
manual checks had passed earlier. The latest M4 native-layout suite passed 472 tests,
and GitHub CI passed for that exact application commit. See the
[packaged-app validation record](intel-packaging-review.md#completed-validation).

No further Intel retest is required for this compatibility milestone. Earlier progress entries
and instructions below are retained as development history and future regression procedures;
their intermediate pending items are superseded by this completed result. The startup graphics
messages remain diagnostic observations without a reported functional failure. Sonoma testing
is deferred, rather than a requirement for completing Sequoia support.

Local automated validation on October 21, 2026, using the M4 on macOS 27.0.1
and CPython 3.14.8: the complete desktop-enabled suite passed **1,021 tests**.
Ruff lint and formatting, Mypy, and the dependency-license checks also passed.
The control fallback was previewed in Light, Dark, and High Contrast. The
maintainer completed hands-on local validation on October 21, 2026; this step
was the starting point for the subsequently completed Intel Sequoia checks.

## Faster visual iteration

Use the source entry point for repeated UI checks after updating the checkout:

```sh
.venv/bin/python launch.py
```

This is a valid way to check button sizing, colors, and interaction on the Intel
Sequoia Mac. It avoids rebuilding the bundle for each adjustment. Once the visual
change is accepted, run `./scripts/build_and_deploy.sh` and check the installed
app once more: bundle resources, signing, launcher/SDK behavior, and installation
still need packaged-app validation. Source launches do not replace those checks.

## Reported Sequoia progress

The Intel Haswell MacBook running macOS 15.8.1 through OpenCore Legacy Patcher
successfully installed the source package and displayed the board. This section records
the investigation leading to the completed milestone above.

The first targeted native run reported 48 passed and two failures. Both failures
were the same compact-menu assertion: its native frame measured 54 by 52 points
instead of 40 by 40. A local native regression model reproduces those dimensions
using alignment insets of 6 points vertically and 7 points horizontally. The
assertion now checks the 40-by-40 Auto Layout alignment rectangle, allowing native
decoration outside it. All 54 targeted control and compact-menu checks pass locally
with this correction. The Sequoia MacBook rerun at commit `93c562f` also passed:
**54 passed, 362 deselected in 25.75 seconds**, as reported by the maintainer.
The subsequent full desktop-enabled run at that commit reported **1,016 passed
and 9 failed in 962.59 seconds**. The failures were:

- Four OCR confidence assertions: the expected digits were recognized, but some
  required review rather than receiving the expected high confidence.
- Two image-import UI checks whose background jobs exceeded the test's original
  15-second wait. Their successful follow-up and timings are recorded below.
- One synthetic mouse-selection check for the themed Appearance dropdown.
  The maintainer confirmed that selecting Dark manually with the mouse works.
- Two active-digit menu badge checks: a hardcoded 24-point custom row enlarged
  Sequoia's 22-point native row by two points.

The follow-up at `199578f` measures the native menu row before inserting the
badge, retaining the modern row size on macOS 27. A native regression model
reproduces the shorter row. The synthetic dropdown test waits for the menu row
to appear and posts a hover followed by clicks using current event timestamps. The Sequoia rerun
reported **19 passed and 1 failed in 8.13 seconds**: the badge and other menu
checks pass, but synthetic mouse selection still fails. The reported menu row
was visible and had positive dimensions; manual mouse selection works.

The adjustment at `317010a` positions the actual pointer over the target row and
allows a tracking-loop iteration between hover and click, then restores the
pointer. The Sequoia rerun passed both keyboard and mouse selection:
**2 passed, 416 deselected in 4.34 seconds**.

The Intel OCR traces use the same Python and package versions and Vision request
revision 3 as the M4. For the bottom 8, only the compact patches were recognized,
with confidence 0.50 and 1.00; the production rule correctly requires review
because both must reach 0.85. The three thin-digit cells were read correctly as
9, 4, and 5, each with confidence about 0.30 on all three attempts. They took
about 1.72–2.20 seconds per cell, and the 8 took 2.97 seconds. These results do
not establish whether OS version, hardware, or patched graphics caused the
differences.

Recognition settings and the 0.85 review threshold remain unchanged. The tests
retain the strict no-review fixture expectations on macOS 27 and newer. On older
systems they still require every digit and blank to match exactly, while allowing
low-confidence results to require review. The image-import tests now confirm each
flagged clue using its digit button, verify Play stays disabled until all flags
are cleared, and preserve every recognized value. Separate decision tests replay
the reported 0.30 and 0.50 confidence patterns. Only the two real image-import
integration cases receive a 180-second wait per OCR phase, accommodating the
measured Intel timings; other background-job waits remain 15 seconds.

The maintainer's targeted OCR and review run at `317010a` passed on the Intel
Sequoia MacBook: **26 passed, 35 deselected in 514.68 seconds**. Reported timings:

| Case | Seconds |
| --- | ---: |
| Clipboard image-import integration | 161.40 |
| File image-import integration | 138.56 |
| Original-size thin-digit board OCR | 70.82 |
| 480-pixel thin-digit board OCR | 69.95 |
| 320-pixel thin-digit board OCR | 67.16 |
| Bottom 8 recognition | 2.88 |

Each import integration case includes loading the image, completing any automatic
recognition, explicitly selecting the original board bounds, reading that board,
and confirming all flagged clues. Its total is not a single OCR pass. These runs,
together with the earlier passing menu-badge rerun, cover all nine original
failures. The full suite has not been rerun at this revision. Remaining manual
visual and functional checks are listed below; Sonoma and older-system standalone
packaging remain unverified.

These graphics diagnostics were also reported during launch:

```text
Could not initialize cikl2metal preamble file
Can't create the cikl2metal preamble string
```

The board appeared despite these messages. Their relationship to the patched
graphics stack and any effect on themes or image recognition remain unverified;
the messages are not suppressed by this compatibility work.
Subsequent Intel probes imported AppKit, Quartz, and Vision, created the accent
filter, and rendered plain and accent-filtered 8-by-8 images without reproducing
the messages. Both renders produced images. The exact startup trigger remains
unidentified; those small checks do not establish that every graphics path works.

## Manual visual follow-up

The maintainer's manual Sequoia preview identified clipped right edges on Apply
and Show Another Hint, plus dark native button fills behind black text in Light
High Contrast. A native regression model with seven-point horizontal button
alignment margins reproduces the clipping at three window sizes. The hint action
rows now reserve those native margins inside the scroll viewport; text retains
the full panel width. Modern controls with zero margins retain their layout.

For systems using the rounded fallback, unselected action and choice buttons now
retain the native background instead of applying the High Contrast background as
a bezel tint. Selected choices keep their accent and selected text. Systems with
glass support retain the existing theme tint behavior. Local checks cover Light,
Dark, enabled and disabled buttons, each selected choice, and switching back to
Default. Active-window visual checks on the M4 covered Light and Dark using the
forced rounded fallback. These fixes still need a manual Sequoia check:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_native_layout.py -k 'hint_button_bezels or older_high_contrast'
.venv/bin/python -m scripts.run_compatibility_preview
```

Local follow-up validation on October 22, 2026, using the M4 on macOS 27.0.1:
the complete desktop-enabled suite passed **1,042 tests in 178.49 seconds**.
Ruff lint and formatting and Mypy also passed. This includes both the modern
control path and the forced fallback regressions.

The maintainer clarified that both clipboard and file imports populate most
digits but flag many for review. The screenshots show 29–31 flagged cells despite
a mathematically valid puzzle. This remains a usability and performance issue;
the earlier passing import tests establish recognition and confirmation behavior,
not an acceptable number of review flags or scan time.

The diagnostic now offers an isolated comparison of the OS's supported
[Vision algorithm revisions](https://developer.apple.com/documentation/vision/vnrecognizetextrequest).
It creates genuine requests with each revision and restores the default request
factory afterwards. App recognition settings and review thresholds are unchanged.
Compare just one known cell on the Intel MacBook:

```sh
.venv/bin/python -m scripts.diagnose_ocr --fixture thin-digits --cells 3 --compare-revisions
```

On the M4, revisions 1 and 2 reproduced low confidence on that 9 (roughly
0.30–0.50), while revision 3 returned 1.00. Separate temporary layout experiments
improved some readings but produced conflicting high-confidence 6/9 results on
the full fixture. Those experiments have not changed production OCR. The Intel
comparison has now completed: revisions 1, 2, and 3 all recognized the 9 but
reported confidence about 0.30–0.50 and required review. Total readings took
2.04, 1.64, and 1.92 seconds respectively. Switching revisions alone did not
resolve this case; these single-cell timings do not establish a general speed
advantage for any revision.

## Choice-row borders and opt-in OCR experiment

The maintainer confirmed that the High Contrast backgrounds are corrected.
Number First and Color still had clipped borders. The choice control now reserves
native bezel margins inside its own bounds, including the first button's left
edge. It recomputes those margins when a theme changes. The same margin helper
serves hint rows, avoiding separate rules for the two controls. Twelve native
regression cases cover both themes, three window sizes, every selection, and
modern and simulated legacy margins. Older-system visual confirmation remains
pending for this follow-up.

An isolated experiment tries Vision's Fast recognition level first and falls
back to the existing Accurate reader whenever the result is absent or below the
unchanged 0.85 threshold. The normal app and normal preview continue to use
Accurate recognition. Fast alone missed some 1s in five of seven real fixture
tests; adding the Accurate fallback preserved all expected digits in all seven
tests. The combined reader also preserved exact fixture values with Vision
revision 2, allowing its low-confidence results to remain flagged for review.
Small local comparisons recovered confident 9s and 4s, while some 5s still
required review. Intel performance and accuracy are not yet established.

Quit the current preview before trying the experiment on the Intel MacBook:

```sh
.venv/bin/python -m scripts.run_compatibility_preview --fast-ocr
```

Its title includes "Fast OCR Experiment" and it uses a separate preview progress
directory under `.preview-data/older-macos/`. Check the entry-order and mode button
borders, import the same image, compare every recognized digit with the source,
and report scan time, review count, and any incorrect digits. Confident Fast
results still require every repeated copy to agree; existing conflict, retry,
and review rules remain in effect.

For a smaller diagnostic using the default Vision revision:

```sh
.venv/bin/python -m scripts.diagnose_ocr --fixture thin-digits --cells 3 5 8 --fast-first
```

The JSON identifies the experimental mode. Each reported attempt includes its
Fast call and, when needed, its Accurate fallback in the same timing.

Local validation on October 22, 2026: the full desktop-enabled suite passed
**1,061 tests in 180.95 seconds** using the default app behavior. Ruff and Mypy
also passed. Separate native checks exercised all seven real OCR fixture cases
with the experimental reader and Vision revisions 2 and 3; every expected digit
was preserved, with strict no-review fixture checks retained for revision 3.

### Reported Intel experiment results

At `1dfc1b2`, the maintainer confirmed that Number First and Color have complete
borders. Clipboard recognition was reported as much faster; exact scan timings
were not provided. Both tested imports showed two cells requiring review:

| Input | Flagged cells shown in the screenshots |
| --- | --- |
| File image | Row 1, column 9: 3; row 9, column 9: 5 |
| Clipboard image | Row 1, column 9: 3; row 2, column 5: 9 |

The maintainer reported that the same clipboard import on the M4 required no
review. The source cell for the top-right 3 visibly includes a "MENU" overlay;
its role in the review decision has not been established. No thresholds or review
decisions have been relaxed based on these screenshots.

The game screenshot also showed an ellipsis in Candidates. A follow-up lets
choice rows with native bezel margins allocate width in proportion to button
content, giving longer labels more room. Zero-margin controls retain their
existing equal-width layout. Local title-area, border, layout, selection-action,
and High Contrast checks passed **42 tests in 3.86 seconds**; Ruff and Mypy also
passed. The full suite was not repeated for this title-allocation follow-up.

### Original-image investigation

The maintainer supplied the original `Untitled 2.jpg`. Local checks used its
detected board and compared every clue and blank against the visible source.
Both the normal and experimental readers preserved all 81 values with Vision
revisions 2 and 3 on the M4. Their review counts were:

| M4 algorithm | Normal reader | Fast-first experiment |
| --- | ---: | ---: |
| Vision revision 2 | 34 | 3 |
| Vision revision 3 | 0 | 0 |

The revision-2 experiment flagged the reported top-right 3 and bottom-right 5,
plus the 1 at row 8, column 8. It accepted the 9 at row 2, column 5. This provides
a local reproduction of low confidence in the actual source digits, but it does
not emulate the Intel machine or explain its separate clipboard pixels.
Single-cell traces returned confidence about 0.30 for the 3 and 0.50 for the 5,
despite correct values. Compact spacing, different text layouts, image scaling,
and retaining grayscale source edges did not reliably clear both flags. These
temporary experiments have not changed app recognition behavior.

Three lossless 100-by-100 cell fixtures retain the original board-warp pixels
for the reported 3, 9, and 5. Native regression checks require their exact digits
with both readers, and retain strict no-review expectations on the modern
baseline. The diagnostic can now trace these same source cells on either Mac:

```sh
.venv/bin/python -m scripts.diagnose_ocr --fixture source-review --fast-first
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_import_images.py -k source_review
```

The two Intel review flags remain unresolved; confirming them manually remains
necessary with the tested preview. The normal application's OCR is unchanged.
Local validation passed all **49 import-image and OCR-experiment tests in 8.52
seconds**, including the six new native source-cell cases. Ruff lint and
formatting and Mypy also passed. The new diagnostic was exercised with all three
supported local revisions; the full desktop suite was not repeated for this
fixture and diagnostic addition.

### Intel source-cell trace and bounded retry

The maintainer ran the source-review diagnostic on the Intel Sequoia MacBook
with Vision revision 3 and the Fast-first experiment. The identical file pixels
produced these results:

| Cell | Result | Seconds | Evidence |
| --- | --- | ---: | --- |
| Row 1, column 9 | 3, review required | 2.2377 | Three readings at confidence about 0.30 |
| Row 2, column 5 | 9, accepted | 0.6185 | Initial confidence about 0.30, then 1.00 for two and four copies |
| Row 9, column 9 | 5, review required | 2.5915 | Compact two-copy reading about 0.30; compact three-copy reading 1.00 |

These results reproduce the file import's two review flags. They do not explain
the separate clipboard capture's 9, whose source pixels have not been supplied.

The experimental reader now permits one extra four-copy compact reading when
the two existing compact readings agree but exactly one reaches the unchanged
0.85 confidence threshold. Review clears only when the extra reading agrees and
also reaches that threshold, providing two confident readings with different
copy counts. An absent, weak, or conflicting result retains review. Earlier
conflicting digits still block acceptance, and two weak compact readings do not
trigger extra work. Normal app recognition keeps the previous policy.

This targets the reported 5; it does not address the consistently weak 3. The
extra reading's Intel result is not yet known, so the 5 may still require review.
After updating, rerun the same short diagnostic before rescanning a full image:

```sh
git pull --ff-only
.venv/bin/python -m scripts.diagnose_ocr --fixture source-review --fast-first
```

When retrying the UI, quit and relaunch the preview with `--fast-ocr` so it uses
the updated experiment.

Local validation passed **1,079 desktop tests in 166.10 seconds**. After two
additional retry guards were added to the tests, the final affected native suite
passed **63 tests in 8.06 seconds**. The exact Intel 5 trace is replayed in unit
checks with confident, weak, absent, and conflicting extra readings. Seven real
OCR fixture cases also passed separately with the experimental reader on each
of Vision revisions 2 and 3, retaining strict modern no-review expectations.
All 81 values in the original JPEG still match with both readers and both
revisions. Ruff lint and formatting and Mypy passed.

The Intel follow-up at `11d63aa` confirmed the 5 now clears review: compact
three-copy and four-copy readings both returned 5 at confidence 1.00. Its total
time was 3.1712 seconds. The 9 remained accepted in 0.6141 seconds; the 3 still
required review at confidence about 0.30 in 2.2071 seconds. The maintainer then
reported that the full import worked, while identifying the enabled Play
button's unreadable black text on its blue background. That report does not
establish that every clue was accepted automatically.

### Import Play contrast

Play is the import window's Return-key default button and receives a native
accented background when enabled. The import's generic action styling assigned
it ordinary text. Active-window rounded-control previews reproduced black on
blue in Light High Contrast and white on yellow in Dark High Contrast.

Play now uses the theme's selected-button text while enabled and ordinary text
while disabled. Its title refreshes when clue review changes its enabled state
and when a theme is applied. Native bezel styles, accent rendering, Return-key
behavior, and the callback are preserved.

Local validation passed **29 native import-window tests in 7.69 seconds**.
The regression failed before the fix and now checks every theme in Light and
Dark, with both OS-selected and forced rounded controls, repeated enabled-state
changes, and reapplying a theme to an enabled Play button. Active-window visual
checks covered enabled and disabled Play in Default, High Contrast, and Default
Teal in both appearances. Intel visual confirmation remains pending.
All **112 theme tests** also passed, including the palette contrast checks;
Ruff lint and formatting and Mypy passed. The full desktop suite was not repeated
for this import-only styling change.

The maintainer subsequently confirmed that the enabled Play title is readable
on the Intel Sequoia Mac in the requested Light/Dark check.

### Full Sequoia regression and menu input isolation

The full desktop-enabled Intel run at `9446714` reported **1,084 passed and one
failed in 1,216.91 seconds (20 minutes 16 seconds)**. Its only failure was
`test_themed_dropdown_keeps_native_menu_selection[mouse]`: the Appearance popup
remained Light instead of selecting Dark through synthesized mouse events. The
native menu window was visible and the cursor warp reported success. The earlier
isolated rerun and manual mouse selection had passed.

Repeated menu openings also exposed test-order failures on the M4 using an
isolated copy of the unchanged committed test. Queued input from a previous menu
could affect the next programmatic opening. The test now discards leftover
keyboard/mouse events at its boundaries and exercises two keyboard/mouse pairs
in one process. Mouse hover, press, and release occur on separate tracking-loop
turns; press waits for the actual pointer to be inside the target row. Event
numbers, click counts, and pressure match the event type, and failures include
full JSON with pointer, hit-target, window, and input-phase diagnostics. Cursor
restoration, real native event dispatch, and the exact one-save assertion remain.
Application dropdown code and OCR behavior are unchanged by this test repair.

Before the repair, the repeated committed-test check stopped after **two failures
and three passes**. With input isolation, **20 native/rounded keyboard and mouse
cases passed in 9.57 seconds** in one process. The two-pair regression was then
added to the regular suite. The final M4 native-layout run passed **442 tests in
64.49 seconds**. Ruff lint and formatting and Mypy also passed. The updated Intel
check is deliberately short:

```sh
git pull --ff-only
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q \
  tests/test_native_layout.py -k themed_dropdown --tb=short
```

The maintainer's Intel rerun at `653b867` passed **4 tests, 438 deselected in
5.84 seconds**. Combined with the preceding full run, this covers its sole
failure; it is not a fresh full-suite run of the repaired revision. GitHub CI
also passed for that exact commit.

### Automatic OCR on Intel Sequoia

The validated Fast-first reader now runs automatically for x86_64 processes on
macOS 15. A confident Fast result can finish immediately; absent or weak Fast
results still fall back to Accurate. The existing 0.85 confidence threshold,
conflict guards, and compact corroboration requirement remain in place. The
extra compact retry accepts the Intel 5 only after two confident agreeing compact
readings. Both file and clipboard imports use this shared production reader.

Apple Silicon and other macOS versions retain the Accurate path. Sonoma remains
untested. The preview/diagnostic switches can force the same production policy
on another host for comparison; the scripts no longer implement a separate OCR
algorithm. Existing preview data directories remain separate, so omitting
`--fast-ocr` opens the normal compatibility preview's saved progress.

After pulling this change on the Intel Mac, quit the preview and use:

```sh
git pull --ff-only
.venv/bin/python -m scripts.diagnose_ocr --fixture source-review
.venv/bin/python -m scripts.run_compatibility_preview
```

The diagnostic should report `recognition_mode: fast-first` and
`policy_selection: automatic`. Check file and clipboard import speed, recognized
digits, and review flags against the previously validated Fast OCR preview.
No OCR flag is needed for normal operation on Intel Sequoia.

Local validation of this integration: **1,104 desktop-enabled tests passed in
175.39 seconds** on the M4. The subsequent correction to use PyObjC's native OS
version tuple passed all **42 policy/fallback tests**. All seven real OCR fixture
cases passed with Fast-first forced under each of Vision revisions 2 and 3.
The original `Untitled 2.jpg` also retained every expected clue and blank with
both readers and revisions; revision 3 needed no review on the M4. These local
algorithm comparisons do not emulate Intel hardware or Sequoia's frameworks.
Both real clipboard and file import integration cases also passed with automatic
Intel Sequoia policy selection simulated on the M4 (**2 passed in 3.20 seconds**).
Ruff lint/formatting and Mypy passed.

The maintainer confirmed automatic selection on the Intel Sequoia Mac at
`7ec9359` (1.1.13): the diagnostic reported `fast-first` and `automatic` without
an override. Its three source-cell results were:

| Cell | Digit | Review needed | Seconds |
| --- | ---: | --- | ---: |
| Row 1, column 9 | 3 | Yes | 2.3006 |
| Row 2, column 5 | 9 | No | 0.6258 |
| Row 9, column 9 | 5 | No | 3.1436 |

The 3 remained at confidence 0.30 across all three repeated layouts. The 5
cleared review after two agreeing compact readings at confidence 1.00. These
results match the prior forced-preview decisions. The maintainer also reported
that both clipboard and file imports worked, with a couple of unreadable digits
remaining; exact counts, values, and whole-board scan timings were not supplied.
GitHub CI passed for `7ec9359`.

### Full Intel regression with automatic OCR

The maintainer's full desktop-enabled run at `7ec9359` reported **1,103 passed
and one failed in 749.60 seconds (12 minutes 29 seconds)**. All OCR and import
cases passed. The only failure was the first synthetic mouse dropdown case,
`test_themed_dropdown_keeps_native_menu_selection[mouse0]`. Its pointer and hit
target checks passed, but the app was inactive, Settings was not key, and the
row was not highlighted when the events were posted.

The entire run was shorter than the preceding 1,216.91-second run, and the same
clipboard/file integration cases fell from 139.88/139.65 seconds to
38.23/36.86 seconds. These are observed test-run timings, not a controlled
benchmark of one OCR scan; each integration case includes multiple OCR phases.

The dropdown test now explicitly activates the app and waits for both active-app
and key-Settings state before opening the native menu. Normal AppKit events are
dispatched during that bounded wait. Two of its four keyboard/mouse cases first
hide and restore the test process without activation, verifying acquisition from
an inactive state. Input queue isolation, actual menu-event dispatch, cursor
restoration, and the exact one-save assertion remain in place. Application code
and OCR policy are unchanged by this repair.

The initial focused M4 check passed all four cases in 2.79 seconds; 40 repeated
native/rounded cases passed in 22.49 seconds. A controlled local comparison
omitting activation also passed 40 cases, so the Intel failure has not been
reproduced locally and focus is a diagnostic lead rather than a proven cause.
The repair makes that input precondition explicit; Intel validation remains
necessary. The full M4 native-layout file passed **442 tests in 67.25 seconds**;
Ruff lint/formatting, Mypy, and the diff whitespace check also passed. Failures
now retain the active/key state immediately before opening the menu as well as
the state during mouse tracking. Rerun the native-layout file after pulling this test repair rather
than repeating the successful OCR cases:

```sh
git pull --ff-only
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_native_layout.py --tb=short
```

### Intel focus result and native application dispatch

The Intel native-layout rerun at `2014724` reported **441 passed and one failed
in 130.15 seconds**. The same first mouse case failed even though both the app
and Settings had focus before opening and throughout the recorded gesture. This
rules out inactive focus as the cause of that failure. GitHub CI passed for
`2014724`; its local and CI results did not establish an Intel fix.

The revised mouse test dispatches its generated events immediately through
`NSApplication.sendEvent_`, which routes them to the open menu's native window
and hit-tested view. It does not call the row action or select a value directly.
The exact Dark preference and one-save assertions remain. Keyboard selection
still uses the application's native menu event queue, typing the unique initial
`d` followed by Return instead of assuming which item is initially highlighted.
Both methods wait for the target menu view to be visible, and keyboard events
now use current uptime timestamps, matching the mouse events.

The selection and cancellation timers are created only after focus setup, so
that setup cannot consume their deadlines before the menu opens. Active/key
state checks, pointer diagnostics, cursor restoration, and queue cleanup remain.
Application code and OCR policy are unchanged.

This narrows the mouse check to native application/window dispatch and preference
handling; it does not validate WindowServer mouse capture or queued mouse-event
tracking. The maintainer previously confirmed physical mouse selection works on
Intel. Keyboard queue integration and mouse application dispatch are validated
separately.

Final M4 validation of the retained application-dispatch implementation:
**40 repeated native/rounded cases passed in 22.74 seconds**, and the full
native-layout file passed **442 tests in 63.84 seconds**. Ruff lint/formatting,
Mypy, and diff whitespace checks passed. Earlier alternate harness experiments
also exposed a first-keyboard selection failure and one narrow glass-label
assertion; those experiments were discarded, the three glass-label cases passed
in isolation, and the final retained suite passed without application changes.

The maintainer's Intel rerun at **`2438e9b` (1.1.15)** passed the entire
native-layout file: **442 passed in 124.17 seconds (2 minutes 4 seconds)**.
GitHub CI also passed for that exact commit. Together with the earlier full
Intel run's 1,103 passing tests at `7ec9359`, this covers all reported automated
failures. It is not a fresh full-suite run at `2438e9b`; application logic and OCR
policy were unchanged between those revisions.

This completes the automated source-validation milestone on the tested Intel
Sequoia/OCLP configuration. Remaining hands-on checks, the unexplained startup
graphics messages and older-system standalone packaging are separate outstanding
items. Sonoma validation is deferred until a tester is available. No further Intel
regression rerun is needed for the documentation update recording this result.

## Local preview on macOS 27

From this checkout, launch either preview:

```sh
.venv/bin/python -m scripts.run_compatibility_preview
.venv/bin/python -m scripts.run_compatibility_preview --rounded-controls
```

Quit one preview before starting the other. Each uses its own progress directory
under `.preview-data/older-macos/` and its own window geometry, independently of
the installed app's player data. The rounded preview changes only control-style
availability; it does not emulate an older OS's frameworks or drawing engine.

Use Settings to compare Light, Dark, and High Contrast. Check action buttons,
the Number First/Cell First and Answers/Candidates/Color choices, and the compact
game-actions menu that appears when the window is narrow.

## Intel MacBook running Sequoia

Connect using RustDesk and open Terminal on the MacBook. Use an Intel CPython
3.14 installation and a virtual environment created on that machine. If Python
is needed, the [official macOS installer](https://docs.python.org/3.14/using/mac.html)
is a candidate. Do not copy the M4's virtual environment or application bundle.
The source preview does not require the builder's SDK 27 launcher compilation.

For a new checkout:

```sh
git clone https://github.com/gpfountz/Sudoku.git
cd Sudoku
```

For an existing, clean checkout, fetch and switch to `main` instead:

```sh
git fetch origin
git switch main
git pull --ff-only
```

Create the environment if this checkout does not already have a suitable Intel
environment, then install the same reviewed dependencies:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m scripts.versioning install
```

The source preview runs directly from this checkout; an editable installation is
optional. If you want the installed `sudoku` command or package metadata, install
the reviewed requirements first, then run:

```sh
.venv/bin/python -m pip install --no-deps -e .
```

Using `--no-deps` retains the dependency versions just installed from
`requirements-dev.txt`. That requirements file also restores its reviewed pip
version if pip was upgraded separately.

Record the tested environment and source revision:

```sh
sw_vers
uname -m
.venv/bin/python --version
git rev-parse HEAD
```

`uname -m` should report `x86_64` on this MacBook. First run the normal tests,
then the desktop tests from the logged-in graphical session:

```sh
.venv/bin/python -m pytest -q
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q
```

The desktop suite exercises the actual OS-selected controls and forced rounded
controls, along with Vision OCR fixtures. Report failures with the environment
details and full failure output; a passing suite on this MacBook establishes
evidence for Sequoia, not Sonoma.

For the current follow-up, run the affected menu tests before repeating the full
suite, then capture a small OCR trace:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_native_layout.py -k 'active_digit_badge or cell_menu or themed_dropdown'
.venv/bin/python -m scripts.diagnose_ocr
.venv/bin/python -m scripts.diagnose_ocr --fixture thin-digits
```

After collecting those traces, validate OCR and review with:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 .venv/bin/python -m pytest -q tests/test_import_images.py tests/test_import_ui.py -k 'bottom_eight or thin_digits or uncertain_cell or recognition_rechecks or compact_recognition' --durations=6
```

The real image-import cases can take several minutes on the Intel MacBook. Keep
the pointer still while running the synthetic menu test; it briefly moves and
restores the pointer to exercise native tracking.

The diagnostic prints JSON containing the OS, architecture, package versions,
Vision request revision, recognized digits, confidence, and per-attempt timings.
It uses the production recognition path and the same fixture pixels as the
failing tests without changing recognition settings or review decisions. The
default checks one 8; the thin-digit option checks three cells flagged for review
on Sequoia. Neither command scans the whole board. On the M4, the 8 required
three attempts and about 0.28 seconds, while the three thin-digit cells each took
one attempt and about 0.04–0.14 seconds. These timings exclude process startup.

Launch the source preview using automatic style selection:

```sh
.venv/bin/python -m scripts.run_compatibility_preview
```

On Sequoia this should select rounded controls automatically. Check:

- Light, Dark, and High Contrast: readable titles, visible selection, keyboard
  focus, and usable action and compact-menu buttons.
- Number First/Cell First and Answers/Candidates/Color: one selected choice,
  correct actions, and no unintended board edits.
- Answer and candidate entry, Control-click/right-click, Shift-Space/Shift-Enter,
  undo/redo, hints, and pause/resume.
- Resizing and full screen; Settings, History, Statistics, and About windows.
- Image import from file and clipboard, including review and correction.
- Daily games and save/reopen. Preview progress should persist without changing
  the installed app's progress.

For a packaged-app check after source validation, use `./scripts/build_and_deploy.sh`.
Its host-native target selection and architecture-specific license inventory checks are
already implemented; see the [packaging record](intel-packaging-review.md).
