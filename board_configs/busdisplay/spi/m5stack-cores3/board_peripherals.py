"""Lazy constructors for M5Stack CoreS3 non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_in",
        "audio_out",
        "sdcard",
        "camera",
        "accelerometer",
        "gyroscope",
        "i2c",
        "wlan",
        "ble",
    }
)

from audiodev import (
    AudioCapability,
    AudioFactory,
    AudioFormat,
    AudioSession,
    I2SWire,
    adapt_channels,
    negotiate,
    queue_bytes,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

_SESSION = AudioSession(duplex=False)

# M5Unified CoreS3 I2S / codec pin map
_MCLK = 0
_BCLK = 34
_LRCK = 33
_DOUT = 13
_DIN = 14
_BMI270_ADDR = 0x69
_RATE = 16000
_I2C_SDA = 12
_I2C_SCL = 11
_IBUF = 20000
_MIN_IBUF = 4096

# --- what this board can actually do --------------------------------------
#
# Declared as exactly what this board already did before the format contract
# existed: one rate, two channels, 16-bit. Nobody here has a CoreS3 to measure
# on, and a capability is a promise the contract makes on the board's behalf,
# so widening it would be inventing a claim. The AW88298 is handed
# sample_rate=_RATE at construction, which is a second reason another rate
# needs real work rather than a wider tuple.
AUDIO_OUT = AudioCapability(
    AudioFormat(_RATE, 2, 16),
    rates=(_RATE,),
    channels=(2,),
    native_channels=1,          # AW88298 drives one speaker
    bits=(16,),
    wire=I2SWire(1, sck=_BCLK, ws=_LRCK, sd=_DOUT),
)
AUDIO_IN = AudioCapability(
    AudioFormat(_RATE, 2, 16),
    rates=(_RATE,),
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(1, sck=_BCLK, ws=_LRCK, sd=_DIN, mck=_MCLK, mck_fs=256),
)

_imu = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """CoreS3 internal / Grove I2C."""
    return _i2c_bus()


def _bmi270():
    global _imu
    if _imu is not None:
        return _imu
    from bmi270 import BMI270

    _imu = BMI270(_i2c_bus(), address=_BMI270_ADDR)
    return _imu


def _i2c_bus():
    """Internal I2C, shared with whatever already opened it.

    Never ``import board_config`` from here: a non-graphics app importing
    this module must not start a display. That import is what the previous
    version of this file did, on every audio call.
    """
    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    from machine import I2C, Pin

    return I2C(0, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=100_000)


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """ES7210 ADC + I2S RX (dual MEMS): a raw ``PCMInput``."""
    from machine import I2S, Pin

    from es7210 import ES7210

    wire, _ = negotiate(AUDIO_IN, format)
    codec = ES7210(_i2c_bus(), profile="m5")
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def stream():
        return I2S(
            1,
            sck=Pin(_BCLK),
            ws=Pin(_LRCK),
            sd=Pin(_DIN),
            mck=Pin(_MCLK),
            mode=I2S.RX,
            bits=wire.bits,
            format=I2S.STEREO if wire.channels == 2 else I2S.MONO,
            rate=wire.rate,
            ibuf=ibuf,
        )

    return I2SPCMInput(
        stream, wire, session=_SESSION, codec=codec,
        set_hardware_gain=codec.set_gain, power=codec.enable_input,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """AW88298 amp + I2S TX (AW9523 speaker enable): a raw ``PCMOutput``.

    Paced: ``I2SPCMOutput`` arms I2S into asyncio mode, so an unpaced
    ``write()`` raises once DMA fills.
    """
    from machine import I2S, Pin

    from aw88298 import AW88298

    from audiodev import pace_output

    wire, source = negotiate(AUDIO_OUT, format)
    codec = AW88298(_i2c_bus(), sample_rate=wire.rate, enable_aw9523=True)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def stream():
        return I2S(
            1,
            sck=Pin(_BCLK),
            ws=Pin(_LRCK),
            sd=Pin(_DOUT),
            mode=I2S.TX,
            bits=wire.bits,
            format=I2S.STEREO if wire.channels == 2 else I2S.MONO,
            rate=wire.rate,
            ibuf=ibuf,
        )

    device = I2SPCMOutput(
        stream, wire, session=_SESSION, codec=codec,
        set_hardware_mute=codec.mute, power=codec.enable_output,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player. Requires audioif; use ``pcm_out`` for raw
    PCM bytes, which has no DSP dependency."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)


def sdcard():
    """CoreS3 microSD via SDMMC when firmware exposes machine.SDCard."""
    from machine import SDCard

    return SDCard()


def camera():
    raise NotImplementedError("CoreS3 camera needs native CSI / GC0308 support")


def accelerometer():
    """BMI270 accel (same instance as gyroscope)."""
    return _bmi270()


def gyroscope():
    """BMI270 gyro (same instance as accelerometer)."""
    return _bmi270()


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
