# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The REPL gate, board side: start ``bledev.repl`` as ``bledev-repl`` and return.

Run it with ``mpftp exec`` (or ``run``) and leave the board at its REPL; the
REPL keeps being served over BLE. ``repl_client.py`` then checks it from a
laptop or another board. The password is a test value, not a secret.

``PLANT = True`` makes the board accept any password, which the client must
catch.
"""
import bledev.repl

PASSWORD = "bledev-gate-pw"
PLANT = False

if PLANT:
    bledev.repl._check_password = lambda given, want: True
bledev.repl.start(password=PASSWORD, name="bledev-repl")
print("bledev.repl serving as bledev-repl, plant", PLANT)
