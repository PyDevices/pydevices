"""Waveshare ESP32-P4-WIFI6-DEV-KIT with a KeDei 5" DSI display (800x480) - CircuitPython

The same panel and the same settings as the MicroPython config in
fbdisplay/esp32-p4-wifi6-dev-kit_kedei-5in-dsi; its docstring has the story.
In short: a Raspberry Pi-style panel whose own microcontroller (I2C 0x45)
powers it and sets up a Chipone ICN6211 DSI-to-RGB bridge, which needs
non-burst video and a continuous HS clock on one lane, or the panel stays
white. That controller acknowledges every I2C address, so a scan of this bus
lists them all. Touch is a FocalTech part at 0x38.

Needs a CircuitPython-compatible build whose mipidsi.Display takes
non_burst and continuous_clock (micropython-pydevices' CircuitPython
patches). The board's other devices come from board_peripherals.
"""

import time

import displayio
import framebufferio
import mipidsi
import supervisor
from ft6x36 import FT6x36

import board_peripherals
from displaydev.fbdisplay import FBDisplay

displayio.release_displays()

PANEL_CTRL = 0x45  # the panel's microcontroller
_POWERON = 0x85
_PWM = 0x86

i2c = board_peripherals.i2c()
_regs = board_peripherals._I2CMem(i2c)

# Panel off while the DSI link starts; the controller configures the bridge
# when it powers the panel, and that wants the clock already running.
_regs.writeto_mem(PANEL_CTRL, _POWERON, b"\x00")
time.sleep(0.3)

display_bus = mipidsi.Bus(frequency=528_000_000, num_lanes=1)

fb = mipidsi.Display(
    display_bus,
    b"",
    width=800,
    height=480,
    color_depth=16,
    pixel_clock_frequency=33_000_000,  # 16 bits x 33 MHz = 528 Mbps on one lane
    hsync_front_porch=46,
    hsync_pulse_width=20,
    hsync_back_porch=210,
    vsync_front_porch=22,
    vsync_pulse_width=10,
    vsync_back_porch=23,
    non_burst=True,
    continuous_clock=True,
)

_regs.writeto_mem(PANEL_CTRL, _POWERON, b"\x01")
time.sleep(0.3)
_regs.writeto_mem(PANEL_CTRL, _PWM, b"\xff")  # backlight, 0-255

# Paint into a Bitmap that the FramebufferDisplay composites onto the panel,
# the Qualia path (cp/fbdisplay/esp32-s3-touch-lcd-7 does the same). Our group
# is the root group, so the REPL isn't shown here while an app runs; set
# display.root_group = displayio.CIRCUITPYTHON_TERMINAL to see it.
display = framebufferio.FramebufferDisplay(fb, auto_refresh=True)
_bitmap = displayio.Bitmap(800, 480, 65535)
_group = displayio.Group()
_group.append(
    displayio.TileGrid(
        _bitmap,
        pixel_shader=displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565),
    )
)
display.root_group = _group
# Nor the status line: drawing it on the panel stalls audio the same way.
supervisor.status_bar.display = False

display_drv = FBDisplay(fb, bitmap=_bitmap, display=display)

touch = FT6x36(_regs, address=0x38)
# The touch panel reads 180 degrees from the display: the default table
# shifted by two rotations.
touch_rotation_table = (0b110, 0b011, 0b000, 0b101)

touch_read = touch.read_points
