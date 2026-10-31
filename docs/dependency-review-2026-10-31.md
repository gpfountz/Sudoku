# Dependency review — October 31, 2026

Reviewed the Sudoku source repository on `main`, starting at `e41a982`, with a clean working
tree. Scope: exact development/packaging pins, project and build-system requirements, the full
resolved Python dependency closure, packaged notices, and GitHub Actions. There are no npm
manifests, container pins, or production lockfiles. Queried official PyPI metadata for all 25
installed third-party distributions and upstream GitHub release/tag endpoints during this run.

## Selected updates

| Dependency | Previous | Selected | Review |
| --- | --- | --- | --- |
| PyObjC core, Cocoa, Quartz, Vision, and transitive CoreML | 12.2.2 | 13.0 | macOS 27 SDK bindings and bridge/callback/reference-count fixes, including `NSData.bytes`. Python 3.11 minimum fits Sudoku's Python 3.13 minimum. [Tagged migration notes](https://github.com/ronaldoussoren/pyobjc/blob/v13.0/docs/changelog.rst), [core metadata](https://pypi.org/pypi/pyobjc-core/13.0/json). |
| pytest | 9.1.1 | 9.2.0 | Test discovery, fixture, and error-reporting improvements. Reviewed the new configuration-path errors, keyword-only parametrization arguments, plugin error codes, and deprecations; the existing suite needs no changes. [Changelog](https://docs.pytest.org/en/stable/changelog.html#pytest-9-2-0-2026-10-27), [metadata](https://pypi.org/pypi/pytest/9.2.0/json). |
| Ruff | 0.17.2 | 0.17.3 | Fixes incorrect `UP032` f-string conversions and improves parser/formatter performance. Existing lint selection and formatting pass unchanged. [Release notes](https://github.com/astral-sh/ruff/releases/tag/0.17.3), [metadata](https://pypi.org/pypi/ruff/0.17.3/json). |
| Mypy | 2.4.0 | 2.4.1 | Corrects overload processing during two-phase type checking and mypyc nested-function handling. The dependency closure is unchanged. [Patch notes](https://github.com/python/mypy/blob/v2.4.1/CHANGELOG.md#mypy-241), [metadata](https://pypi.org/pypi/mypy/2.4.1/json). |

The source ranges and build-system requirements in `pyproject.toml` already admit the selected
versions. They remain unchanged. Exact packaging requirements and license inventory versions
move together. The application version remains subject to the existing commit-time policy.

### PyObjC major-version review

Reviewed the tagged 13.0 changelog against application and test call sites. Sudoku does not
construct `objc.native_selector`, inspect bound-selector flavors, use the removed APIs, or
override the changed Bezier-path method. Its bridge calls do not rely on the affected keyword
arguments. Existing subclass/delegate, control, drawing, image decoding, and Vision tests
exercise the relevant bridge behavior; no application migration or test relaxation was needed.

PyPI lists 13.0 as the latest stable release for all five used PyObjC distributions. The live
documentation also discusses 13.0.1 and 12.2.3; neither has a published release artifact for
these packages at review time. They were not selected from documentation alone.

## Retained dependencies

Current registry metadata confirms the retained latest stable versions:

- NumPy 2.5.4; opencv-python-headless 5.0.0.93; py2app 0.28.10; setuptools 84.2.1; pip 26.2.2.
- Transitive packages: altgraph 0.17.5, modulegraph 0.19.7, macholib 1.16.4, packaging 26.3,
  ast-serialize 0.13.1, iniconfig 2.3.1, librt 0.16.0, mypy-extensions 1.1.0, pathspec 1.1.1,
  pluggy 1.7.0, Pygments 2.21.0, and typing-extensions 4.16.0.
- [actions/checkout 7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1), still at
  `3d3c42e5aac5ba805825da76410c181273ba90b1`.
- [actions/setup-python 7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0), still
  at `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`.

Official action release tags resolve directly to the existing commit pins. No workflow,
runner, permissions, or cache change is needed. No published stable update was deferred.
Installing a newer CPython interpreter is outside this dependency-manifest refresh.

## Integrity, native payloads, and notices

Resolved and downloaded all requirements in binary-only mode for CPython 3.13 and 3.14 on
`macosx_15_0_arm64` and `macosx_15_0_x86_64`. Each target resolves 25 distributions. All 100
downloaded artifacts match SHA-256 values from non-yanked version-specific PyPI metadata.
The native parser dependencies retain Intel wheels; Mypy uses its pure-Python wheel on Intel.

The changed CPython 3.14 artifacts used on the development Mac are:

| Wheel | SHA-256 |
| --- | --- |
| `pyobjc_core-13.0-cp314-cp314-macosx_10_15_universal2.whl` | `fe470bd7b8163b4b8d216b1ebe5b227f01c0fa1c4e0085d7ccade269dec02bb0` |
| `pyobjc_framework_cocoa-13.0-cp314-cp314-macosx_10_15_universal2.whl` | `88be6d452e7531f695ce6d41428aa74bcaade9ddbc50af592419b9f2fbb7c879` |
| `pyobjc_framework_coreml-13.0-cp314-cp314-macosx_10_15_universal2.whl` | `de28b771adc331f875bd755b0873a95895fe668eb22b9215a3bb71747f77c445` |
| `pyobjc_framework_quartz-13.0-cp314-cp314-macosx_10_15_universal2.whl` | `ea179def24ffbdd61e43e7c33a0cb2b2d79c7cb39fa8d212ab87c964702e5f87` |
| `pyobjc_framework_vision-13.0-cp314-cp314-macosx_10_15_universal2.whl` | `cef65bfbb399fcebb755ee79f6ec3aab78c925292073ae8daf4244bdd85ed938` |
| `pytest-9.2.0-py3-none-any.whl` | `07acdcf88ec174f907dc01af70bf52d49b014bbab03faeeade31c96b18c2e588` |
| `ruff-0.17.3-py3-none-macosx_11_0_arm64.whl` | `b75cc113b3aca388933d8296b667b1ac401a80317ea3074c9b0a66541199da29` |
| `mypy-2.4.1-cp314-cp314-macosx_11_0_arm64.whl` | `c45485061ba08f700acc12cfc8b177e6997e6bc353605babfc0abb081e079456` |

For each reviewed Python minor, the 19 PyObjC runtime extensions pass the builder's `lipo` and
`otool` checks for both architectures and the macOS 15 deployment target. Test extensions and
debug-symbol files are excluded from this runtime check. These wheels add no bundled dylibs.
This establishes binary architecture/deployment metadata compatibility, not Intel execution.

Cocoa and Quartz wheel license bytes match existing MIT snapshots for both Python minors.
Core, Vision, and CoreML wheels omit license files; their tagged upstream 13.0 `License.txt`
files match the same MIT text, SHA-256
`0ca04b07928d4872b9d9bb22187ca0426dd8bfab08f26eada0999a71dc81aaff`.
Updated existing notice origins without changing their hashes, added the previously missing
CoreML upstream notice and exact inventory version, and refreshed the third-party summary.
There is no notice generator in this repository; canonical snapshots/inventory are maintained
directly and checked by `sudoku.license_checks` and existing legal tests.

pytest, Ruff, and Mypy retain MIT licensing and identical notice text to their previous wheels,
including Mypy's typeshed notice. They remain development tools outside the app notice inventory.
The existing NumPy/OpenCV artifacts, native-library hashes, and OpenCV/FFmpeg provenance
qualification remain unchanged. This review does not clear the
[standalone binary release restrictions](licensing.md#publishing-a-standalone-app).

## Validation and delivery

Local environment: Apple Silicon macOS 27.0.1, CPython 3.14.8. Installed the complete requirements
file into a new isolated environment, then installed the project through its editable backend
with the selected build dependencies and without isolated backend substitution.

- Standard suite, `python -m pytest -q`: **649 passed, 524 skipped** in 55.79 seconds.
- Ruff lint and format checks: passed in the clean and working environments; the final
  check reported **98 files already formatted**. No source reformatting was required.
- Mypy: passed for **81 source files**, with both accelerated ARM and pure-Python wheels.
- Clean-environment `python -m pip check` and `python -m sudoku.license_checks`: passed.
- `pip-audit` 2.10.1 against the clean environment: **25 third-party dependencies audited,
  zero known vulnerabilities**. The local `pfountz-sudoku` distribution is the sole skipped
  entry because it is not on PyPI. Embedded native libraries are outside this audit's scope.
- Built the Python package wheel using the selected backend. All **43 inventoried notices**
  are included verbatim, including the new CoreML notice.

- Refreshed the working `.venv` from `requirements-dev.txt` and its editable project metadata.
  All **12 exact direct pins**, transitive CoreML 13.0, and project version 1.1.28 match.
  Working-environment dependency, license, lint, formatting, and typing checks pass.
- Workflow YAML parsed successfully; its existing action commit pins were verified upstream.
- Final `git diff --check`: passed. No tracked file-mode changes or deleted snapshots.

The native desktop command was:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 <clean-environment>/bin/python -m pytest -q \
  tests/test_native_layout.py tests/test_import_images.py \
  tests/test_import_ui.py tests/test_statistics_ui.py
```

The first desktop run completed with **561 passed, 4 failed** in 131.08 seconds. Three failures
were keyboard/mouse variants of `test_themed_dropdown_keeps_native_menu_selection`; the fourth
was the Light/active variant of `test_new_game_level_menu_keeps_default_action`. All failed
while waiting for application/window activation, before menu interactions. Running both test
groups with the original PyObjC 12.2.2/pytest 9.1.1 environment produced **8 passed,
469 deselected** in 7.26 seconds. A complete rerun of the command above with the updated
dependencies then produced **565 passed** in 85.85 seconds. No test assertions, gates, or
application code were changed. The initial focus failures were not reproduced on rerun.

Intel and Python 3.13 checks establish resolution and artifact availability/metadata, not
execution on those targets. No standalone app was built, installed, deployed, or published.
Delivery is a local commit at the user's request. Hosted CI remains pending because
these changes have not been pushed.
