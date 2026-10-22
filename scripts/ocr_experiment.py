# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Force the validated Fast-first policy in source previews and diagnostics."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from sudoku import compatibility


@contextmanager
def experimental_fast_ocr(enabled: bool) -> Iterator[None]:
    """Force Fast-first when requested; otherwise retain the host's automatic policy."""
    if not enabled:
        yield
        return
    with patch.object(compatibility, "prefers_fast_ocr", return_value=True):
        yield
