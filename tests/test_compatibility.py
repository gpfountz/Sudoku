# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Cover OS and bridge availability independently of the machine running tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sudoku import compatibility


@pytest.mark.parametrize("major_version", [14, 15, 26, 27])
@pytest.mark.parametrize("bridge_has_glass", [False, True])
@pytest.mark.parametrize("high_contrast", [False, True])
def test_action_styles_respect_os_bridge_and_contrast(
    monkeypatch: pytest.MonkeyPatch,
    major_version: int,
    bridge_has_glass: bool,
    high_contrast: bool,
) -> None:
    """Avoid unsupported glass even if an old OS exposes its enum through PyObjC."""
    appkit: SimpleNamespace = SimpleNamespace(NSBezelStyleRounded=1)
    if bridge_has_glass:
        appkit.NSBezelStyleGlass = 16
    process: Mock = Mock()
    process.isOperatingSystemAtLeastVersion_.return_value = major_version >= 26
    process_info: Mock = Mock()
    process_info.processInfo.return_value = process
    monkeypatch.setattr(compatibility, "AK", appkit)
    monkeypatch.setattr(compatibility, "NSProcessInfo", process_info)

    expected_glass: bool = major_version >= 26 and bridge_has_glass
    assert compatibility.supports_glass_buttons() is expected_glass
    assert compatibility.action_bezel_style(high_contrast) == (
        16 if expected_glass and not high_contrast else 1
    )
    process.isOperatingSystemAtLeastVersion_.assert_called_with((26, 0, 0))
