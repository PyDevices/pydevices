# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app that counts seconds. Its timer stops when the app closes."""

import lvgl as lv


def main(scope):
    label = lv.label(scope.root)
    label.center()
    seconds = [0]
    label.set_text("0 s")

    @scope.every(1000)
    def tick(timer):
        seconds[0] += 1
        label.set_text("%d s" % seconds[0])
