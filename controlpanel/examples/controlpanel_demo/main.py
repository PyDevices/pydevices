# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run the control panel as an appkit app.

appkit finds the one app in apps/, which hands its scope to
controlpanel.main(). That builds the panel against the mock adapter, and
appkit takes it down again, timer and all, when the app closes. On a desktop
the window opens in landscape at WIDTH x HEIGHT, the plug-in editor's size;
on a board the panel fills the board's own screen.

Needs: appkit, controlpanel, pydevices' appdev, and LVGL with a
board_config that has a display.

Run it from this folder:

    micropython main.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

import sys

from boarddev import env_get, env_set

# Change these to match your setup.
WIDTH = 800
HEIGHT = 480

# On a desktop, ask for a landscape window before anything opens the display.
# A size already in the environment wins, and a board keeps its own screen.
if getattr(sys, "platform", "") in ("linux", "darwin", "win32") and not env_get("PYDEVICES_WIDTH"):
    env_set("PYDEVICES_WIDTH", WIDTH)
    env_set("PYDEVICES_HEIGHT", HEIGHT)

import appkit  # noqa: E402

# Run the controlpanel app on its own, with no home screen.
appkit.run("controlpanel")
