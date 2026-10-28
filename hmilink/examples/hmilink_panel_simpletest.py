# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Connect to a device over Wi-Fi and turn its volume up.

The panel connects to a device, gets a copy of its settings, and turns the
volume up a step at a time, past the device's limit of 10. It prints what
the device really used, then keeps listening and prints what other panels
change, so you can watch a second panel or a browser move the volume.

The device can be another board or a laptop running
hmilink_device_simpletest.py, or anything else that speaks hmilink.

Needs: a board with Wi-Fi and hmilink. On MicroPython, a secrets.py
holding WIFI_SSID and WIFI_PASSWORD; on CircuitPython, settings.toml.
Install hmilink with:
    mpremote mip install github:PyDevices/pydevices/hmilink
On CircuitPython, copy its hmilink folder into the board's lib folder.
It runs on a laptop too, without the Wi-Fi step.

Run it:
    mpremote run hmilink_panel_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview and CPython 3.14
on Windows, each with another board as the device.
"""

import time

import hmilink
from hmilink import tcp

# Change these to match your setup.
DEVICE = "192.168.1.42"  # the address the device prints
PORT = 9000
LISTEN_S = 20


def poll_for(seconds):
    """Pass messages to and from the device for a while."""
    for _ in range(int(seconds * 100)):
        panel.poll()
        time.sleep(0.01)


def show(op):
    """Print each change the device sends."""
    global answered
    print("The device says", op["path"], "is", op.get("value"))
    answered = True


# Join Wi-Fi, if this is a board.
# CircuitPython joins at boot from settings.toml, and makes its sockets
# from a pool on the radio.
pool = None
try:
    import wifi
except ImportError:
    pass
else:
    if not wifi.radio.connected:
        wifi.connect_from_secrets()
    try:
        import socketpool

        pool = socketpool.SocketPool(wifi.radio)
    except ImportError:
        pass

# Connect, and wait for the device's copy of its settings.
panel = hmilink.Panel(tcp.connect(DEVICE, PORT, pool=pool))
while not panel.ready:
    poll_for(0.1)
print("Connected:", panel.doc)
panel.on_op = show

# Turn the volume up past 10, waiting each time for the device to answer
# with the value it used.
for volume in (6, 8, 10, 12):
    print("Asking for volume", volume)
    answered = False
    panel.set("/volume", volume)
    while not answered:
        poll_for(0.05)

# Listen for changes from other panels, then let go.
print("Listening for", LISTEN_S, "seconds")
poll_for(LISTEN_S)
panel.close()
print("Volume ended at", panel.doc["volume"])
