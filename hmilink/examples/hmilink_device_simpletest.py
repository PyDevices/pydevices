# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Serve a device's settings over Wi-Fi, for panels to show and change.

The device holds a volume and a tone setting and serves them on a TCP
port. Each panel that connects gets a copy, and every change one panel
makes reaches all the others. The device keeps the volume between 0 and
10, so a panel that asks for more is told what was really used.

The panel can be another board or a laptop running
hmilink_panel_simpletest.py, or a phone's browser: open
http://<the device's address>:9000/ for a slider.

Needs: a board with Wi-Fi and hmilink. On MicroPython, a secrets.py
holding WIFI_SSID and WIFI_PASSWORD; on CircuitPython, settings.toml.
Install hmilink with:
    mpremote mip install github:PyDevices/pydevices/hmilink
On CircuitPython, copy its hmilink folder into the board's lib folder.
It runs on a laptop too, without the Wi-Fi step.

Run it:
    mpremote run hmilink_device_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, with another
board and CPython 3.14 on Windows as panels.
"""

import time

import hmilink
from hmilink import tcp

# Change these to match your setup.
PORT = 9000

# The page a browser gets: a slider that speaks hmilink over a WebSocket.
PAGE = b"""<!doctype html><meta name=viewport content="width=device-width">
<h1>Volume <output id=o></output></h1><input type=range min=0 max=12 id=v>
<script>
let ws = new WebSocket("ws://" + location.host + "/ws"), id = 0;
ws.onopen = () => ws.send('{"t":"hello","v":1}');
ws.onmessage = (e) => {
  let m = JSON.parse(e.data);
  if (m.t == "doc") v.value = o.value = m.doc.volume;
  if (m.t == "op" && m.path == "/volume") v.value = o.value = m.value;
};
v.onchange = () => ws.send(JSON.stringify(
  {t: "op", op: "replace", path: "/volume", value: +v.value, id: ++id}));
</script>"""


# The device's model: what the document holds and which changes it accepts.
class Amp(hmilink.Model):
    def __init__(self):
        super().__init__({"volume": 5, "tone": "warm"})

    def apply(self, op):
        if op["path"] == "/volume":
            # Keep the volume between 0 and 10, and say what was used.
            op["value"] = max(0, min(10, op["value"]))
        print("A panel set", op["path"], "to", op["value"])
        return super().apply(op)


# Join Wi-Fi, if this is a board, and say where panels should connect.
# CircuitPython joins at boot from settings.toml, and makes its sockets
# from a pool on the radio.
pool = None
try:
    import wifi
except ImportError:
    print("Serving on this computer's address, port", PORT)
else:
    if not wifi.radio.connected:
        wifi.connect_from_secrets()
    try:
        import socketpool

        pool = socketpool.SocketPool(wifi.radio)
    except ImportError:
        pass
    print("Serving on", wifi.radio.ipv4_address, "port", PORT)

# Serve the model, and the page to any browser that asks.
device = hmilink.Device(Amp())
device.add(tcp.serve(PORT, page=PAGE, pool=pool))

# Poll often: each poll takes in new panels and passes changes along.
while True:
    device.poll()
    time.sleep(0.01)
