# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Reach the board's REPL over Bluetooth, behind a password.

The board advertises its REPL over Bluetooth LE, the way WebREPL does over
Wi-Fi. A computer that knows the password logs in, runs code on the board and
reads what it prints. ``start()`` returns at once, and the board keeps serving
the REPL while your program runs.

Needs: a board with Bluetooth LE, running MicroPython with bledev. On your
computer, mpftp with bleak.

Run it:

    mpremote run bledev_repl_simpletest.py

Then, from your computer:

    MPFTP_BLE_PASSWORD="correct horse" mpftp eval "1 + 1" -d ble://PyDevices-REPL

Success is the answer 2. To keep the REPL on after a reset, copy the file to
the board as main.py. A password sent over Bluetooth isn't encrypted, so pick
one you use nowhere else.

Tested on: Waveshare ESP32-S3 Touch LCD 7 on MicroPython 1.30 preview,
reached by mpftp with bleak 3.0 on Windows: the eval answered 2.
"""

import bledev.repl

# Change these to match your setup.
PASSWORD = "correct horse"
NAME = "PyDevices-REPL"

# Start serving. The REPL owns the radio until you call bledev.repl.stop().
bledev.repl.start(password=PASSWORD, name=NAME)
print("The REPL is on Bluetooth as", NAME)
