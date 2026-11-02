# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Choose from a list with a joystick or a D-pad.

Shows a pdwidgets list of three items and moves the highlight up and down
when the joystick's hat or D-pad moves.

Needs: a board_config with a display_drv and a joystick, which a PyDevices
board package or pydevices-desktop provides, appdev and pdwidgets.

Run it from pydevices' pdwidgets folder:
    python examples/joystick_list_select.py

Tested on: CPython 3.12 on Linux, in an SDL window.
"""

import board_config
import appdev
import pdwidgets as pd

app = appdev.App(board_config)

display = pd.Display(board_config.display_drv, app,40)
screen = pd.Screen(display, visible=False)

top, bottom, main = screen.top, screen.bottom, screen.main

pd.Label(top,value="Select an Item")

list_view = pd.ListView(main, w=int(main.width * .9), h=int(main.height * .9), align=pd.ALIGN.CENTER)

items = [pd.Label(list_view,value=i) for i in ["Item 1", "Item 2", "Item 3"]]
selected = 0
items[selected].bg = list_view.color_theme.secondary

screen.visible = True



def select_item(up: bool):
    global selected
    if up and selected > 0:
        selected -= 1
    elif not up and selected < len(items) - 1:
        selected += 1
    for i in items:
        i.bg = list_view.color_theme.secondary if i == items[selected] else list_view.color_theme.transparent
    list_view.invalidate()

def joystick_callback(event):
    if event.type == pd.events.JOYHATMOTION:
        if event.hat == 0:
            if event.value[1] != 0:
                select_item(event.value[1] > 0)

app.on(pd.events.JOYHATMOTION, joystick_callback)
