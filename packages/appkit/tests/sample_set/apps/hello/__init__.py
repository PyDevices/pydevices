# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app: one label."""

import lvgl as lv


def main(scope):
    lv.label(scope.root).set_text("Hello")
