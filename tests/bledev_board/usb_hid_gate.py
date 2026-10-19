# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The HID gate's script over USB: the board types into whatever its USB port is plugged into.

The same keyboard code as ``hid_peripheral.py``: ``hid_script.perform()``
drives Adafruit's ``adafruit_hid`` over a set of devices. The one line that
changes is where the devices come from, ``usb_hid`` (CircuitPython's module,
here over micropython-lib's ``usb-device-hid``) instead of a
``bledev.hid.Peripheral``. ``usb_hid``'s devices are a keyboard, a mouse and
consumer control, so the script's gamepad steps are skipped, as they are over
BLE without ``GAMEPAD``.

Needs ``hid_script.py`` beside it, ``usb_hid``, ``adafruit_hid``, and
pydevices' ``events`` and ``keys`` (which ``hid_script`` imports). On Windows,
``usb_hid_gate_windows.py`` hears it. ``PLANT = True`` drops Shift from the
first character typed, as in ``hid_peripheral.py``; the comparison must then
fail. ``run()`` returns the number of steps sent.
"""
import asyncio

import usb_hid  # the port line: over BLE, bledev.hid.Peripheral(ble, ...)
import hid_script

PLANT = False
GAP_MS = 30  # pause after each character or step, as in hid_peripheral.py
START_MS = 5000  # time for the host to install the keyboard after enable()
SKIP = ()  # step kinds left out: ("consumer",) when the host can't keep media keys from acting
#           (Windows hands consumer control to the shell, past any hook an app can set)


async def main():
    usb_hid.enable()
    await asyncio.sleep_ms(START_MS)
    steps = tuple(st for st in hid_script.STEPS if st[0] not in SKIP)
    if PLANT:
        text = steps[0][1]
        steps = (("type", text[0].lower()), ("type", text[1:])) + steps[1:]
    await hid_script.perform(usb_hid, steps, gap_ms=GAP_MS, sleep_ms=asyncio.sleep_ms)
    return len(steps)


def run():
    return asyncio.run(main())
