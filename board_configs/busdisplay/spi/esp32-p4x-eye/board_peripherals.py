# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for the Espressif ESP32-P4X-EYE. PERIPHERALS = lazy roles only.

Pins from Espressif's ESP32-P4-EYE board support package:

    I2C            port 1, SCL 13, SDA 14 (camera SCCB, QMA6100P)
    camera         OV2710 on MIPI-CSI; enable 12 (high on), reset 26,
                   XCLK 11 at 24 MHz
    SD card        SDMMC slot 0, 4 bits, on-chip LDO channel 4;
                   power 46 (low on), card detect 45 (low when a card is in)
    microphone     PDM, CLK 22, DATA 21
    flash LED      23 (high on)
    C6 radio       enable 9, the ESP-Hosted reset line
    buttons        menu 3, up 4, down 5, knob press 2 (low when pressed)

``sleep()`` puts the board into light or deep sleep until a time passes or
one of the four buttons is pressed. Deep sleep holds the camera and the C6
off until the board wakes, and the board restarts on wake; the holds are let
go the next time this module is imported.

Nothing here has run on the board yet.
"""

import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "pcm_in",
        "sdcard",
        "camera",
        "led",
        "accelerometer",
        "i2c",
        "sleep",
        "usb_device",
        "wlan",
        "ble",
    }
)

# Factories: first attribute access binds the callable, so a caller can pass
# arguments. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"pcm_in", "sleep"})

from audiodev import AudioCapability, AudioFactory, AudioFormat, negotiate
from audiodev.i2s_audio import I2SPCMInput

# Hooks hand drivers the one bus object _i2c_bus() returns, never these pins.
# See docs/boards/board-contract.md.
_I2C_PORT = 1
_I2C_SCL = 13
_I2C_SDA = 14

_CAM_EN = 12
_CAM_RESET = 26
_CAM_XCLK = 11
_CAM_XCLK_HZ = 24_000_000

_SD_POWER = 46  # low powers the card
_SD_DETECT = 45  # low when a card is in

_MIC_CLK = 22
_MIC_DATA = 21
_IN_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

_LED = 23
_C6_EN = 9

_BUTTONS = {"menu": 3, "up": 4, "down": 5, "knob": 2}
WAKE_SOURCES = ("menu", "up", "down", "knob")

_i2c_own = None
_accel = None
_sd_detect = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _release_sleep_holds():
    """After a deep-sleep wake, let go of the camera and C6 enables.

    ``sleep(deep=True)`` holds both low through sleep. The hold outlives the
    restart, so until it is released the camera can't be switched on and
    ESP-Hosted can't take the C6 out of reset. Nothing is touched after any
    other kind of reset.
    """
    try:
        import machine
    except ImportError:
        # Host structural import: no pins.
        return
    if machine.reset_cause() != machine.DEEPSLEEP_RESET:
        return
    machine.Pin(_CAM_EN, machine.Pin.OUT, value=0, hold=False)
    machine.Pin(_C6_EN, hold=False)


_release_sleep_holds()


def _i2c_bus():
    """I2C port 1, opened once and shared by every hook here.

    Nothing in board_config uses this bus, so this module owns it, and a
    non-graphics app importing only this module gets the same object.
    """
    global _i2c_own

    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400_000)
    return _i2c_own


def i2c():
    """The board's I2C bus (port 1, SCL 13, SDA 14, 400 kHz), shared with the
    camera and the accelerometer."""
    return _i2c_bus()


def sdcard_present():
    """True when a card is in the slot (the card-detect switch, GPIO45)."""
    global _sd_detect
    if _sd_detect is None:
        from machine import Pin

        _sd_detect = Pin(_SD_DETECT, Pin.IN)
    return not _sd_detect.value()


def sdcard():
    """The microSD slot (``machine.SDCard``, SDMMC slot 0, 4 bits), with its
    power switched on first. Mount it yourself::

        import os
        os.mount(board_config.sdcard, "/sd")
    """
    import time

    from machine import Pin, SDCard

    Pin(_SD_POWER, Pin.OUT, value=0)
    time.sleep_ms(10)
    try:
        return SDCard()
    except TypeError:
        return SDCard(slot=0)


def camera(**kwargs):
    """The OV2710 on MIPI-CSI, switched on first.

    Any ``cameraif.Camera`` keyword passes straight through::

        cam = board_config.camera(format="HD")

    The camera's SCCB bus is the board's I2C bus, so that bus is opened
    first and cameraif joins it rather than opening a second controller on
    the same pins.
    """
    import time

    import cameraif
    from machine import Pin

    if not cameraif.available():
        raise NotImplementedError("cameraif is not in this firmware, or this is not an ESP32-P4")
    Pin(_CAM_EN, Pin.OUT, value=1, hold=False)
    time.sleep_ms(10)
    kwargs.setdefault("sda", _I2C_SDA)
    kwargs.setdefault("scl", _I2C_SCL)
    kwargs.setdefault("reset", _CAM_RESET)
    kwargs.setdefault("xclk", _CAM_XCLK)
    kwargs.setdefault("xclk_hz", _CAM_XCLK_HZ)
    if "i2c" not in kwargs:
        _i2c_bus()
        kwargs["i2c"] = _I2C_PORT
    return cameraif.Camera(**kwargs)


def led():
    """The white flash LED beside the lens, as a ``machine.Pin``: ``led(1)``
    lights it. It starts off."""
    from machine import Pin

    return Pin(_LED, Pin.OUT, value=0)


def accelerometer():
    """QMA6100P, ``acceleration`` in g, at +-2 g.

    The axes are turned 180 degrees about Z from the chip's, so that
    ``orientation.Orientation()`` gives 0 when the board is held the way its
    screen shows unrotated, and the rotation to set on the display otherwise.
    """
    global _accel
    if _accel is None:
        from qma6100p import QMA6100P

        _accel = QMA6100P(_i2c_bus(), range_g=2, axes=(~0, ~1, 2))
    return _accel


# --- the PDM microphone ----------------------------------------------------
#
# I2S0's hardware PDM-to-PCM filter, at the factory firmware's 16 kHz 16-bit.
# Not yet measured on this board: the format is the factory's, and the gain
# range is the one measured on the T-Watch S3's PDM microphone. pcm_in
# removes the filter's DC offset and starts at unity gain.
MIC_MAX_GAIN_DB = 36
MIC_DEFAULT_GAIN = 0  # percent of MIC_MAX_GAIN_DB
_IN_DEFAULT = AudioFormat(16000, 1, 16)
AUDIO_IN = AudioCapability(
    _IN_DEFAULT,
    rates=(16000,),
    channels=(1,),
    native_channels=1,
    bits=(16,),
)


def _in_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _IN_PORT,
        sck=Pin(_MIC_CLK),
        sd=Pin(_MIC_DATA),
        mode=I2S.PDM_RX,
        bits=fmt.bits,
        format=I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _mic_filter():
    """A viper function that removes DC and rumble (a one-pole high-pass,
    pole 1 - 2**-shift: shift 5 is about 80 Hz at 16 kHz) and applies gain,
    in place, on 16-bit samples. ``state`` carries the filter across calls;
    ``gain`` is in 1/16ths."""
    import micropython

    @micropython.viper
    def run(buf, n: int, gain: int, state, shift: int) -> int:
        p = ptr16(buf)  # noqa: F821
        st = ptr32(state)  # noqa: F821
        x1 = st[0]
        y1 = st[1]  # 1/256ths
        for i in range(n):
            x = p[i]
            if x > 32767:
                x -= 65536
            y = ((x - x1) << 8) + y1 - (y1 >> shift)
            x1 = x
            y1 = y
            o = ((y >> 8) * gain) >> 4
            if o > 32767:
                o = 32767
            elif o < -32768:
                o = -32768
            p[i] = o & 0xFFFF
        st[0] = x1
        st[1] = y1
        return n

    return run


class _PDMInput(I2SPCMInput):
    """The microphone, with its DC offset removed and gain applied: what
    ``set_gain()`` sets here is a real gain, 0-100 % of ``MIC_MAX_GAIN_DB``."""

    def __init__(self, i2s, fmt):
        super().__init__(i2s, fmt, set_hardware_gain=self._apply_gain)
        from array import array

        self._run = _mic_filter()
        self._state = array("i", (0, 0))
        self._gain16 = 16
        self.highpass_shift = 5
        self.set_gain(MIC_DEFAULT_GAIN)

    def _apply_gain(self, percent):
        self._gain16 = int(16 * 10 ** (MIC_MAX_GAIN_DB * percent / 100 / 20) + 0.5)

    def _readinto(self, buf):
        n = super()._readinto(buf)
        if n:
            self._run(buf, n // 2, self._gain16, self._state, self.highpass_shift)
        return n

    async def _areadinto(self, buf):
        n = await super()._areadinto(buf)
        if n:
            self._run(buf, n // 2, self._gain16, self._state, self.highpass_shift)
        return n


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """The PDM microphone: a ``PCMInput`` of 16 kHz 16-bit mono with its DC
    offset removed (``set_gain(percent)`` adds up to ``MIC_MAX_GAIN_DB``).
    Needs firmware with ``I2S.PDM_RX``."""
    from machine import I2S

    from audiodev import check_latency, queue_bytes

    if not hasattr(I2S, "PDM_RX"):
        raise OSError("this firmware's machine.I2S has no PDM_RX: the microphone needs a PyDevices build")
    check_latency(latency)
    wire, source = negotiate(AUDIO_IN, format)
    if source is not wire:
        raise ValueError("this board captures %s; capture cannot be converted" % (wire,))
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    return _PDMInput(lambda: _in_stream(ibuf, wire), wire)


pcm_in = AudioFactory(_pcm_in, AUDIO_IN)


def _sleep(ms=None, *, deep=False, wake=WAKE_SOURCES):
    """Sleep until ``ms`` pass or one of ``wake`` is pressed; ``wake`` names
    come from ``WAKE_SOURCES``: ``"menu"``, ``"up"``, ``"down"`` and
    ``"knob"`` (the knob's press).

    Light sleep (the default) returns the button that woke it, or
    ``"timer"``. Deep sleep restarts the board on wake, so it never returns;
    ``machine.reset_cause()`` and ``machine.wake_reason()`` say why it woke.
    Through deep sleep the camera's enable and the C6's are held low, so
    neither draws power; ``import board_peripherals`` lets them go after the
    restart. The screen and backlight stay as they are: turn them off first
    to save power.
    """
    import esp32
    import machine
    from machine import Pin

    for name in wake:
        if name not in WAKE_SOURCES:
            raise ValueError("wake sources are %s" % (WAKE_SOURCES,))
    pins = [Pin(_BUTTONS[name], Pin.IN, Pin.PULL_UP, hold=False) for name in wake]
    # Clear what an earlier call set (an empty tuple clears).
    esp32.wake_on_gpio(pins=(), level=False)
    if pins:
        # Every button reads low when pressed. On the P4 these are LP GPIOs,
        # which wake both light and deep sleep.
        esp32.wake_on_gpio(pins=tuple(pins), level=False)
    if deep:
        Pin(_CAM_EN, Pin.OUT, value=0, hold=True)
        Pin(_C6_EN, Pin.OUT, value=0, hold=True)
        if hasattr(esp32, "gpio_deep_sleep_hold"):
            esp32.gpio_deep_sleep_hold(True)
        machine.deepsleep(ms) if ms else machine.deepsleep()
    machine.lightsleep(ms) if ms else machine.lightsleep()
    esp32.wake_on_gpio(pins=(), level=False)
    if machine.wake_reason() == machine.TIMER_WAKE:
        return "timer"
    for name in wake:
        if not Pin(_BUTTONS[name], Pin.IN, Pin.PULL_UP).value():
            return name
    return "unknown"


sleep = _sleep


def usb_device():
    """The USB 2.0 port (the one not marked Debug) as ``machine.USBDevice``.
    The REPL stays on the Debug port."""
    from machine import USBDevice

    return USBDevice()


def wlan():
    """Wi-Fi through the C6 over ESP-Hosted."""
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/guides/bluetooth-le.md). It also answers every bluetooth.BLE
    # method, so code written for the raw radio keeps working. Without bledev
    # (or aioble) installed, the raw radio, as before.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
