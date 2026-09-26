# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The browser's timer as the wake source (direct MicroPython WebAssembly).

``_wasm_bridge.timer_start`` is ``setTimeout`` with a Python callback the
bridge calls once the VM has returned to the page's event loop: an idle
point by construction, and the page loop outlives the script, so no pump is
needed after the script body ends. While Python is inside an Asyncify sleep
the bridge cannot call in; it queues the firing, and ``sleep_ms``'s poll
picks it up.
"""

import _wasm_bridge

name = "wasm"
delivery = "idle"
wakes_blocking = False

_ID = 0x7E11  # one browser timer for the dispatcher
_wake = None
_armed = False


def _fire():
    global _armed
    _armed = False
    w = _wake
    if w is not None:
        w()


def start(wake):
    global _wake
    _wake = wake


def arm(delay_ms):
    global _armed
    _armed = True
    _wasm_bridge.timer_start(_ID, max(0, int(delay_ms)), False, _fire)


def cancel():
    global _armed
    _armed = False
    # Unconditional: the bridge ignores an id it no longer holds, and a
    # one-shot that already fired was deleted on the browser side.
    _wasm_bridge.timer_cancel(_ID)


def stop():
    global _wake
    cancel()
    _wake = None


def poll():
    """Deliver firings the bridge queued while Python was sleeping."""
    fired = False
    while True:
        tid = _wasm_bridge.timer_poll()
        if tid is None:
            break
        if tid == _ID:
            fired = True
    if fired:
        _fire()


def sleep_ms(ms):
    _wasm_bridge.sleep_ms(max(0, int(ms)))
    poll()
