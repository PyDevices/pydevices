"""
Board configuration for Python running in a Web Worker.

The page transfers its canvas to the worker as an ``OffscreenCanvas`` and
sets it on the worker's global scope as ``display_canvas`` before this runs;
see ``displaydev.workerdisplay`` for the page side and the input relay.
"""

from boarddev import env_int
from displaydev.workerdisplay import WorkerDisplay
from js import display_canvas

width = env_int("PYDEVICES_WIDTH", int(display_canvas.width))
height = env_int("PYDEVICES_HEIGHT", int(display_canvas.height))

display_drv = WorkerDisplay(display_canvas, width, height)

host_read = display_drv.get_events

display_drv.fill(0)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())
