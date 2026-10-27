#!/usr/bin/env python3
"""Redraw docs/images/pdwidgets.png: the README example after three taps.

Needs pydevices-desktop (for ``board_config``) and Pillow. Run it headless:

    SDL_VIDEODRIVER=dummy PYTHONPATH=lib python scripts/generate_readme_screenshot.py

The example below is the one in README.md. The script sends three
press-and-release pairs to the button through ``Display.handle_event``, the
same entry point the app uses for real input, then reads the window back.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import appdev
import board_config
import events
import pdwidgets as pd
from PIL import Image

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

label = pd.Label(screen, value="Taps: 0", align=pd.ALIGN.TOP, y=40, bg=screen.bg)
button = pd.Button(screen, label="Tap me", align=pd.ALIGN.CENTER, w=160, h=50)
taps = 0


def on_tap(sender, event):
    global taps
    taps += 1
    label.value = f"Taps: {taps}"
    print(label.value)


button.add_event_cb(pd.events.MOUSEBUTTONUP, on_tap)

pd.tick()
pos = (button.x + button.width // 2, button.y + button.height // 2)
for _ in range(3):
    for kind in (events.MOUSEBUTTONDOWN, events.MOUSEBUTTONUP):
        display.handle_event(SimpleNamespace(type=kind, pos=pos, button=1))
    pd.tick()
    pd.tick()

rgb, w, h = board_config.display_drv.capture_rgb()
out = Path(__file__).resolve().parent.parent / "docs" / "images" / "pdwidgets.png"
out.parent.mkdir(parents=True, exist_ok=True)
# The window is scaled to fit the desktop; save it at the panel's own size.
Image.frombytes("RGB", (w, h), rgb).resize((display.width, display.height), Image.LANCZOS).save(out)
print("Saved", out)
# The app keeps its timers alive past the end of the script; leave now.
os._exit(0)
