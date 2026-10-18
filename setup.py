# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Build the local macOS application bundle with py2app."""

import os

from py2app.build_app import py2app
from setuptools import setup

from sudoku.version import APP_VERSION


class BundleCommand(py2app):
    """Bundle dependencies already installed through the project's development extra."""

    def finalize_options(self) -> None:
        """Avoid py2app's obsolete dependency-install path with modern project metadata."""
        self.distribution.install_requires = []
        super().finalize_options()


setup(
    cmdclass={"py2app": BundleCommand},
    app=[{"script": "launch.py", "dest_base": "Sudoku"}],
    options={
        "py2app": {
            "resources": [
                os.environ.get("SUDOKU_BUILD_CATALOG", "sudoku/data/catalog"),
                "sudoku/data/licenses",
            ],
            "iconfile": "resources/Sudoku.icns",
            "argv_emulation": False,
            # OpenCV loads its extension and configuration by filesystem path.
            "packages": ["sudoku", "cv2", "numpy"],
            "includes": [
                "AppKit",
                "Foundation",
                "objc",
                "PyObjCTools.AppHelper",
                "Vision",
                "Quartz",
            ],
            "excludes": ["pytest", "mypy", "ruff", "tkinter"],
            "plist": {
                "CFBundleName": "Sudoku",
                "CFBundleDisplayName": "Sudoku",
                "CFBundleIdentifier": "com.pfountz.sudoku",
                "NSHumanReadableCopyright": "Copyright © 2026 Greg Pfountz",
                "LSMinimumSystemVersion": "27.0",
                "CFBundleShortVersionString": APP_VERSION,
                "CFBundleVersion": "24",
                "NSHighResolutionCapable": True,
            },
        }
    },
)
