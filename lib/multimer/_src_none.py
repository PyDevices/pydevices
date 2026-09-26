# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""No wake source: delivery only at idle points (sleep_ms, pump, the hook loops).

CircuitPython, and any build with neither a hardware timer, signals, threads
nor a browser loop. ``multimer.repl()`` is the way in from outside.
"""

name = "none"
delivery = "idle"
wakes_blocking = False


def start(wake):
    pass


def arm(delay_ms):
    pass


def cancel():
    pass


def stop():
    pass
