# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app named like a built-in module, which it uses."""

import json

from . import helper


def main(scope):
    scope.store()["dumped"] = json.dumps({"a": helper.ONE})
