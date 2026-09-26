"""
Board configuration for Jupyter Notebook.
"""

from displaydev.jndisplay import JNDisplay

width = 320
height = 480

display_drv = JNDisplay(width, height)

host_read = display_drv.get_events

display_drv.fill(0)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())
