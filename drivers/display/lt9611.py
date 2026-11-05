# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""Send a MIPI DSI display out over HDMI through a Lontium LT9611 bridge.

The bridge is set up entirely over I2C, so `LT9611` has nothing to do with the
pixels: start the DSI video first (`mipidsi.Display` on ESP32-P4), then call
`LT9611.start` with the same timing. Video must already be running when the
bridge starts, because it measures the incoming clock.

Tell the bridge the pixel clock the host really produces, not the one you
asked for. An ESP32-P4 divides a fixed source by a whole number, so asking for
148.5 MHz gets 120 or 160 MHz. Pad the horizontal blanking to land on the
refresh rate you want.

The register sequence is Espressif's ``esp_lcd_lt9611`` component (esp-bsp),
ported from C. That component is Apache-2.0 licensed, and so is this file. It
expects straight wiring into port A. ``port="B"`` uses the Kendryte K230 SDK's
values for LCKFB's MIPI-to-HDMI board, whose lanes are reordered and partly
swapped in polarity: those values are for that wiring, not for port B in
general, and the SDK only uses them with four lanes. Running them with two
hasn't been tried. This driver doesn't set up audio yet.

Example:
    fb = Display(bus, b"", width=1920, height=1080, ...)
    hdmi = LT9611(i2c, width=1920, height=1080, pixel_clock=80_000_000, ...)
    hdmi.start()
"""

import time

_PAGE = 0xFF


class LT9611:
    """One LT9611 bridge on an I2C bus.

    Args:
        i2c: A bus with ``writeto_mem`` and ``readfrom_mem``.
        width (int): Active pixels per line.
        height (int): Active lines per frame.
        pixel_clock (int): The pixel clock the DSI host really produces, in Hz.
        hsync_front_porch (int): Pixels.
        hsync_pulse_width (int): Pixels.
        hsync_back_porch (int): Pixels.
        vsync_front_porch (int): Lines.
        vsync_pulse_width (int): Lines.
        vsync_back_porch (int): Lines.
        lanes (int): DSI data lanes, 2 or 4.
        port (str): ``"A"`` for straight wiring into port A, ``"B"`` for LCKFB's board.
        vic (int): CEA video code to announce, or 0 for a mode that isn't one.
        hsync_active_low (bool): HDMI sync polarity.
        vsync_active_low (bool): HDMI sync polarity.
        address (int): The bridge's 7-bit I2C address.

    Raises:
        ValueError: If `lanes` or `port` isn't one of the values above.
    """

    def __init__(
        self,
        i2c,
        *,
        width,
        height,
        pixel_clock,
        hsync_front_porch,
        hsync_pulse_width,
        hsync_back_porch,
        vsync_front_porch,
        vsync_pulse_width,
        vsync_back_porch,
        lanes=2,
        port="A",
        vic=0,
        hsync_active_low=False,
        vsync_active_low=False,
        address=0x3B,
    ):
        if lanes not in (2, 4):
            raise ValueError("lanes must be 2 or 4")
        if port not in ("A", "B"):
            raise ValueError("port must be 'A' or 'B'")
        self._i2c = i2c
        self._address = address
        self._width = width
        self._height = height
        self._pclk_khz = (pixel_clock + 500) // 1000
        self._hfp = hsync_front_porch
        self._hs = hsync_pulse_width
        self._hbp = hsync_back_porch
        self._vfp = vsync_front_porch
        self._vs = vsync_pulse_width
        self._vbp = vsync_back_porch
        self._lanes = lanes
        self._port = port
        self._vic = vic
        self._hsync_active_low = hsync_active_low
        self._vsync_active_low = vsync_active_low
        self._page = None

    def _write(self, reg, value):
        page = reg >> 8
        if page != self._page:
            self._i2c.writeto_mem(self._address, _PAGE, bytes((page,)))
            self._page = page
        self._i2c.writeto_mem(self._address, reg & 0xFF, bytes((value & 0xFF,)))

    def _read(self, reg):
        page = reg >> 8
        if page != self._page:
            self._i2c.writeto_mem(self._address, _PAGE, bytes((page,)))
            self._page = page
        return self._i2c.readfrom_mem(self._address, reg & 0xFF, 1)[0]

    def _write_all(self, pairs):
        for reg, value in pairs:
            self._write(reg, value)

    def start(self):
        """Program the bridge and turn on its HDMI output.

        Call this once DSI video is running. It takes about half a second, most
        of it waiting for the bridge's PLLs to settle.
        """
        # After a reset the chip's page register isn't what we last wrote.
        self._page = None
        self._write(0x80EE, 0x01)  # enable register access
        self._mipi_digital()
        postdiv = self._pll()
        self._video()
        self._pcr(postdiv)
        self._power_on()
        self._mipi_analog()
        self._avi_infoframe()
        self._write_all(((0x82D6, 0x8C), (0x82D7, 0x04)))
        self._hdmi_phy()
        time.sleep(0.5)
        self._write(0x8130, 0xEA)

    def enable(self, on):
        """Turn the HDMI output on or off, leaving the bridge configured."""
        self._write(0x8130, 0xEA if on else 0x6A)

    @property
    def connected(self):
        """True when a monitor is asserting HDMI hot-plug detect."""
        return (self._read(0x825E) & 0x05) != 0

    def _mipi_digital(self):
        lanes = 0x02 if self._lanes == 2 else 0x00
        if self._port == "A":
            self._write(0x8300, lanes)
        else:
            self._write(0x8300, 0x60 | lanes)
        self._write(0x830A, 0x00)
        self._write(0x824F, 0x80)
        if self._port == "A":
            self._write_all(((0x8250, 0x10), (0x8303, 0x00)))
        else:
            self._write_all(((0x8250, 0x14), (0x8303, 0x4F), (0x8304, 0x00), (0x8307, 0x40)))
        self._write_all(((0x8302, 0x0A), (0x8306, 0x0A)))

    def _pll(self):
        self._write_all(
            (
                (0x8123, 0x40),
                (0x8124, 0x64),
                (0x8125, 0x80),
                (0x8126, 0x55),
                (0x812C, 0x37),
                (0x812F, 0x01),
                (0x8126, 0x55),
                (0x8127, 0x66),
                (0x8128, 0x88),
                (0x812A, 0x20),
            )
        )
        pclk = self._pclk_khz
        if pclk > 150000:
            self._write(0x812D, 0x88)
            postdiv = 1
        elif pclk > 70000:
            self._write(0x812D, 0x99)
            postdiv = 2
        else:
            self._write(0x812D, 0xAA)
            postdiv = 4
        self._write_all(
            (
                (0x82E3, pclk >> 17),
                (0x82E4, pclk >> 9),
                (0x82E5, pclk >> 1),
                (0x82DE, 0x20),
                (0x82DE, 0xE0),
                (0x8016, 0xF1),
                (0x8016, 0xF3),
            )
        )
        return postdiv

    def _video(self):
        htotal = self._width + self._hs + self._hbp + self._hfp
        vtotal = self._height + self._vs + self._vbp + self._vfp
        hporch = self._hs + self._hbp
        self._write_all(
            (
                (0x830D, vtotal >> 8),
                (0x830E, vtotal),
                (0x830F, self._height >> 8),
                (0x8310, self._height),
                (0x8311, htotal >> 8),
                (0x8312, htotal),
                (0x8313, self._width >> 8),
                (0x8314, self._width),
                (0x8315, self._vs),
                (0x8316, self._hs),
                (0x8317, self._vfp),
                (0x8318, self._vs + self._vbp),
                (0x8319, self._hfp),
                (0x831A, (hporch >> 8) | ((self._hfp >> 8) << 4)),
                (0x831B, hporch),
            )
        )

    def _pcr(self, postdiv):
        polarity = 0x10
        if self._hsync_active_low:
            polarity |= 0x02
        if self._vsync_active_low:
            polarity |= 0x01
        self._write_all(
            (
                (0x830B, 0x01),
                (0x830C, 0x10),
                (0x8348, 0x00),
                (0x8349, 0x81),
                (0x8321, 0x4A),
                (0x8324, 0x71),
                (0x8325, 0x30),
                (0x832A, 0x01),
                (0x834A, 0x40),
                (0x832D, 0x38),
                (0x8331, 0x08),
                (0x831D, polarity),
                (0x8326, self._pclk_khz * 5 * postdiv // 27000),
                (0x8011, 0x5A),
                (0x8011, 0xFA),
            )
        )

    def _power_on(self):
        self._write_all(
            (
                (0x8101, 0x18),
                (0x821B, 0x69),
                (0x821C, 0x78),
                (0x82CB, 0x69),
                (0x82CC, 0x78),
                (0x8251, 0x01),
                (0x8258, 0x0A),
                (0x8259, 0x80),
                (0x829E, 0xF7),
                (0x8004, 0xF0),
                (0x8006, 0xF0),
                (0x800A, 0x80),
                (0x800B, 0x40),
                (0x800D, 0xEF),
                (0x8011, 0xFA),
            )
        )

    def _mipi_analog(self):
        self._write_all(
            (
                (0x8106, 0x40),
                (0x810A, 0xFE),
                (0x810B, 0xBF),
                (0x8111, 0x40),
                (0x8115, 0xFE),
                (0x8116, 0xBF),
                (0x811C, 0x03),
                (0x8120, 0x03),
            )
        )

    def _avi_infoframe(self):
        aspect = 0
        if self._height in (720, 1080):
            aspect = 2  # 16:9
        elif self._height == 480:
            aspect = 1  # 4:3
        frame = bytearray(17)
        frame[0:3] = b"\x82\x02\x0d"
        frame[5] = aspect << 4
        frame[7] = self._vic
        frame[3] = -sum(frame) & 0xFF
        for i, value in enumerate(frame):
            self._write(0x8440 + i, value)
        self._write(0x843D, self._read(0x843D) | 0x08)

    def _hdmi_phy(self):
        self._write_all(
            (
                (0x8130, 0x6A),
                (0x8131, 0x44),
                (0x8132, 0x4A),
                (0x8133, 0x0B),
                (0x8134, 0x00),
                (0x8135, 0x00),
                (0x8136, 0x00),
                (0x8137, 0x44),
                (0x813F, 0x0F),
                (0x8140, 0xA0),
                (0x8141, 0xA0),
                (0x8142, 0xA0),
                (0x8143, 0xA0),
                (0x8144, 0x0A),
            )
        )
