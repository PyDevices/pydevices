# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Give your computer a network link to the board over its USB cable.

The board shows up on your computer as a USB Ethernet adapter, and its DHCP
server gives the computer an address on a small network of their own. The
program then serves one web page over that link, so a browser on the computer
reaches the board with no Wi-Fi at all. Sockets, WebREPL and file transfers
work over the same link.

Needs: an ESP32-S2, S3 or P4, or an RP2040 or RP2350 with lwIP, running a
PyDevices MicroPython firmware, with ``usb-device`` and ``usb-device-net``
installed (ESP32 firmware has both frozen in). Plug the board's USB device port
into your computer. The program keeps the board's serial port, so the REPL
stays on the same cable.

Run it:

    mpremote run usb_device_net.py

The program prints the board's address on the link. Open
``http://<that address>/`` in a browser on the computer to see the page.

Tested on: Waveshare ESP32-S3 Touch LCD 4.3 on MicroPython 1.30 preview.
"""

import socket
import time

import usb.device
from usb.device.net import NCMInterface

# Change these to match your setup.
SECONDS = 120  # how long to serve the page
PORT = 80

# Present the network adapter. This re-enumerates the board, and
# builtin_driver keeps the serial port.
net = NCMInterface()
usb.device.get().init(net, builtin_driver=True)

# Wait for the computer to bring the link up: it switches the adapter on, then
# asks the board's DHCP server for an address.
while not net.nic.isconnected():
    time.sleep_ms(100)
address = net.nic.ipconfig("addr4")[0]
print("Link up: open http://%s:%d/ on the computer" % (address, PORT))

# Serve one small page to every request until the time runs out.
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT))
server.listen(2)
server.settimeout(1)
served = 0
deadline = time.ticks_add(time.ticks_ms(), SECONDS * 1000)
while time.ticks_diff(deadline, time.ticks_ms()) > 0:
    try:
        client, _ = server.accept()
    except OSError:
        continue
    client.recv(1024)
    served += 1
    body = "<h1>Hello over USB</h1><p>Request %d, served by the board.</p>" % served
    client.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n" + body)
    client.close()
server.close()
print("Served %d requests" % served)
