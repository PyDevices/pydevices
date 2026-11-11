# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check usb.host.dfu by reading a board's flash through its DFU bootloader.

Reads the first 128 KB of an Arduino GIGA's firmware0 (flash address
0x08040000) and compares its SHA-256 with the file it was flashed from. It
only reads: nothing is downloaded, erased or left. Reset the GIGA afterwards.

Needs: an ESP32-S3 or P4 board running a firmware built with usbhost, and a
GIGA in its DFU bootloader (double-tap its reset button) on the host port,
holding the firmware0 whose first 128 KB hash to EXPECTED.

Run it:

    mpftp run --follow tests/hardware/usb_host_dfu_read_check.py

Expect: the alternates "Internal Flash" and others, then "match True". If the
bootloader's pointer doesn't start at 0x08000000 the read returns other data
and the check says so; don't fall back to a set-address command without asking.
"""

import hashlib
import time

import usb.core
from usb.host.dfu import Dfu

# Change these to match your setup.
ADDRESS = 0x08040000
LENGTH = 128 * 1024
EXPECTED = "800a01b4e9bd719af7504db49db6ad30356868ec7b795f019637fc79aaafcbea"  # firmware0-406-on-410-5111a1e.bin

usb.core.start()
time.sleep_ms(3000)
dfu = Dfu(usb.core.find(custom_match=Dfu.match))
print("alternates", dfu.alternates())
digest = hashlib.sha256()
for chunk in dfu.chunks(ADDRESS, LENGTH):
    digest.update(chunk)
got = "".join("%02x" % b for b in digest.digest())
print("sha256", got)
print("match", got == EXPECTED)
