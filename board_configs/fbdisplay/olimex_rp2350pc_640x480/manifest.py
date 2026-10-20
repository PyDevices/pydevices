# The olimex_rp2350pc_640x480 board package: what mip.install("olimex_rp2350pc_640x480") brings.
metadata(
    description="Olimex RP2350pc onboard mini-HDMI (HSTX) 640x480 - MicroPython",
    version="0.1",
)

require("pydevices")

module("board_config.py")
module("board_peripherals.py")
