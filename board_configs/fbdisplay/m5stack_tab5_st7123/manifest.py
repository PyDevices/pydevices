# The m5stack_tab5_st7123 board package: what mip.install("m5stack_tab5_st7123") brings.
metadata(
    description="M5Stack Tab5 (ST7123 TDDI) - MicroPython",
    version="0.3",
)

require("pydevices")
require("st7123")
require("pi4ioe5v")
require("tab5_st7123_init")
require("es7210")
require("es8388")

module("board_config.py")
module("board_peripherals.py")
