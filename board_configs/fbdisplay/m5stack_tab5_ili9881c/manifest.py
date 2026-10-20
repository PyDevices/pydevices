# The m5stack_tab5_ili9881c board package: what mip.install("m5stack_tab5_ili9881c") brings.
metadata(
    description="M5Stack Tab5 (ILI9881C + GT911) - MicroPython",
    version="0.3",
)

require("pydevices")
require("gt911")
require("pi4ioe5v")
require("tab5_ili9881c_init")
require("es7210")
require("es8388")

module("board_config.py")
module("board_peripherals.py")
