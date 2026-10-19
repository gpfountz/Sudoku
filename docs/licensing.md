# Licensing and attribution

[Back to the README](../README.md)

## Application license

Copyright © 2026 Greg Pfountz. Original author: Greg Pfountz.

The original application code, tests, scripts, documentation, and original artwork are
licensed under the **GNU General Public License, version 3 only** (`GPL-3.0-only`).
The complete, unmodified terms are in [LICENSE](../LICENSE). The standard warranty
disclaimer and limitation of liability apply to the extent permitted by law. No additional
advertising-credit requirement or custom indemnification clause is imposed.

This designation does not automatically authorize use under a future GPL version. Original
copyright remains with the relevant authors; this is not a public-domain dedication.

## Reusing or modifying the code

You may use and modify the application privately without publishing your changes. If you
distribute the covered application or a derivative work, whether free or for payment, comply
with GPLv3: preserve the applicable copyright, license, and warranty notices, identify your
changes and their dates, and license the covered work under GPLv3. When distributing a compiled
app, provide its corresponding source using one of the methods in section 6 of the license.
The source obligations apply to recipients; a public GitHub fork is not universally required.

Preserve the appropriate legal notices displayed through **Sudoku → About Sudoku** in
distributed modified versions, as required by GPLv3. Standard GPLv3 does not generally require
the original author's name in every advertisement or on a startup screen. You may add truthful
credit for your own changes. Do not imply that the original author endorses your version.

This is a practical overview. The [license text](../LICENSE) controls the legal terms.

## Separately licensed material

- The puzzle catalog retains its existing public-domain dedication in
  [PUZZLE-LICENSE.txt](../sudoku/data/PUZZLE-LICENSE.txt). See the
  [catalog guide](puzzle-catalog.md) for its origin.
- Python, PyObjC, NumPy, OpenCV, setuptools, the py2app launcher, and their embedded components retain
  their upstream terms and notices. Those files are not claimed as Greg Pfountz's work.
- Apple system frameworks come from macOS and are not distributed by this repository.

Verbatim upstream texts and a provenance inventory are kept in
[`sudoku/data/licenses/`](../sudoku/data/licenses/). Both the application license and the
third-party notices can be read offline from **About Sudoku**. The inventory describes the
reviewed development environment; it is not a declaration that every binary-release
obligation has been fulfilled.

## Dependency and notice maintenance

The current inventory records CPython 3.14.6, PyObjC 12.2.2, NumPy 2.5.3,
opencv-python-headless 5.0.0.93, py2app 0.28.10, and setuptools 84.0.0. It includes the wheel-supplied license
texts, upstream PyObjC notices omitted from two wheels, and SHA-256 hashes of OpenCV's
bundled native libraries. Source development supports the project's declared Python range.
For local packaging, the recorded Python version is the minimum reviewed patch: stable
CPython 3.14.6 and newer within 3.14 are accepted when the installed `lib/python3.14/LICENSE.txt`
matches the reviewed notice byte for byte. Older patches, prereleases, other minor versions,
and other implementations are rejected. All other inventoried versions remain exact requirements;
notice checksums and native-library membership and hashes remain enforced.

On October 19, 2026, the installed Homebrew CPython 3.14.8 (`3.14.8_2`) root `LICENSE` and
standard-library `LICENSE.txt` both matched the recorded Python 3.14.6 notice exactly, with SHA-256
`b0e25a78cffb43f4d92de8b61ccfa1f1f98ecbc22330b54b5251e7b6ba010231`.
This confirms the preserved Python notice for that installation; it does not constitute a review
of every separately licensed library linked by Python or of future patches. Build metadata in
`Sudoku.app/Contents/Resources/build-info.json` and beside the ZIP records the actual Python version,
application version, source commit, uncommitted-change status, and UTC timestamp.

Before building:

```sh
.venv/bin/python -m sudoku.license_checks
```

After changing dependencies, moving Python outside the accepted patch range, or encountering a
changed installed Python notice, review the actual distributions and native libraries,
collect their complete license texts without altering them, and update the versions, notice
origins, and hashes in `sudoku/data/licenses/inventory.json`. Review the wheel contents rather
than relying only on the package's top-level license classifier. Update this guide and the
third-party summary when the reviewed environment changes. Never update hashes merely to
bypass a failed check. If the root license or puzzle dedication changes, refresh its runtime
copy as well; automated checks require the copies to match.

## Publishing a standalone app

**The current OpenCV wheel has an unresolved binary provenance issue.** Its FFmpeg binary
reports GPLv3-or-later, while the supplied third-party notice describes FFmpeg as LGPL.
See the [binary audit](opencv-binary-audit.md). Adoption of GPLv3 for this repository does
not resolve missing notices, source, or build materials for those bundled libraries.

Before publishing a binary release:

1. Resolve the exact licenses, notices, and corresponding source/build materials for all
   redistributed dependencies, including the libraries inside OpenCV's macOS wheel.
2. Record the exact release commit and retain a matching source archive, with the application,
   modifications, build/install scripts, and any dependency source and build materials required
   by the applicable licenses. A source archive of this repository alone may be insufficient.
3. Publish the binary and equivalent access to its corresponding source together, with clear
   source-download directions next to the binary. A link only to a changing `main` branch
   does not identify the source for an older release.
4. Build outside cloud sync, extract the ZIP, verify its signature, and confirm that About,
   View License, and Third-Party Notices work without a network connection. The builder checks
   notice inclusion and dependency drift; it does not certify legal compliance or publish files.

See the [development guide](development.md#building-and-installing) for build commands.
