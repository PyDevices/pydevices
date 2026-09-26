"""
Board configuration for PyScript.
"""

from displaydev import env_int
from displaydev.psdisplay import PSDisplay

width = 320
height = 480

width = env_int("PYDEVICES_WIDTH", width)
height = env_int("PYDEVICES_HEIGHT", height)

display_drv = PSDisplay("display_canvas", width, height)

host_read = display_drv.get_events

display_drv.fill(0)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())
