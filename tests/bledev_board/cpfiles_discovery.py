# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Restart a CircuitPython ESP32-S3 in BLE discovery mode, with no hand on the board.

CircuitPython's BLE workflow (the file service and the serial console) only
advertises to a new host in discovery mode. You get there by pressing reset
during the second of blue blinking after boot: the supervisor writes a marker
into an RTC register that survives a reset (``port_set_saved_word``), and
clears it once the second is up, so a reset inside that second boots with the
marker set (``supervisor/shared/bluetooth/bluetooth.c``). Discovery mode also
erases the board's bonds.

This writes the same marker and resets, which is the same thing without the
button. ``memorymap`` may write the RTC peripheral's registers on the S3, and
the marker lives in ``RTC_CNTL_STORE0_REG``. Run it with
``mpftp exec -d COMx --no-follow "$(cat cpfiles_discovery.py)"`` or copy it
over; the board restarts at once. Then ``cpfiles_client.py`` on a laptop.
"""
import memorymap
import microcontroller
import os
import struct

# RTC_CNTL_STORE0_REG: DR_REG_RTCCNTL_BASE (0x60008000) + 0x50, on the ESP32-S3.
STORE0 = {"esp32s3": 0x60008050}
# BLE_DISCOVERY_DATA_GUARD with a mode of 1, as the supervisor writes it.
MARKER = 0xBB0000BB | (1 << 8)

chip = os.uname().sysname.lower()  # "ESP32S3"
if chip not in STORE0:
    raise RuntimeError("no saved-word register known for " + chip)
register = memorymap.AddressRange(start=STORE0[chip], length=4)
register[0:4] = struct.pack("<I", MARKER)
microcontroller.reset()
