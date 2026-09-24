"""Lazy constructors for M5Stack CoreS3 non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "pcm_in",
        "audio_power",
        "sdcard",
        "camera",
        "accelerometer",
        "gyroscope",
        "i2c",
        "wlan",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power"})

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
# Internal I2C: the same bus as board_config.i2c (port 0). Hooks hand
# drivers that bus object; the pins only open port 0 when board_config
# isn't loaded. See docs/board-peripherals.md.
_I2C_PORT = 0
_I2C_SDA = 12
_I2C_SCL = 11
_i2c_own = None
_out_codec = None
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

    Without board_config, open that port once and hand out the same object
    after -- never a second controller on these pins.
    """
    global _i2c_own

    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=100_000)
    return _i2c_own


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """ES7210 ADC + I2S RX (dual MEMS): a raw ``PCMInput``."""
    from machine import I2S, Pin

    from es7210 import ES7210

    wire, source = negotiate(AUDIO_IN, format)
    if source is not wire:
        # Capture has no adapter. negotiate() will happily say "open the wire
        # at 1 channel and convert to the 2 you asked for", but that machinery
        # exists only on the push side -- so handing back the wire format here
        # would give a caller who asked for stereo a mono stream and no error.
        # Silently-different is the exact failure this contract prevents.
        raise ValueError(
            "this board captures %d channel(s); asked for %d, and capture "
            "cannot be remixed" % (wire.channels, source.channels)
        )
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

    from audiodev import pace_output

    wire, source = negotiate(AUDIO_OUT, format)
    codec = _output_codec()
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
        # For a consumer that drives the peripheral in C: the pin map, and a
        # way to bring the amp up without opening a stream. On a firmware
        # carrying ``audiopump``, audiodev's sample player uses both and never
        # opens ``machine.I2S`` on this port -- the pump's own I2S channel is
        # the only owner. On a firmware without it these two are inert.
        # Without them this board plays every sample on machine.I2S and the
        # pump sits idle (PyDevices/pydevices#41).
        # PUMP WIRING UNVERIFIED ON HARDWARE (2026-09-23): copied from the
        # Waveshare P4 / T-Embed pattern; nobody here has a CoreS3.
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player. Requires audiodsp; use ``pcm_out`` for raw
    PCM bytes, which has no DSP dependency."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _output_codec():
    """The one AW88298 instance, shared by the transport and the pump.

    Its I2S sample-rate register is written once, at construction, for
    ``_RATE`` -- the only rate this board declares.
    """
    global _out_codec
    if _out_codec is None:
        from aw88298 import AW88298

        _out_codec = AW88298(_i2c_bus(), sample_rate=_RATE, enable_aw9523=True)
    return _out_codec


def _audio_power(enable=True, *, volume=None):
    """Bring the amp up or down WITHOUT opening an I2S stream.

    The audio pump's ``BusioDriver`` calls this before it opens its own I2S
    channel and again when it closes it. The AW88298 clocks from BCLK (no
    MCLK on this wire) and has no volume register this driver sets, so
    ``volume=`` is accepted and ignored. ``enable_output`` also switches the
    speaker path on the AW9523 expander.
    """
    _output_codec().enable_output(bool(enable))
    return enable


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


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
    # A bledev adapter (docs/ble.md §2). It also answers every bluetooth.BLE
    # method, so code written for the raw radio keeps working. Without bledev
    # (or aioble) installed, the raw radio, as before.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
