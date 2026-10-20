# The ili9341_eyespi_qtpy_rp2040 board package: what mip.install("ili9341_eyespi_qtpy_rp2040") brings.
metadata(
    description="QT Py RP2040 with EyeSPI and ILI9341 2.8\" display",
    version="0.1",
)

require("pydevices")
require("ili9341")
require("ft6x36")

module("board_config.py")
