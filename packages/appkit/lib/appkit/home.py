# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The home screen: a button for each app."""

import lvgl as lv


def main(scope):
    launcher = scope.launcher
    page = scope.root
    page.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    page.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    for name in launcher.names:
        if name == launcher.home:
            continue
        b = lv.button(page)
        lv.label(b).set_text(launcher.info[name].get("title", name))
        b.add_event_cb(lambda e, n=name: scope.switch(n), lv.EVENT.CLICKED, None)
