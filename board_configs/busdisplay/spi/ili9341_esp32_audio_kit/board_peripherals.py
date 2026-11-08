# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy roles for the Ai-Thinker ESP32-Audio-Kit V2.2 (ESP32-A1S).

The A1S module carries an ES8388 codec on its own I2C (IO32, IO33) and I2S
(MCLK IO0, BCLK IO27, LRCK IO25, DOUT IO26). Its outputs feed the
headphone jack and two NS4150B speaker amplifiers, which IO21 switches on.
None of these pins reach the kit's headers, so nothing the display uses
can collide with them.

Recording isn't here yet: the es8388 driver brings up the DAC only, and
the kit's microphones need the codec's ADC.
"""

import sys

import boarddev
from audiodev import (
    AudioCapability,
    AudioFactory,
    AudioFormat,
    I2SWire,
    adapt_channels,
    check_latency,
    negotiate,
    pace_output,
    queue_bytes,
)
from audiodev.i2s_audio import I2SPCMOutput

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "audio_power",
        "sdcard",
        "wlan",
        "bt",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "audio_power"})

_I2S_PORT = 0
_MCLK = 0
_BCLK = 27
_LRCK = 25
_DOUT = 26
_AMP = 21  # NS4150B enable, high = on

# The codec's I2C: a port of its own, inside the A1S module.
_CODEC_I2C_PORT = 1
_CODEC_SCL = 32
_CODEC_SDA = 33

_IBUF = 20000
_MIN_IBUF = 4096

# These rates are the two a Bluetooth or file source sends. They have not
# been measured on the kit yet: the es8388 driver sets the codec's MCLK ratio
# to 128 while machine.I2S drives MCLK at 256 fs, and a capture at each rate
# has to show the pitch is right before this declaration is a promise.
AUDIO_OUT = AudioCapability(
    AudioFormat(44100, 2, 16),
    rates=(44100, 48000),
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(_I2S_PORT, sck=_BCLK, ws=_LRCK, sd=_DOUT, mck=_MCLK, mck_fs=256),
)

_codec_i2c = None
_codec = None
_amp = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _output_codec():
    """The one ES8388, so power, volume and mute all reach the same codec."""
    global _codec_i2c, _codec
    if _codec is None:
        from es8388 import ES8388
        from machine import I2C, Pin

        _codec_i2c = I2C(_CODEC_I2C_PORT, scl=Pin(_CODEC_SCL), sda=Pin(_CODEC_SDA), freq=100_000)
        _codec = ES8388(_codec_i2c)
    return _codec


def _set_amp(enable):
    global _amp
    if _amp is None:
        from machine import Pin

        _amp = Pin(_AMP, Pin.OUT, value=0)
    _amp(1 if enable else 0)


def _stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _I2S_PORT,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DOUT),
        mck=Pin(_MCLK),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """ES8388 DAC and the speaker amplifiers: a raw ``PCMOutput``.

    Paced: ``I2SPCMOutput`` arms I2S into asyncio mode, so check ``space()``
    before each write.
    """
    from audiodev.accel import best_remix

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    codec = _output_codec()
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def power(enable):
        codec.enable_output(enable)
        _set_amp(enable)

    device = I2SPCMOutput(
        lambda: _stream(ibuf, wire),
        wire,
        codec=codec,
        set_hardware_volume=codec.set_dac_volume,
        set_hardware_mute=codec.dac_mute,
        power=power,
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    if source is not wire:
        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player. Requires audiodsp; use ``pcm_out`` for
    raw PCM bytes, which has no DSP dependency."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _audio_power(enable=True, *, volume=None):
    """Bring the codec and speaker amplifiers up or down without opening a
    stream. The register writes need no clock; the codec plays once MCLK
    runs."""
    codec = _output_codec()
    if enable:
        codec.enable_output(True)
        codec.dac_mute(False)
        if volume is not None:
            codec.set_dac_volume(int(volume))
        _set_amp(True)
    else:
        _set_amp(False)
        codec.enable_output(False)
    return enable


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


def sdcard():
    """The kit's microSD slot in 1-bit mode (CLK IO14, CMD IO15, D0 IO2).

    It has to stay 1-bit: IO12, the 4-bit D2, is the display's chip select.
    CMD reaches IO15 through DIP switch 3, which must be on.
    """
    from machine import SDCard

    return SDCard(slot=1, width=1)


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def bt():
    """A Bluetooth audio receiver: the kit as a speaker for a phone or computer.

    Needs firmware built with the btaudio module. Wi-Fi and Bluetooth share
    the radio, so turn Wi-Fi off while playing.
    """
    try:
        import btaudio
    except ImportError:
        raise ImportError("bt needs firmware built with the btaudio module") from None
    return btaudio.Receiver()


def ble():
    # A bledev adapter (docs/guides/bluetooth-le.md). It also answers every
    # bluetooth.BLE method, so code written for the raw radio keeps working.
    # Firmware built with btaudio has no BLE: one Bluetooth host at a time.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
