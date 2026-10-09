"""board_peripherals for the Waveshare ESP32-P4-WIFI6-DEV-KIT, on CircuitPython.

Headless, like the MicroPython config in board_configs/nodisplay: there is no
board_config.py; an app imports board_peripherals directly. The board's
hardware is described there; this file exposes what CircuitPython can drive.

``audio_out()`` is CircuitPython's own ``audiobusio.I2SOut`` into the ES8311
codec (MCLK 13, SCLK 12, LRCK 10, DSDIN 9), after the codec is set up over
the board I2C and the speaker amplifier (GPIO53) is switched on. I2SOut
clocks MCLK at 256 times the sample rate, the tree the ES8311 driver
programs, so any rate plays. The speaker header and the 3.5 mm jack carry
the same DAC; headphones in the jack cut the speaker in hardware.
"""

import board
import displayio

# CircuitPython keeps a display a previous program made and puts the console on
# it, and redrawing that text on an 800x480 panel holds up everything else for
# about 200 ms, audio included: each print() clicks. Every app imports this
# file, and board_config imports it before making its own display, so dropping
# any leftover display here leaves a headless app with no console to redraw.
displayio.release_displays()

PERIPHERALS = frozenset({"audio_out", "audio_in", "audio_power", "i2c", "sdcard", "boot_button"})

_VOLUME = 100  # 0 dB: the loudest the ES8311 plays without clipping

_i2c = None
_codec = None
_pa = None


class _I2CMem:
    """machine.I2C's register calls over a busio.I2C, for drivers written for
    MicroPython (the ES8311 codec, the FT6x36 touch controller)."""

    def __init__(self, bus):
        self._bus = bus

    def _lock(self):
        while not self._bus.try_lock():
            pass

    def writeto_mem(self, addr, reg, buf):
        self._lock()
        try:
            self._bus.writeto(addr, bytes([reg]) + bytes(buf))
        finally:
            self._bus.unlock()

    def readfrom_mem(self, addr, reg, n):
        buf = bytearray(n)
        self.readfrom_mem_into(addr, reg, buf)
        return buf

    def readfrom_mem_into(self, addr, reg, buf):
        self._lock()
        try:
            self._bus.writeto_then_readfrom(addr, bytes([reg]), buf)
        finally:
            self._bus.unlock()


def i2c():
    """The board I2C (SDA 7, SCL 8): codec, camera SCCB, DSI touch, I2C header."""
    global _i2c
    if _i2c is None:
        _i2c = board.I2C()
    return _i2c


def _amp(on):
    global _pa
    if _pa is None:
        import digitalio

        _pa = digitalio.DigitalInOut(board.IO53)
        _pa.switch_to_output(value=False)
    _pa.value = bool(on)


def audio_power(enable=True, *, volume=None):
    """Bring the codec and amplifier up (or down) without opening I2S."""
    global _codec
    if enable:
        if _codec is None:
            from es8311 import ES8311

            _codec = ES8311(_I2CMem(i2c()), mclk_multiplier=256)
        _codec.enable_output(True)
        _codec.set_dac_volume(_VOLUME if volume is None else int(volume))
        _codec.dac_mute(False)
        _amp(True)
    elif _codec is not None:
        _amp(False)
        _codec.enable_output(False)
    return enable


def audio_out(*args, **kwargs):
    """The ES8311's I2S output, codec and amplifier powered. Arguments are
    accepted and ignored: I2SOut plays whatever format each sample carries."""
    import audiobusio

    audio_power(True)
    return audiobusio.I2SOut(board.IO12, board.IO10, board.IO9, main_clock=board.IO13)


def audio_in(sample_rate=16000):
    """The onboard microphone, through the ES8311's own ADC, as
    ``audioi2sin.I2SIn``: ``record(buf, n)`` fills a 16-bit ``'h'`` array.

    It shares the codec's I2S pins with ``audio_out``, so stop and deinit the
    output before recording, and the reverse.
    """
    import audioi2sin

    global _codec
    if _codec is None:
        from es8311 import ES8311

        _codec = ES8311(_I2CMem(i2c()), mclk_multiplier=256)
    _codec.enable_input(True)
    return audioi2sin.I2SIn(
        board.IO12, board.IO10, board.IO11, main_clock=board.IO13, sample_rate=sample_rate, bit_depth=16, mono=True
    )


def sdcard():
    """The microSD slot over 4-bit SDIO (``sdioio.SDCard``)."""
    import sdioio

    return sdioio.SDCard(
        clock=board.IO43,
        command=board.IO44,
        data=[board.IO39, board.IO40, board.IO41, board.IO42],
        frequency=40_000_000,
    )


def boot_button():
    """The BOOT button (GPIO35, ``value`` False when pressed)."""
    import digitalio

    button = digitalio.DigitalInOut(board.BOOT)
    button.switch_to_input(pull=digitalio.Pull.UP)
    return button
