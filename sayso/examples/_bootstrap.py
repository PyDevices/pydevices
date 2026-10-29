# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Make the sayso library importable from this checkout.

The examples import this first. It adds the project's ``lib`` folder to ``sys.path``, so they run from a clone without installing the package. If you installed sayso, you can delete the two lines that use it.

Needs: CPython.
"""

import os
import sys


def bootstrap():
    # Put <project root>/lib first on the import path, once.
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
