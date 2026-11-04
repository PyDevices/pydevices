# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""`import mip` on CircuitPython, which has none. Not for MicroPython, whose own mip this would hide."""

from omip import install  # noqa: F401
