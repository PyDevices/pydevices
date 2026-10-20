# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A sample app set's main.py, as a user writes it, plus the test's autopilot.

Run it under the supervisor, from this folder::

    python -m appkit.launcher -- micropython main.py

``tests/test_scripts.py`` does, and reads what ``autopilot`` logged.
"""

import autopilot

autopilot.plant()  # a planted fault, when the test asks for one

import appkit

autopilot.watch()  # drives the home screen once run() has it up

try:
    appkit.run()  # ends in the foreground loop, until the program quits
except Exception as exc:
    autopilot.crash(exc)  # logs it and ends the program
