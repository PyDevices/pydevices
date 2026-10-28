# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""An app with a button that says hello."""

import lvgl as lv


def main(scope):
    label = lv.label(scope.root)
    label.set_text("Press the button")
    label.align(lv.ALIGN.CENTER, 0, -40)

    button = lv.button(scope.root)
    button.center()
    lv.label(button).set_text("Hello")

    def on_click(event):
        label.set_text("Hello from appkit")

    button.add_event_cb(on_click, lv.EVENT.CLICKED, None)
