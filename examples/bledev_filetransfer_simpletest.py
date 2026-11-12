# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Copy files to and from the board over Bluetooth.

The board serves CircuitPython's Bluetooth file-transfer protocol, so any
client that speaks it, CircuitPython's own included, can list, read, write
and delete the board's files behind a password. The REPL is served beside it.
``start()`` returns at once, and the board keeps serving while your program
runs.

Needs: a board with Bluetooth LE, running MicroPython with bledev. On your
computer, mpftp with bleak.

Run it:

    mpremote run bledev_filetransfer_simpletest.py

Then, from your computer:

    MPFTP_BLE_PASSWORD="correct horse" mpftp ls / -d ble://PyDevices-Files

Success is the board's files listed. The same address takes ``put``, ``get``
and ``rm``. To keep it on after a reset, copy this file to the board as
main.py. A password sent over Bluetooth isn't encrypted, so pick one you use
nowhere else.

Tested on: Waveshare ESP32-S3 Touch LCD 7 on MicroPython 1.30 preview,
reached by mpftp with bleak 3.0 on Windows: it listed the board's files.
"""

import bledev.filetransfer

# Change these to match your setup.
PASSWORD = "correct horse"
NAME = "PyDevices-Files"

# Start serving files and the REPL. They own the radio until you call
# bledev.filetransfer.stop().
bledev.filetransfer.start(password=PASSWORD, name=NAME)
print("Files are on Bluetooth as", NAME)
