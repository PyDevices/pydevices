# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Keep two front panels in step with one device using hmilink.

A device holds a JSON document, here a volume and a tone setting. Each
panel gets a copy and can change it. The device checks every change,
keeps the value it really used, and sends it to every panel, so they never
disagree. This runs the device and two panels in one program; over Wi-Fi
the panels would be a phone's browser or another board.

Needs: nothing but hmilink, so no board.

Run it:
    micropython hmilink_simpletest.py

Tested on: the unix ports of MicroPython and CircuitPython, and CPython
3.12 on Linux and 3.14 on Windows.
"""

import time

import hmilink
from hmilink import local


# The device's model: what the document holds and which changes it accepts.
class Amp(hmilink.Model):
    def __init__(self):
        super().__init__({"volume": 5, "tone": "warm"})

    def apply(self, op):
        if op["path"] == "/volume":
            # Keep the volume between 0 and 10, and say what was used.
            op["value"] = max(0, min(10, op["value"]))
        return super().apply(op)


def run_for_a_moment():
    """Let the device and both panels pass their messages along."""
    for _ in range(10):
        device.poll()
        panel_a.poll()
        panel_b.poll()
        time.sleep(0.002)


# One device, and two panels connected to it.
device = hmilink.Device(Amp())
listener = device.add(local.serve())
panel_a = hmilink.Panel(local.connect(listener))
panel_b = hmilink.Panel(local.connect(listener))
run_for_a_moment()
print("Both panels start with", panel_a.doc, panel_b.doc)

# Panel A turns the tone bright; panel B sees it.
panel_a.set("/tone", "bright")
run_for_a_moment()
print("Panel B's tone is now", panel_b.doc["tone"])

# Panel B asks for volume 15. The device allows 10, and both panels show 10.
panel_b.set("/volume", 15)
run_for_a_moment()
print("Volume on A, B and the device:", panel_a.doc["volume"], panel_b.doc["volume"],
      device.model.doc["volume"])
