# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Choose supported native presentation without limiting newer macOS features."""

import AppKit as AK
from Foundation import NSProcessInfo


def supports_glass_buttons() -> bool:
    """Require macOS 26 or newer and bridge support before selecting glass."""
    return bool(
        NSProcessInfo.processInfo().isOperatingSystemAtLeastVersion_((26, 0, 0))
        and hasattr(AK, "NSBezelStyleGlass")
    )


def action_bezel_style(high_contrast: bool = False) -> int:
    """Keep High Contrast opaque and use rounded buttons when glass is unavailable."""
    if high_contrast or not supports_glass_buttons():
        return int(AK.NSBezelStyleRounded)
    return int(AK.NSBezelStyleGlass)
