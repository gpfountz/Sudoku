# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Exercise first-install metadata hooks without importing the application package."""

import shutil
import subprocess
import sys
from email.message import Message
from email.parser import Parser
from pathlib import Path

import pytest

from sudoku.version import APP_VERSION

ROOT: Path = Path(__file__).resolve().parents[1]
METADATA_PROBE: str = """
import importlib.abc
import sys
from pathlib import Path
from setuptools import build_meta


class UninstalledApplication(importlib.abc.MetaPathFinder):
    \"\"\"Keep build metadata independent of any previously installed application.\"\"\"

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        \"\"\"Model a fresh installer whose application package is not importable yet.\"\"\"
        if fullname == 'sudoku' or fullname.startswith('sudoku.'):
            raise ModuleNotFoundError("No module named 'sudoku'")


sys.meta_path.insert(0, UninstalledApplication())
kind: str = sys.argv[1]
getattr(build_meta, 'get_requires_for_build_' + kind)()
destination: Path = Path('metadata')
destination.mkdir()
getattr(build_meta, 'prepare_metadata_for_build_' + kind)(str(destination))
"""


@pytest.mark.parametrize("kind", ["editable", "wheel"])
def test_first_install_metadata_reads_shared_version_without_package_import(
    tmp_path: Path, kind: str
) -> None:
    """Build actual metadata hooks even when an existing editable install could hide the bug."""
    for name in ("setup.py", "pyproject.toml", "LICENSE", "launch.py"):
        shutil.copy2(ROOT / name, tmp_path / name)
    package: Path = tmp_path / "sudoku"
    package.mkdir()
    (package / "__init__.py").write_text(
        'raise AssertionError("Packaging must not initialize the application")\n'
    )
    shutil.copy2(ROOT / "sudoku/version.py", package / "version.py")
    shutil.copytree(ROOT / "sudoku/data/licenses", package / "data/licenses")
    shutil.copy2(ROOT / "sudoku/data/PUZZLE-LICENSE.txt", package / "data/PUZZLE-LICENSE.txt")

    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", "-c", METADATA_PROBE, kind],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    metadata_file: Path = next((tmp_path / "metadata").glob("*.dist-info/METADATA"))
    metadata: Message = Parser().parsestr(metadata_file.read_text())
    assert metadata["Name"] == "pfountz-sudoku"
    assert metadata["Version"] == APP_VERSION
    assert metadata["License-Expression"] == "GPL-3.0-only"
