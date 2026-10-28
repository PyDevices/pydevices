# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run two timers at once and stop them from a third.

multimer gives every PyDevices host, board or desktop, the same Timer as
MicroPython's machine.Timer. Callbacks run on the main thread, between
lines of your program, so they can touch anything it can. Here one timer
ticks every quarter second, another every second, and a one-shot timer
stops them both.

Needs: nothing but multimer, so no board.

Run it:
    micropython multimer_simpletest.py

Tested on: the unix ports of MicroPython and CircuitPython, and CPython
3.12 on Linux and 3.14 on Windows.
"""

import multimer
from multimer import Timer

# Change these to try other rates.
FAST_MS = 250
SLOW_MS = 1000
STOP_MS = 3100

counts = {"fast": 0, "slow": 0}
done = []
start = multimer.ticks_ms()


def stamp():
    return multimer.ticks_diff(multimer.ticks_ms(), start)


def on_fast(timer):
    counts["fast"] += 1


def on_slow(timer):
    counts["slow"] += 1
    print("%5d ms: %d fast ticks so far" % (stamp(), counts["fast"]))


def on_stop(timer):
    fast.deinit()
    slow.deinit()
    done.append(True)


# Two periodic timers, made the two ways multimer offers.
fast = Timer(-1, mode=Timer.PERIODIC, period=FAST_MS, callback=on_fast)
slow = multimer.every(SLOW_MS, on_slow)

# A one-shot timer that stops both of them.
multimer.after(STOP_MS, on_stop)

# Wait until it has. The callbacks run while this waits.
multimer.run_until(lambda: done)
print("Stopped at %d ms: %d fast, %d slow" % (stamp(), counts["fast"], counts["slow"]))
