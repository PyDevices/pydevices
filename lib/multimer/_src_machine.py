# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One ``machine.Timer`` as the wake source (MicroPython on a board).

A single hardware or virtual timer, ONE_SHOT, re-armed to the earliest
deadline from the dispatcher. Its callback is already soft on esp32, rp2 and
stm32 (the port hands it to ``micropython.schedule``); ``wake_from_source``
queues the dispatcher the same way, so the user's callbacks run between
bytecodes of the main thread, and at the REPL while it waits for a key.

Boards have few timers (four on an ESP32); this uses one for every
``multimer.Timer`` in the program.
"""

from machine import Timer as _HW

name = "machine"
delivery = "bytecode"
wakes_blocking = True

_wake = None
_hw = None
_armed_ms = None


def _cb(_t):
    w = _wake
    if w is not None:
        w()


def start(wake):
    global _wake, _hw
    _wake = wake
    if _hw is None:
        last = None
        # -1 asks for a virtual timer where the port has them; ports that
        # number hardware timers take the first free id.
        for tid in (-1, 0, 1, 2, 3):
            try:
                _hw = _HW(tid)
                break
            except (ValueError, OSError) as exc:
                last = exc
        if _hw is None:
            raise last


def arm(delay_ms):
    global _armed_ms
    ms = int(delay_ms)
    if ms < 1:
        ms = 1
    _armed_ms = ms
    _hw.init(mode=_HW.ONE_SHOT, period=ms, callback=_cb)


def cancel():
    global _armed_ms
    _armed_ms = None
    try:
        _hw.deinit()
    except Exception:
        pass


def stop():
    global _wake
    cancel()
    _wake = None
