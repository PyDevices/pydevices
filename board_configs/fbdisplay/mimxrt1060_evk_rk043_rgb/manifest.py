# The mimxrt1060_evk_rk043_rgb board package: what mip.install("mimxrt1060_evk_rk043_rgb") brings.
metadata(
    description="NXP MIMXRT1060-EVK + RK043FN66HS-CTG 4.3\" parallel RGB - MicroPython",
    version="0.1",
)

require("pydevices")
require("gt911")

module("board_config.py")
