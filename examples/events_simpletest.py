# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Make events, tell them apart by type, and add one of your own.

Every input in PyDevices, from a touch screen to a USB keyboard, arrives
as one of these small named tuples. A program looks at .type and reads the
fields it needs. Here three events are made by hand, the way a display
backend makes them, and handled in a loop.

Needs: nothing but the events module, so no board or display.

Run it:
    micropython events_simpletest.py

Tested on: the unix ports of MicroPython and CircuitPython, and CPython
3.12 on Linux and 3.14 on Windows.
"""

import events

# Add an event type of your own, with its own fields.
events.register_event("ALARM", fields="type minutes")

# A press and a release of the left mouse button, and the alarm.
queue = [
    events.Button(events.MOUSEBUTTONDOWN, (120, 80), 1, False, None),
    events.Button(events.MOUSEBUTTONUP, (122, 81), 1, False, None),
    events.Alarm(events.ALARM, 5),
]

# Handle each one by its type.
for event in queue:
    if event.type == events.MOUSEBUTTONDOWN:
        print("Button %d pressed at %s" % (event.button, event.pos))
    elif event.type == events.MOUSEBUTTONUP:
        print("Button %d released at %s" % (event.button, event.pos))
    elif event.type == events.ALARM:
        print("Alarm after %d minutes" % event.minutes)
