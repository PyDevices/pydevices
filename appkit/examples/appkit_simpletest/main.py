# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run two apps from a home screen and switch between them with appkit.

The two apps are the folders in apps/: a counter that ticks once a second,
and a greeter with a button. appkit.run() finds them, shows a home screen
with a button for each, and closes one app completely before it opens the
next, so each app gets back the memory the last one used.

Needs: appkit, pydevices' appdev, and LVGL with a board_config that has a
display, which a PyDevices board package or pydevices-desktop provides.

Run it from this folder:
    micropython main.py

On a board, copy main.py and the apps folder to the board's root.

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

import appkit

# A home screen with a button for each app in ./apps. It runs until you
# close the window or reset the board.
appkit.run()
