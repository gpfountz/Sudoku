# Dependency review — October 26, 2026

Reviewed the source repository on `main`, starting at `e88af8d`, with a clean working tree.
The scope includes `requirements-dev.txt`, the ranges and build backend in `pyproject.toml`,
the complete resolved Python dependency closure, packaged notices, and both CI actions.
There are no npm manifests, container pins, or production lockfiles in this repository.
The existing source dependency ranges remain compatible with the selected exact development
and packaging pins; this refresh does not narrow the supported source Python range.

## Selected updates

| Dependency | Previous | Selected | Review |
| --- | --- | --- | --- |
| NumPy | 2.5.3 | 2.5.4 | Patch fixes for typing, crashes, memory management, and non-finite linear algebra inputs. Supports Python 3.12–3.15. [Release notes](https://github.com/numpy/numpy/releases/tag/v2.5.4), [PyPI metadata](https://pypi.org/pypi/numpy/2.5.4/json). |
| setuptools | 84.0.0 | 84.2.1 | Includes archive extraction and namespace path validation fixes from 84.1, vendored packaging 26.3, and stable ABI fixes. No application migration required. [History](https://setuptools.pypa.io/en/stable/history.html#v84-2-1), [PyPI metadata](https://pypi.org/pypi/setuptools/84.2.1/json). |
| pip | 26.2.1 | 26.2.2 | Refreshes the vendored certifi certificate bundle. [Changelog](https://pip.pypa.io/en/stable/news/#v26-2-2), [PyPI metadata](https://pypi.org/pypi/pip/26.2.2/json). |
| Ruff | 0.16.7 | 0.17.2 | Reviewed intervening 0.16.8–0.17.2 releases, including the 0.17 breaking changes. Explicit `py313` and rule configuration remain valid; existing sources pass without reformatting or rule suppression. macOS executables are now signed and notarized upstream. [0.17.0 notes](https://github.com/astral-sh/ruff/releases/tag/0.17.0), [0.17.2 notes](https://github.com/astral-sh/ruff/releases/tag/0.17.2), [PyPI metadata](https://pypi.org/pypi/ruff/0.17.2/json). |
| Mypy | 2.3.1 | 2.4.0 | Enables its native parser by default. Checked the complete project with both the accelerated ARM wheel and the pure-Python wheel used on Intel. [Changelog](https://github.com/python/mypy/blob/v2.4.0/CHANGELOG.md), [PyPI metadata](https://pypi.org/pypi/mypy/2.4.0/json). |
| actions/setup-python | 7.0.0 | 7.1.0 | Adds optional mirror inputs and updates dependencies/cache support. Existing Python 3.14 and pip cache inputs remain valid; Node 24 is unchanged. [Release notes](https://github.com/actions/setup-python/releases/tag/v7.1.0). |

Both actions now use full commit pins resolved from official release tags:

- `actions/checkout` remains at 7.0.1: `3d3c42e5aac5ba805825da76410c181273ba90b1`.
- `actions/setup-python` 7.1.0: `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`.

The hosted runner, workflow permissions, and verification steps are unchanged.

## Dependencies retained

Current PyPI metadata confirms these are already the latest stable, non-yanked releases:

- PyObjC core, Cocoa, Quartz, Vision, and transitive CoreML: 12.2.2.
- opencv-python-headless: 5.0.0.93; py2app: 0.28.10; pytest: 9.1.1.
- The resolved transitive packages also match current stable releases: altgraph 0.17.5,
  modulegraph 0.19.7, macholib 1.16.4, packaging 26.3, ast-serialize 0.13.1,
  iniconfig 2.3.1, librt 0.16.0, mypy-extensions 1.1.0, pathspec 1.1.1,
  pluggy 1.7.0, Pygments 2.21.0, and typing-extensions 4.16.0.

No stable dependency update was deferred. CPython interpreter installation is outside this
manifest refresh; local checks use CPython 3.14.8. The existing packaging policy still accepts
stable CPython 3.14 patches from 3.14.6 with matching Python notices.

## Integrity, native payloads, and notices

Resolved and downloaded the entire requirements file in binary-only mode for CPython 3.13
and 3.14 on `macosx_15_0_arm64` and `macosx_15_0_x86_64`: 25 distributions for each target.
All 100 downloaded files match the SHA-256 values in non-yanked, version-specific PyPI metadata.
Mypy 2.4 no longer supplies accelerated Intel wheels; pip selects its pure-Python wheel there.
Its native parser dependency also has an Intel-compatible artifact.

The reviewed CPython 3.14 NumPy wheels are:

| Wheel | SHA-256 |
| --- | --- |
| `numpy-2.5.4-cp314-cp314-macosx_14_0_arm64.whl` | `956555e0603a4d38019ae6925711cb9dc43195c076a928accf7ea5d50bddfe53` |
| `numpy-2.5.4-cp314-cp314-macosx_14_0_x86_64.whl` | `2c2c4afffdeb7920e445028dd71eb932cac3e704792e964bc2a232426d4f1255` |
| `setuptools-84.2.1-py3-none-any.whl` | `ca140b45d5325a9478f880e351484f62fef15f336462e449ca0c03c873d589c2` |

All 19 NumPy native extensions in each reviewed architecture pass the existing builder's
`lipo`/`otool` architecture and macOS 15 deployment checks. Neither wheel contains a `.dylibs`
payload. NumPy's 20 included notice files per architecture match existing notice bytes;
the 17 canonical snapshots retain their checksums and acquire current wheel origins.

All 17 setuptools notice files are byte-identical to their existing snapshots. Vendored
packaging changed from 26.0 to 26.3 with identical license texts. Updated the inventory origins
and renamed its three notice snapshots and setuptools' own notice consistently; no notice
hash was replaced. Reviewed the development tools' wheel metadata and license files as well;
they are not added to the application notice inventory because they are development tools.

The OpenCV version, ARM/Intel native-library hashes, and existing FFmpeg provenance qualification
are retained. This review does not resolve the [binary release restrictions](licensing.md#publishing-a-standalone-app).

## Validation

Local environment: macOS 27.0.1, Apple Silicon, CPython 3.14.8.

- Installed the complete requirements file into a new, isolated virtual environment and
  installed the project through its editable backend using the selected build dependencies.
- `python -m pytest -q`: **647 passed, 519 skipped** in 67.71 seconds. Native tests require
  the separate desktop run below.
- Ruff check and format check: passed; **96 files already formatted**.
- Mypy: passed for **81 source files**, with both accelerated and pure-Python Mypy wheels.
- `python -m pip check`: passed in both the clean environment and the working `.venv`.
- `python -m sudoku.license_checks`: passed in both environments.
- `pip-audit` 2.10.1, run from a separate audit environment against the clean environment's
  site-packages: **25 dependencies audited, zero skips, zero known vulnerabilities**.
  The audit ran before adding the local project distribution; it covers the complete resolved
  third-party requirements and does not audit native libraries embedded in wheels.
- Built the project's Python wheel with the selected setuptools and py2app. Every inventoried
  notice is included verbatim, and superseded notice filenames are absent.
- All **12 direct pins** match the working `.venv`; editable package metadata was refreshed.
- Workflow YAML syntax: parsed successfully with Ruby's YAML parser. Hosted action execution
  is verified separately against the exact published commit.
- `git diff --check`: passed.

The native desktop run used:

```sh
RUN_NATIVE_LAYOUT_TESTS=1 <clean-environment>/bin/python -m pytest -q \
  tests/test_native_layout.py tests/test_import_images.py \
  tests/test_import_ui.py tests/test_statistics_ui.py
```

It completed with **558 passed, 2 failed** in 104.99 seconds. Both failures were the Light/Dark
variants of `test_graphite_choices_render_paired_colors_across_key_windows`, waiting for the
game window to become key before any pixel assertion. Focused reruns of those two tests passed
with the original dependency pins (**2 passed, 470 deselected**) and with the updated pins
(**2 passed, 470 deselected**). The initial focus failures were not reproduced with the updates;
the complete native command was not rerun. No checks or assertions were weakened.

Intel and Python 3.13 checks establish wheel resolution and availability, not execution on those
targets. No standalone app was built, installed, deployed, or published by this maintenance run.
Source changes follow the repository's normal commit-time patch version and delivery policy.
