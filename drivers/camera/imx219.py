# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Sony IMX219: the Raspberry Pi Camera Module v2 and its clones, for cameraif.

    import cameraif
    from imx219 import SENSOR

    cam = cameraif.Camera(7, 8, i2c=1, reset=21, sensor=SENSOR)

The sensor is data, not code: cameraif reads this description and drives the
chip from it, so a camera needs a file like this one and no firmware build.

Registers and PLL settings follow Zephyr's IMX219 driver
(drivers/video/imx219.c, Apache-2.0, copyright Circuit Valley and
tinyVision.ai), which is also where the digital gain, the pedestal, the test
pattern menu, RAW8 and the 15 fps mode come from. The module carries its own
24 MHz oscillator, so no XCLK is driven. Two CSI-2 lanes at 400 Mbit/s each;
the pixel rate is 120 Mpixel/s, and a frame lasts LINE_LENGTH x frame length
pixel clocks. One mode runs Zephyr's faster clocks instead (912 Mbit/s a
lane, 182.4 Mpixel/s).

Besides exposure and analogue gain it has two controls, set as attributes of
the camera: `digital_gain` (8.8 fixed point, 256 is x1) and `brightness`, the
data-type pedestal added to every pixel in 10-bit steps. `test_pattern(n)`
takes a number from 0 to 9, listed in `TEST_PATTERNS`.

The IMX219 has no exposure control of its own, so cameraif's auto-exposure
runs it. The tuning at the end was made on an ESP32-P4 panel indoors.
"""

LINE_LENGTH = 3448  # pixel clocks per line, blanking included
FULL = (3280, 2464)  # the pixel array

# Unlock 0x3000-0x5fff, then the vendor's undocumented settings, then the
# clocks. (None, ms) waits.
_INIT = [
    (0x0103, 0x01), (None, 6),  # software reset
    (0x30EB, 0x05), (0x30EB, 0x0C), (0x300A, 0xFF), (0x300B, 0xFF),
    (0x30EB, 0x05), (0x30EB, 0x09),
    (0x455E, 0x00), (0x471E, 0x4B), (0x4767, 0x0F), (0x4750, 0x14),
    (0x4540, 0x00), (0x47B4, 0x14), (0x4713, 0x30), (0x478B, 0x10),
    (0x478F, 0x10), (0x4793, 0x10), (0x4797, 0x0E), (0x479B, 0x0E),
    (0x0114, 0x01),  # two lanes
    (0x0128, 0x00),  # D-PHY timing automatic
    (0x012A, 0x18), (0x012B, 0x00),  # INCK 24 MHz
    (0x0162, LINE_LENGTH >> 8), (0x0163, LINE_LENGTH & 0xFF),
    (0x0170, 0x01), (0x0171, 0x01),  # odd increments
    # PLL: VT 24 / 3 x 30 = 240 MHz, / 4 = 60 MHz (120 Mpixel/s); OP 24 / 3 x
    # 50 = 400 Mbit/s a lane, / 10 for RAW10.
    (0x0301, 0x04), (0x0303, 0x01), (0x0304, 0x03), (0x0305, 0x03),
    (0x0306, 0x00), (0x0307, 30), (0x0309, 10), (0x030B, 0x01),
    (0x030C, 0x00), (0x030D, 50),
    (0x018C, 10), (0x018D, 10),  # RAW10
    (0x0158, 0x01), (0x0159, 0x00),  # digital gain x1
]  # fmt: skip


# What test_pattern(n) shows, by n. 0 is off and 1 is the colour bars that
# test_pattern(True) shows; the rest are the sensor's, in Zephyr's order.
TEST_PATTERNS = (
    "off", "colour bars", "solid colour", "fade to grey colour bars", "PN9",
    "16-split colour bars", "16-split inverted colour bars", "column counter",
    "inverted column counter", "PN31",
)
_TEST_PATTERN_REGS = (0, 2, 1, 3, 4, 5, 6, 7, 8, 9)  # what 0x0600 takes for each


def _u16(reg, value):
    return [(reg, value >> 8), (reg + 1, value & 0xFF)]


# The clocks Zephyr's driver uses: VT 24 / 3 x 57 / 5 = 91.2 MHz (182.4
# Mpixel/s) and OP 24 / 3 x 114 = 912 Mbit/s a lane. Written over the init
# list's, they read 1280x960 out at 53 fps; the 1640x1232 and 1920x1080 modes
# give no frames at all on them on an ESP32-P4.
_FAST_PLL = [(0x0301, 5), (0x0307, 57), (0x030D, 114)]


def _mode(name, fps, x, y, width, height, binned, frame_length, bits=10, fast=False):
    """A window on the array, read out at width x height (half the window when binned)."""
    w, h = (width * 2, height * 2) if binned else (width, height)
    regs = (
        _u16(0x0164, x) + _u16(0x0166, x + w - 1)
        + _u16(0x0168, y) + _u16(0x016A, y + h - 1)
        + _u16(0x016C, width) + _u16(0x016E, height)
        + [(0x0174, int(binned)), (0x0175, int(binned))]
        + _u16(0x0160, frame_length)
        + _u16(0x0624, width) + _u16(0x0626, height)  # the test pattern's window
        # The init list says 10. The output pixel clock divider takes the bit
        # depth too: left at 10, RAW8 frames come out as stripes.
        + ([(0x018C, bits), (0x018D, bits), (0x0309, bits)] if bits != 10 else [])
        + (_FAST_PLL if fast else [])
    )  # fmt: skip
    return {
        "name": name, "width": width, "height": height, "fps": fps,
        "format": "raw%d" % bits, "bayer": "RGGB", "lanes": 2, "lane_hz": 912_000_000 if fast else 400_000_000,
        "pclk": 182_400_000 if fast else 120_000_000, "hts": LINE_LENGTH, "vts": frame_length, "regs": regs,
    }  # fmt: skip


SENSOR = {
    "name": "IMX219",
    "addr": 0x10,
    "reg_bits": 16,
    "id": (0x0000, 0x0219),  # chip ID, in this register and the next
    "init": _INIT,
    "modes": [
        # 4:3 from the middle 2560x1920, binned 2x2: about 35 fps
        _mode("1280x960", 35, 360, 272, 1280, 960, True, 980),
        # the whole array, binned 2x2: about 28 fps
        _mode("1640x1232", 28, 0, 0, 1640, 1232, True, 1252),
        # 16:9 from the middle, unbinned: about 30 fps
        _mode("1920x1080", 30, 680, 692, 1920, 1080, False, 1100),
        # the first mode again, as 8-bit pixels: a fifth less on the link
        _mode("1280x960 RAW8", 35, 360, 272, 1280, 960, True, 980, bits=8),
        # the 1080p window at half the rate: 120 Mpixel/s / (3448 x 2320) is 15
        # fps, and exposure can run twice as long
        _mode("1920x1080 15fps", 15, 680, 692, 1920, 1080, False, 2320),
        # the first mode on Zephyr's clocks: 182.4 Mpixel/s / (3448 x 992)
        _mode("1280x960 53fps", 53, 360, 272, 1280, 960, True, 992, fast=True),
    ],
    "stream": ([(0x0100, 0x01)], [(0x0100, 0x00)]),
    # (register, bytes, minimum, maximum, default); a maximum of -4 is the
    # mode's frame length less 4 lines, a default of None the maximum.
    "exposure": (0x015A, 2, 1, -4, None),
    "controls": {
        "digital_gain": (0x0158, 2, 0, 4095, 256),  # 8.8 fixed point, 256 is x1
        "brightness": (0xD1EA, 2, 0, 1023, 64),  # the data-type pedestal, 10-bit steps; 64 at power-up
    },
    "gain": (0x0157, 1, 0, 232, 128),  # analogue: 256 / (256 - code), x1 to x10.7
    "flip": (0x0172, 0x02, 0x01),  # register, vertical bit, horizontal bit
    # register, bytes, colour bars, off, and the values test_pattern(n) writes
    "test_pattern": (0x0600, 2, 2, 0, _TEST_PATTERN_REGS),
    # Tuning.
    "auto_exposure": True,
    # In 8-bit steps. 64 of 1023 at low gain, but nearer 48 at the gain an
    # indoor room needs; 16 there tints every dark tone yellow.
    "black_level": 12,
    "gamma": 0.5,
    # Raspberry Pi's measured matrix for 3600 K light (libcamera's
    # imx219.json), 60:40 with identity. At full strength a highlight the
    # sensor clips turns magenta on a P4 before revision 3, where the white
    # balance has to ride in this matrix.
    "ccm": (
        1.712, -0.397, -0.315,
        -0.467, 2.017, -0.550,
        -0.151, -0.499, 1.650,
    ),  # fmt: skip
}
