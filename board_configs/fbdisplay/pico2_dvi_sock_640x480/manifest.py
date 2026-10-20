# The pico2_dvi_sock_640x480 board package: what mip.install("pico2_dvi_sock_640x480") brings.
metadata(
    description="Raspberry Pi Pico 2 + Adafruit DVI Sock or PiCowbell HSTX (640x480)",
    version="0.2",
)

require("pydevices")

module("board_config.py")
module("board_peripherals.py")
