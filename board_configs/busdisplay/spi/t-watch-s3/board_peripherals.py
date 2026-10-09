"""Lazy constructors for the LILYGO T-Watch S3. PERIPHERALS = lazy roles only.

Every peripheral on this watch sits behind a rail of its AXP2101 power chip,
so each hook here switches its rail on before it builds the device:

    ALDO2  display backlight      ALDO3  display and touch
    ALDO4  LoRa radio             BLDO2  DRV2605 enable pin
    DLDO1  MAX98357A amplifier    VBACKUP  PCF8563 clock and its coin cell

(LILYGO's schematic T_WATCH-S3 25-03-24 and LilyGoLib's LilyGoWatchS3.cpp.)
The clock in particular does not answer on I2C until VBACKUP is on.

Pins are LILYGO's (TTGO_TWatch_Library, branch t-watch-s3, src/utilities.h),
and agree with CircuitPython's lilygo_twatch_s3 board definition:

    I2C (PMU, BMA423, PCF8563, DRV2605)  SDA 10, SCL 11
    MAX98357A                            BCLK 48, WS 15, DOUT 46
    PDM microphone                       CLK 44, DATA 47
    IR LED                               GPIO2
    interrupts                           PMU 21, RTC 17, BMA423 14

The PDM microphone has no role here: MicroPython's ``machine.I2S`` has no PDM
mode, so there is nothing to capture it with. The SX1262 radio has no role
either: there is no driver for it in this repository.
"""

import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "audio_power",
        "accelerometer",
        "rtc",
        "haptic",
        "ir",
        "battery",
        "boot_button",
        "wlan",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "audio_power"})

from audiodev import AudioCapability, AudioFactory, AudioFormat, I2SWire, adapt_channels, negotiate
from audiodev.i2s_audio import I2SPCMOutput

# Main I2C, shared with board_config (port 0). Hooks hand drivers the one bus
# object _i2c_bus() returns, never these pins. See docs/board-peripherals.md.
_I2C_PORT = 0
_I2C_SDA = 10
_I2C_SCL = 11
_IIS_BCLK = 48
_IIS_WS = 15
_IIS_DOUT = 46
_IR_PIN = 2
_IR_CARRIER = 38_000

_OUT_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

_i2c_own = None
_pmu_obj = None
_accel = None
_rtc = None
_haptic = None

# --- what this board can actually do --------------------------------------
#
# A MAX98357A is an amplifier, not a codec: no I2C and no registers, and it
# clocks from BCLK, so the rate is whatever the I2S peripheral is asked for.
# Measured on this watch: 16000, 22050 and 44100 Hz each played out in real
# time (a known number of frames took its own duration through the paced
# write path). SD_MODE is pulled to the supply through 1 Mohm (schematic), so
# the amp plays (left + right) / 2 into its one speaker.
_OUT_DEFAULT = AudioFormat(16000, 2, 16)
AUDIO_OUT = AudioCapability(
    _OUT_DEFAULT,
    rates=None,
    channels=(1, 2),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(_OUT_PORT, sck=_IIS_BCLK, ws=_IIS_WS, sd=_IIS_DOUT),
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _i2c_bus():
    """The main I2C bus, shared with whatever already opened it.

    Never ``import board_config`` from here: a non-graphics app importing
    this module must not start the display. Without board_config, open that
    port once and hand out the same object after.
    """
    global _i2c_own

    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=400_000)
    return _i2c_own


def pmu():
    """The AXP2101, constructed once, with its ADC and the clock's supply on.

    Not a role (no app needs the chip itself), but board_config uses it to
    power the display, and every hook here uses it to power its device.
    """
    global _pmu_obj
    if _pmu_obj is None:
        from axp2101 import AXP2101

        _pmu_obj = AXP2101(_i2c_bus())
        _pmu_obj.enable_adc()
        _pmu_obj.set_backup_battery(3300)
    return _pmu_obj


def battery():
    """The AXP2101 itself: ``voltage`` (volts, ``None`` with no battery),
    ``percent``, ``charging``, ``vbus_voltage``."""
    return pmu()


def accelerometer():
    """BMA423 (or BMA456 on later watches), ``acceleration`` in g.

    The chip sits on the underside of the board, so its axes are remapped:
    LILYGO's library selects Bosch's "bottom layer, top right corner" remap
    (register value 0x81 in SensorLib v0.2.6), which is board X = chip Y,
    board Y = chip X, board Z = -chip Z. Face up on a table reads +1 g on Z.
    """
    global _accel
    if _accel is None:
        from bma423 import BMA423

        pmu()
        _accel = BMA423(_i2c_bus(), axes=(1, 0, ~2))
    return _accel


def rtc():
    """PCF8563: ``datetime()`` and ``datetime(t)`` as ``machine.RTC``,
    ``lost_power``."""
    global _rtc
    if _rtc is None:
        from pcf8563 import PCF8563

        pmu()  # VBACKUP feeds the clock
        _rtc = PCF8563(_i2c_bus())
    return _rtc


def haptic():
    """DRV2605 vibration motor: ``play(effect, ...)``, ``stop()``."""
    global _haptic
    if _haptic is None:
        import time

        from drv2605 import DRV2605

        pmu().set_rail("bldo2", 3300)  # the DRV2605's EN pin
        time.sleep_ms(1)
        _haptic = DRV2605(_i2c_bus())
    return _haptic


def ir():
    """The IR LED as an ``esp32.RMT`` channel with a 38 kHz carrier and 1 us
    ticks: ``write_pulses((9000, 4500, 560, 560, ...), True)`` sends marks and
    spaces in microseconds, starting with a mark."""
    import esp32
    from machine import Pin

    return esp32.RMT(0, pin=Pin(_IR_PIN), resolution_hz=1_000_000, tx_carrier=(_IR_CARRIER, 33, 1))


def _audio_power(enable=True, *, volume=None):
    """Switch the amplifier's rail (DLDO1) without opening an I2S stream.

    A MAX98357A has no volume register, so ``volume=`` is accepted and
    ignored: the loudness lives in the material. Unlike a board where one
    rail feeds everything, this rail feeds only the amplifier, so
    ``enable=False`` really does turn it off.
    """
    pmu().set_rail("dldo1", 3300, enable=bool(enable))
    return enable


def _out_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _OUT_PORT,
        sck=Pin(_IIS_BCLK),
        ws=Pin(_IIS_WS),
        sd=Pin(_IIS_DOUT),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """MAX98357A I2S amplifier: a raw, paced ``PCMOutput``. Push bytes with
    ``write()``; gate on ``space()`` when writing faster than realtime."""
    from audiodev import check_latency, pace_output, queue_bytes

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    _audio_power(True)
    device = I2SPCMOutput(
        lambda: _out_stream(ibuf, wire),
        wire,
        # For a consumer that drives the peripheral in C (the audio pump):
        # the pin map, and a way to bring the amplifier up without a stream.
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over the amplifier. Requires audiodsp; use
    ``pcm_out`` for raw PCM bytes, which has no DSP dependency."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


def boot_button():
    """The BOOT button inside the case (GPIO0, ``value()`` 0 when pressed)."""
    from machine import Pin

    return Pin(0, Pin.IN, Pin.PULL_UP)


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/bledev.md). It also answers every bluetooth.BLE
    # method, so code written for the raw radio keeps working. Without bledev
    # (or aioble) installed, the raw radio, as before.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
