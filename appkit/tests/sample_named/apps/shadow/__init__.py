# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app named like a library on the path, which it uses."""

import shadow


def main(scope):
    scope.store()["who"] = shadow.WHO
