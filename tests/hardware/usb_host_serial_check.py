# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check usb.host.cdc against a real USB-serial adapter or CDC-ACM device.

Starts the host, lists what is plugged in, opens the first device Serial.match
accepts, names its chip, writes a line and reads back what arrives. With the
adapter's TX wired to its RX the line comes back; with a microcontroller's CDC
console on the port, its REPL answers.

Needs: an ESP32-S3 or P4 board with a firmware built with usbhost, and a USB
serial adapter (CH340, CP210x, FTDI, PL2303) or a CDC-ACM device on the host
port. The frozen usb.host.cdc in a firmware older than this package shadows a
copy in /lib: put the package folder first on sys.path, or build with it.

Run it:

    mpftp run tests/hardware/usb_host_serial_check.py

Expect: "chip" names the adapter, "wrote 12" and, with a loopback jumper, "read b'hello loop\\r\\n'".
"""

import time

import usb.core
from usb.host.cdc import Serial

# Change these to match your setup.
BAUDRATE = 115200
LINE = b"hello loop\r\n"

usb.core.start(classes=("cdc",))
time.sleep_ms(3000)
for dev in usb.core.find(find_all=True):
    print("found", dev)
dev = usb.core.find(custom_match=Serial.match)
if dev is None:
    raise SystemExit("no serial device on the host port")
port = Serial(dev, baudrate=BAUDRATE, timeout=500)
print("chip", port.chip)
print("wrote", port.write(LINE))
time.sleep_ms(300)
print("read", port.read(64))
port.close()
