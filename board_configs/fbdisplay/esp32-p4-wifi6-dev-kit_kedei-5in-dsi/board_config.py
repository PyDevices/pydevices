"""Waveshare ESP32-P4-WIFI6-DEV-KIT with a KeDei 5" DSI display (800x480) - MicroPython

The display is a Raspberry Pi-style DSI panel: a Chipone ICN6211 DSI-to-RGB
bridge that the panel's own microcontroller configures, so nothing here writes
to the bridge. That controller sits at I2C 0x45 and speaks the official Pi
display's protocol (0x85 powers the panel, 0x86 sets the backlight). It also
acknowledges every I2C address, so an I2C scan of this bus is meaningless. The
touch controller is a FocalTech part at 0x38.

What the bridge needs, found on the bench (2026-10-06): non-burst video with
sync pulses and a continuous HS clock, one lane, and the timing it holds in its
own registers (0x20-0x29). Without non_burst/continuous_clock the panel stays
white; with Linux's TC358762 timing the picture shears.
"""

import time

from ft6x36 import FT6x36
from keypad_gpio import GPIOButtons
from machine import I2C, Pin

from displaydev.fbdisplay import FBDisplay
import keys

try:
    from mipidsi import Bus, Display
except ImportError as exc:
    raise NotImplementedError("MIPI DSI requires displayif mipidsi cmod (esp32p4 port)") from exc

I2C_SCL = 8
I2C_SDA = 7
PANEL_CTRL = 0x45  # the panel's microcontroller
_POWERON = 0x85
_PWM = 0x86

i2c = I2C(1, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=100_000)

# Panel off while the DSI link starts; the controller configures the bridge
# when it powers the panel, and that wants the clock already running.
i2c.writeto_mem(PANEL_CTRL, _POWERON, b"\x00")
time.sleep_ms(300)

display_bus = Bus(frequency=528_000_000, num_lanes=1, ldo_chan=3, ldo_voltage_mv=2500)

fb = Display(
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

i2c.writeto_mem(PANEL_CTRL, _POWERON, b"\x01")
time.sleep_ms(300)
i2c.writeto_mem(PANEL_CTRL, _PWM, b"\xff")  # backlight, 0-255

touch = FT6x36(i2c, address=0x38)
# The touch panel reads 180 degrees from the display: the default table
# shifted by two rotations.
touch_rotation_table = (0b110, 0b011, 0b000, 0b101)

display_drv = FBDisplay(fb)

touch_read = touch.read_points

# Active-low BOOT button; GPIO35 is shared with Ethernet TXD1, so don't use
# it with ethernet(). appdev turns it into ordinary key events.
keypad = GPIOButtons({"boot": (Pin(35, Pin.IN, Pin.PULL_UP), keys.K_LCTRL)})
keypad_read = keypad.read

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())
