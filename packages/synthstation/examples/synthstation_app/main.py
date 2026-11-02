# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Run Synth Station as an appkit app.

appkit finds the one app in apps/, which hands its scope to
synthstation.main(). Pick an instrument, play it from a MIDI keyboard, and
turn its knobs on the panel; EXIT goes back to the list. With no keyboard,
the panel's first bank of pads plays notes. On a desktop the window opens
at WIDTH x HEIGHT; on a board the app fills the board's own screen.

Needs: appkit, synthstation, controlpanel, audioinstruments and audiodsp,
pydevices' appdev, LVGL with a board_config that has a display and an audio
out, and midiports for the keyboard.

Run it from this folder:

    micropython main.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window, and MicroPython 1.30 and CPython 3.14 on Windows.
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

# Run Synth Station on its own, with no home screen.
appkit.run("synthstation")
