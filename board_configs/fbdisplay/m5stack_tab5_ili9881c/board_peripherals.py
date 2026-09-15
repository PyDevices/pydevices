"""Lazy constructors for M5Stack Tab5 (ILI9881C). PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {"audio_out", "pcm_out", "pcm_in", "sdcard", "camera", "i2c", "wlan", "ble"}
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in"})

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

# M5Unified Tab5 I2S / codec pin map
_MCLK = 30
_BCLK = 27
_LRCK = 29
_DOUT = 26
_DIN = 28
_RATE = 16000
_I2C_SCL = 32
_I2C_SDA = 31

# I2S ring buffer. The default is the value this board was brought up with;
# leave it. A caller asking for latency="low" gets a shorter one instead (see
# queue_bytes), which is what an interactive synth needs and buffered playback
# does not.
_IBUF = 20000

# Floor for that shortened buffer: I2S feeds from DMA blocks, so too small a
# ring underruns no matter how promptly the caller writes.
_MIN_IBUF = 4096

# --- what this board can actually do --------------------------------------
#
# Declared as exactly what this board already did before the format contract
# existed: one rate, two channels, 16-bit. Nobody here has a Tab5 to measure
# on, and a capability is a promise the contract makes on the board's behalf,
# so widening it would be inventing a claim. The codec's clock tree is set up
# for this rate; another rate needs register work and a capture to prove it.
# Someone holding the hardware should widen this, not a reader of a datasheet.
_OUT_DEFAULT = AudioFormat(_RATE, 2, 16)
AUDIO_OUT = AudioCapability(
    _OUT_DEFAULT,
    rates=(_RATE,),
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(0, sck=_BCLK, ws=_LRCK, sd=_DOUT, mck=_MCLK, mck_fs=256),
)
AUDIO_IN = AudioCapability(
    AudioFormat(_RATE, 2, 16),
    rates=(_RATE,),
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(0, sck=_BCLK, ws=_LRCK, sd=_DIN, mck=_MCLK, mck_fs=256),
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """Panel / expansion I2C."""
    return _i2c_bus()


def _i2c_bus():
    """Panel I2C, shared with whatever already opened it.

    Never ``import board_config`` from here: a non-graphics app importing
    this module must not start a display. That import is what the previous
    version of this file did, on every audio call.
    """
    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    from machine import I2C, Pin

    return I2C(0, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400_000)


def _stream(mode, sd_pin, ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        0,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(sd_pin),
        mck=Pin(_MCLK),
        mode=mode,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """ES7210 ADC + I2S RX: a raw ``PCMInput``."""
    from machine import I2S

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
    return I2SPCMInput(
        lambda: _stream(I2S.RX, _DIN, ibuf, wire),
        wire,
        session=_SESSION,
        codec=codec,
        set_hardware_gain=codec.set_gain,
        power=codec.enable_input,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """ES8388 DAC + I2S TX (+ PI4IOE amp enable): a raw ``PCMOutput``.

    Paced: ``I2SPCMOutput`` arms I2S into asyncio mode, so an unpaced
    ``write()`` raises once DMA fills. See the T-Embed board for the measured
    version of that.
    """
    from machine import I2S

    from es8388 import ES8388
    from pi4ioe5v import tab5_set_amp

    from audiodev import pace_output

    wire, source = negotiate(AUDIO_OUT, format)
    bus = _i2c_bus()
    codec = ES8388(bus)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def power(enable):
        codec.enable_output(enable)
        tab5_set_amp(bus, enable)

    device = I2SPCMOutput(
        lambda: _stream(I2S.TX, _DOUT, ibuf, wire),
        wire,
        session=_SESSION,
        codec=codec,
        set_hardware_volume=codec.set_dac_volume,
        set_hardware_mute=codec.dac_mute,
        power=power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player. Requires audioif; use ``pcm_out`` for
    raw PCM bytes, which has no DSP dependency."""
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
    from machine import SDCard

    return SDCard()


def camera():
    raise NotImplementedError("Tab5 camera needs native CSI support")


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
