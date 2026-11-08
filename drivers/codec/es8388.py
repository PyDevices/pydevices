# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""ES8388 codec over I2C: the DAC for playback, and the ADC for recording.

The DAC sequence is distilled from M5Unified Tab5
(``_speaker_enabled_cb_tab5``): enough to unmute the DAC and line outs so
I2S TX can play. The ADC is off until `ES8388.enable_input`; its settings
follow the datasheet and Espressif's ESP-ADF driver. Tab5 uses an ES7210
for its microphones and never turns this ADC on.
"""

import time

try:
    from micropython import const
except ImportError:

    def const(x):
        return x


I2C_ADDR = const(0x10)

# ADC inputs: the pair of pins each side of the ADC reads.
INPUT1 = const(1)  # LINPUT1/RINPUT1
INPUT2 = const(2)  # LINPUT2/RINPUT2
DIFFERENTIAL = const(3)  # LINPUT1 - RINPUT1 on both channels, mic bias on


def _sleep_ms(milliseconds):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(milliseconds)
    else:
        time.sleep(milliseconds / 1000)

# (reg, value) — Tab5 speaker enable bulk (DAC path)
_INIT = (
    (0x00, 0x80),  # RESET / CSM power on
    (0x00, 0x00),
    (0x00, 0x00),
    (0x00, 0x0E),
    (0x01, 0x00),
    (0x02, 0x0A),  # chip power up
    (0x03, 0xFF),  # ADC power down
    (0x04, 0x3C),  # DAC + LOUT/ROUT 1/2
    (0x05, 0x00),
    (0x06, 0x00),
    (0x07, 0x7C),  # VSEL
    (0x08, 0x00),  # I2S slave
    (0x17, 0x18),  # 16-bit I2S
    (0x18, 0x00),  # MCLK ratio 128
    (0x19, 0x20),  # DAC unmute
    (0x1A, 0x00),  # LDACVOL
    (0x1B, 0x00),  # RDACVOL
    (0x1C, 0x08),  # click-free power
    (0x1D, 0x00),
    (0x26, 0x00),  # DAC CTRL16
    (0x27, 0xB8),  # left mix
    (0x2A, 0xB8),  # right mix
    (0x2B, 0x08),  # ADC/DAC separate LRCK
    (0x2D, 0x00),
    (0x2E, 0x21),
    (0x2F, 0x21),
    (0x30, 0x21),
    (0x31, 0x21),
)


class ES8388:
    """Power up ES8388 DAC for I2S slave playback."""

    def __init__(self, i2c, address=I2C_ADDR):
        self._i2c = i2c
        self._addr = address
        self.volume = 100
        self.muted = False
        self.enabled = False
        self.input_enabled = False
        self.input = INPUT1
        self.mic_gain = 24
        self.input_volume = 100
        self._init()

    def _wr(self, reg, val):
        self._i2c.writeto_mem(self._addr, reg, bytes((val & 0xFF,)))

    def _init(self):
        for reg, val in _INIT:
            self._wr(reg, val)
            if reg == 0x00 and val == 0x80:
                _sleep_ms(10)
        self.enabled = True

    def set_dac_volume(self, percent):
        """Set stereo DAC volume from -96 dB (0%) to 0 dB (100%)."""
        percent = max(0, min(100, int(percent)))
        attenuation = (100 - percent) * 0xC0 // 100
        self._wr(0x1A, attenuation)
        self._wr(0x1B, attenuation)
        self.volume = percent
        return percent

    def dac_mute(self, mute=True):
        """Mute both DAC analog outputs while retaining the signal path."""
        self._wr(0x19, 0x24 if mute else 0x20)
        self.muted = bool(mute)

    def enable_output(self, enable=True):
        enable = bool(enable)
        if enable:
            self._wr(0x04, 0x3C)
        else:
            self.dac_mute(True)
            self._wr(0x04, 0xC0)
        self.enabled = enable

    def enable_input(self, enable=True, input=None):
        """Power the ADC up or down.

        Args:
            enable: True records, False powers the ADC down.
            input: `INPUT1` or `INPUT2`, the pins the ADC reads, or
                `DIFFERENTIAL` for a microphone wired across both input 1
                pins, which also turns the mic bias on. Defaults to the last
                one chosen, `INPUT1` at first.
        """
        if input is not None:
            if input not in (INPUT1, INPUT2, DIFFERENTIAL):
                raise ValueError("input is INPUT1, INPUT2 or DIFFERENTIAL")
            self.input = input
        if not enable:
            self._wr(0x03, 0xFF)  # ADC, its inputs and the mic bias off
            self._wr(0x02, 0x0A)  # the ADC's DLL and reference off
            self.input_enabled = False
            return
        self._wr(0x02, 0x00)  # every block of the chip powered
        # The ADC takes its frame clock from the DAC's LRCK pin: one clock
        # for both directions, as I2S full duplex has.
        self._wr(0x2B, 0x80)
        self._wr(0x0A, {INPUT1: 0x00, INPUT2: 0x50, DIFFERENTIAL: 0xF0}[self.input])
        self._wr(0x0B, 0x02)
        self._wr(0x0C, 0x0C)  # 16-bit I2S
        self._wr(0x0D, 0x02)  # single speed, MCLK = 256 fs
        self.set_mic_gain(self.mic_gain)
        self.set_adc_volume(self.input_volume)
        if self.input == DIFFERENTIAL:
            self._wr(0x03, 0x00)  # ADC, both inputs and the mic bias on
        else:
            self._wr(0x03, 0x09)  # ADC and both inputs on, mic bias off
        self.input_enabled = True

    def set_mic_gain(self, db):
        """Set the input amplifier of both channels: 0 to 24 dB in 3 dB steps."""
        db = max(0, min(24, int(db))) // 3 * 3
        step = db // 3
        self._wr(0x09, step << 4 | step)
        self.mic_gain = db
        return db

    def set_adc_volume(self, percent):
        """Set the ADC's digital level from -96 dB (0%) to 0 dB (100%)."""
        percent = max(0, min(100, int(percent)))
        attenuation = (100 - percent) * 0xC0 // 100
        self._wr(0x10, attenuation)
        self._wr(0x11, attenuation)
        self.input_volume = percent
        return percent

    def close(self):
        self.enable_input(False)
        self.enable_output(False)

    deinit = close
