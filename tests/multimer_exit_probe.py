# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run as a script: does ``sys.exit()`` from a timer callback end the program?

The shape of a game that quits from its own tick: keep the program alive past
the script body (as ``appdev.App`` does), tick every 20 ms, and call
``sys.exit()`` on the third tick. The program must end, however the tick
reached the main thread.

Arguments: the ``lib`` directory to test, then any of ``KeyboardInterrupt``
(raise that instead) and ``busy`` (the script body spins for a moment
instead of ending, so the tick lands in the middle of it).
"""

import sys
import time

sys.path.insert(0, sys.argv[1])
raise_kbd = "KeyboardInterrupt" in sys.argv[2:]
busy = "busy" in sys.argv[2:]

import multimer  # noqa: E402

ticks = [0]


def _tick(_t):
    ticks[0] += 1
    print("tick", ticks[0])
    if ticks[0] == 3:
        print("exiting")
        if raise_kbd:
            raise KeyboardInterrupt
        sys.exit()


multimer.keepalive()
multimer.every(20, _tick)
print("source", multimer.info()["source"])

if busy:
    # No multimer idle point in here: plain Python, the way a program's own
    # loop or a slow import looks to the timers.
    _now = getattr(time, "ticks_ms", None)
    if _now is None:
        _now = lambda: int(time.monotonic() * 1000)  # noqa: E731
    _end = _now() + 200
    while _now() - _end < 0:
        pass
    print("body done")
