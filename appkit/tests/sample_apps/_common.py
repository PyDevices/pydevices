# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""What every sample app makes: a timer, a subscription, a device, a buffer
and, where LVGL is loaded, a screen of widgets."""

import events

from . import shared

#: Bytes each app holds while it runs, so a leaked app shows in the heap.
BUFFER = 4096


class Ticker:
    """A device that reports one KEYDOWN per poll."""

    type = 0

    def __init__(self, key):
        self.app = None
        self.key = key

    def poll(self):
        return [events.Key(events.KEYDOWN, "", self.key, 0, 0, 0)]

    def subscribe(self, cb, event_types=None):
        pass


def build(scope, state, key):
    state["buf"] = bytearray(BUFFER)
    state["ticks"] = 0
    state["keys"] = 0

    @scope.every(5)
    def tick(timer):
        state["ticks"] += 1

    def on_key(e):
        if e.key == key:
            state["keys"] += 1

    scope.on(events.KEYDOWN, on_key)
    scope.register(Ticker(key))
    lv = shared.lvgl_ready()
    if lv is not None:
        base = lv.screen_active()
        scr = scope.screen()
        for i in range(8):
            btn = lv.button(scr)
            lbl = lv.label(btn)
            lbl.set_text("%s %d" % (scope.name, i))
        # One widget on the screen that was showing, and one on the top
        # layer: both are the app's, and close() must delete them.
        lv.label(base).set_text("base")
        lv.label(lv.layer_top()).set_text("top")
    return tick
