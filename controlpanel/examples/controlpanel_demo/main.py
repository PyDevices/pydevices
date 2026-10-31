# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run the control panel as an appkit app.

appkit finds the one app in apps/, which hands its scope to
controlpanel.main(). That builds the panel against the mock adapter, and
appkit takes it down again, timer and all, when the app closes.

Needs: appkit, controlpanel, pydevices' appdev, and LVGL with a
board_config that has a display.

Run it from this folder:

    micropython main.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

import appkit

# Run the controlpanel app on its own, with no home screen.
appkit.run("controlpanel")
