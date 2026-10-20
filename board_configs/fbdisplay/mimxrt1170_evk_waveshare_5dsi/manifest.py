# The mimxrt1170_evk_waveshare_5dsi board package: what mip.install("mimxrt1170_evk_waveshare_5dsi") brings.
metadata(
    description="NXP MIMXRT1170-EVK + Waveshare 50H-800480-IPS DSI (800x480) on J84 - MicroPython",
    version="0.1",
)

require("pydevices")
require("gt911")

module("board_config.py")
