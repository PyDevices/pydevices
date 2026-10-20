# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Minimal CPython shim for ``from micropython import const`` in unit tests.

PyDevices dependencies (``graphics``, ``palettes``, ``framebuf``) come from the CI
sparse checkout; see ``.github/workflows/pdwidgets.yml`` at the repository root.
"""


def const(x):
    return x
