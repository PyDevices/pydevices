# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy roles for the Ai-Thinker ESP32-Audio-Kit V2.2 (ESP32-A1S).

The A1S module carries an ES8388 codec on its own I2C (IO32, IO33) and I2S
(MCLK IO0, BCLK IO27, LRCK IO25, DOUT IO26, DIN IO35). Its outputs feed the
headphone jack and two NS4150B speaker amplifiers, which IO21 switches on.
Its ADC reads the kit's two microphones, or the line-in jack. None of these
pins reach the kit's headers, so nothing the display uses can collide with
them.

Many of these kits ship with the microphones' two coupling capacitors on the
wrong pads, and their microphones record only noise until those are moved.
The line-in jack works either way.
"""

import sys

import boarddev
from audiodev import (
    AudioCapability,
    AudioFactory,
    AudioFormat,
    AudioSession,
    I2SWire,
    adapt_channels,
    check_latency,
    negotiate,
    pace_output,
    queue_bytes,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "pcm_in",
        "audio_power",
        "sdcard",
        "wlan",
        "bt",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power"})

_I2S_PORT = 0
_MCLK = 0
_BCLK = 27
_LRCK = 25
_DOUT = 26
_DIN = 35  # the ES8388's ADC output
_AMP = 21  # NS4150B enable, high = on

# The codec's I2C: a port of its own, inside the A1S module.
_CODEC_I2C_PORT = 1
_CODEC_SCL = 32
_CODEC_SDA = 33

_IBUF = 20000
_MIN_IBUF = 4096

# 44.1 and 48 kHz are what a Bluetooth or file source sends; 8 and 16 kHz
# are a phone call's. Each measured as a 1 kHz tone on the kit's headphone
# output: 1005 Hz at 44.1 kHz, 1002 Hz at 48 kHz, 1000 Hz at 16 kHz and at
# 8 kHz. The codec runs as an I2S slave, so MCLK at 256 fs works even though
# es8388 sets a DAC ratio of 128.
_RATES = (8000, 16000, 44100, 48000)

AUDIO_OUT = AudioCapability(
    AudioFormat(44100, 2, 16),
    rates=_RATES,
    channels=(2,),
    native_channels=2,
    bits=(16,),
    # sd_in is the ADC's output. Publishing it lets the audio pump open the
    # port as one TX/RX pair, so pcm_in records while the output plays.
    wire=I2SWire(_I2S_PORT, sck=_BCLK, ws=_LRCK, sd=_DOUT, mck=_MCLK, mck_fs=256, sd_in=_DIN),
)

# The microphones, or the line-in jack (`MIC` and `LINE` below), through the
# ES8388's ADC on the same port and clocks as the output.
AUDIO_IN = AudioCapability(
    AudioFormat(16000, 1, 16),
    rates=_RATES,
    channels=(1, 2),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(_I2S_PORT, sck=_BCLK, ws=_LRCK, sd=_DIN, mck=_MCLK, mck_fs=256),
)

# pcm_in's inputs: the kit's two onboard microphones, or its line-in jack.
MIC = "mic"
LINE = "line"

_codec_i2c = None
_codec = None
_amp = None
_SESSION = AudioSession(codec_factory=lambda: _output_codec(), duplex=False)
_INPUT_SESSION = AudioSession(codec_factory=lambda: _output_codec(), duplex=False)


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


def _i2s(mode, sd_pin, ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _I2S_PORT,
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


def _refuse_if_held(session, wanted, holder):
    """Refuse to open I2S(0) while the other direction has it.

    On esp32, constructing machine.I2S(0) while it is in use doesn't raise:
    it deinitialises the live one and hands it back in the new direction,
    so the speaker would just go quiet.
    """
    if session._owners:
        raise OSError(
            "I2S(0) is in use by the %s: the kit's speaker and microphones "
            "share one I2S port, and pcm_out takes the whole port, so close "
            "the %s before opening the %s. audio_out, and the audio pump, "
            "play while pcm_in records" % (holder, holder, wanted)
        )


def _stream(ibuf, fmt):
    from machine import I2S

    _refuse_if_held(_INPUT_SESSION, "speaker", "microphone")
    return _i2s(I2S.TX, _DOUT, ibuf, fmt)


def _input_stream(ibuf, fmt):
    from machine import I2S

    _refuse_if_held(_SESSION, "microphone", "speaker")
    return _i2s(I2S.RX, _DIN, ibuf, fmt)


def _duplex_pump():
    """``audiodev.pump`` when this firmware records while it plays, else None."""
    try:
        from audiodev import pump
    except ImportError:
        return None
    return pump if pump.duplex() else None


def _input_power(enable, which):
    codec = _output_codec()
    if enable:
        from es8388 import DIFFERENTIAL, INPUT2

        # The two microphones are wired differentially into input 1 and need
        # the mic bias, and the amplifier's full 24 dB. A line is loud
        # already, and clips with any gain.
        codec.mic_gain = 24 if which == MIC else 0
        codec.enable_input(True, DIFFERENTIAL if which == MIC else INPUT2)
    else:
        codec.enable_input(False)


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
        session=_SESSION,
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


def _pcm_in(format=None, *, latency=None, queue_ms=None, input=MIC):
    """The kit's microphones, or its line-in jack, through the ES8388's ADC:
    a raw ``PCMInput``.

    Mono mixes the two microphones (or the line's left and right); stereo
    keeps them apart. With the audio pump in the firmware, this reads the
    RX half of the pump's channel, so it records while ``audio_out`` or the
    pump plays, at the rate the output is clocked at. Without it, it is
    ``machine.I2S``, and it and ``pcm_out`` refuse each other.

    Args:
        format: the recording's ``AudioFormat``, 16 kHz mono by default.
        input: `MIC` for the onboard microphones, `LINE` for the line-in jack.
    """
    if input not in (MIC, LINE):
        raise ValueError("input is MIC or LINE")
    check_latency(latency)
    wire, source = negotiate(AUDIO_IN, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    _output_codec()
    gain = lambda value: _output_codec().set_adc_volume(value)
    power = lambda enable: _input_power(enable, input)
    pump = _duplex_pump()
    if pump is not None:
        return pump.PumpPCMInput(
            source,
            wire=AUDIO_OUT.wire,
            ring_bytes=ibuf,
            take="mix",
            before_open=lambda: _refuse_if_held(_SESSION, "microphone", "speaker"),
            session=_INPUT_SESSION,
            set_hardware_gain=gain,
            power=power,
        )
    if source is not wire:
        raise ValueError("without the audio pump, this board records %d channel(s)" % wire.channels)
    return I2SPCMInput(
        lambda: _input_stream(ibuf, wire),
        wire,
        session=_INPUT_SESSION,
        set_hardware_gain=gain,
        power=power,
    )


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
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
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

    Needs firmware built with the btclassic module. Wi-Fi and Bluetooth share
    the radio, so turn Wi-Fi off while playing.
    """
    try:
        import btclassic
    except ImportError:
        raise ImportError("bt needs firmware built with the btclassic module") from None
    return btclassic.AudioSink(btclassic.Bluetooth())


def ble():
    # A bledev adapter (docs/guides/bluetooth-le.md). It also answers every
    # bluetooth.BLE method, so code written for the raw radio keeps working.
    # Firmware built with btclassic has no BLE: one Bluetooth host at a time.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
