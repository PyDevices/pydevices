# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A C helper as the wake source (MicroPython builds with the ``_timing`` module).

For ports with neither signals nor ``machine.Timer`` -- the windows port.
``_timing`` (micropython-pydevices, patch 0015) owns one OS timer whose
expiry calls ``mp_sched_schedule`` on the Python callable given to
``_timing.init``; the callback runs at the next bytecode boundary, and the
port's console wait services pending callbacks while the REPL is idle.
"""

import _timing

name = "native"
delivery = "bytecode"
wakes_blocking = True

_wake = None


def _cb(_arg):
    # Already at a bytecode boundary: the port scheduled this call.
    w = _wake
    if w is not None:
        w(True)


def start(wake):
    global _wake
    _wake = wake
    _timing.init(_cb)


def arm(delay_ms):
    _timing.arm(max(0, int(delay_ms)))


def cancel():
    _timing.cancel()


def stop():
    global _wake
    cancel()
    _wake = None
