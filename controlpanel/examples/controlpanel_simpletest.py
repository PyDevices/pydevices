# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show the control panel on the screen against a stand-in instrument.

Builds the panel over controlpanel's mock adapter: 40 patches in three
banks and sixteen macros. Press a pad and every encoder moves to the patch;
drag an encoder up or down, or click it and use the wheel, and the display
shows the value. Each edit the panel makes is printed.

Needs: LVGL and a board_config with a display, which a PyDevices board
package or pydevices-desktop provides.

Run it:

    micropython controlpanel_simpletest.py

Tested on: the unix port of MicroPython and CPython 3.12 on Linux, each in
an SDL window.
"""

from display_driver import app  # noqa: F401  (opens the display and LVGL)

import controlpanel
from controlpanel.mock import MockAdapter


# Print every edit the panel publishes, the way an engine would receive it.
class PrintingAdapter(MockAdapter):
    def set_macro(self, index, value):
        super().set_macro(index, value)
        print("macro", index, value)

    def set_patch(self, index):
        super().set_patch(index)
        print("patch", index, self.patches[index])


# Build the panel on the active screen. It runs until you close the window.
panel = controlpanel.build(PrintingAdapter())
app.run()
