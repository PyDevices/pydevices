"""board_peripherals for a QT Py ESP32 Pico carrying an Adafruit Audio BFF.

NOT YET RUN AGAINST THE BFF -- it is not soldered on. What IS measured is the
wire underneath it: every rate from 8 kHz to 48 kHz, mono and stereo, opened
on these exact pins and drain-timed within 1 permille (tools/audio_rig/,
2026-09-15). machine.I2S clocks into unconnected pins as happily as into an
amplifier, so the pin choice and the clock are already proven; what is not
proven is that anything comes out of the speaker.

Placement is deliberately provisional. Every board_configs/ category is named
for a display, and this board has none -- where a headless board belongs is a
structural question, so this sits in tools/ until that is decided.

The amplifier is a MAX98357A: no codec, no I2C, no register set, no MCLK. It
takes its clock from BCLK, which is why rates are continuous here rather than
a fixed tuple -- the same reason as the T-Embed, whose output half this file
is shaped like.
"""

import sys

import boarddev
from audiodev import (
    AudioCapability,
    AudioFactory,
    AudioFormat,
    I2SWire,
    adapt_channels,
    negotiate,
)
from audiodev.i2s_audio import I2SPCMOutput

PERIPHERALS = frozenset({"audio_out", "pcm_out"})

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = PERIPHERALS

# Audio BFF pads on the QT Py ESP32 Pico. The pad names are Adafruit's
# (A0/A1/A2); the GPIO numbers were read off the CircuitPython board
# definition running on this board's twin, not from a datasheet.
#   A0 = GPIO26 -> DIN    A1 = GPIO25 -> LRC    A2 = GPIO27 -> BCLK
# GPIO25/26 are the classic ESP32's DAC pins; they are ordinary GPIOs too and
# drive I2S without complaint (measured).
_BCLK = 27
_LRC = 25
_DIN = 26

_I2S_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

# --- what this board can actually do --------------------------------------
#
# Measured on the pins above, all within 1 permille: 8000, 16000, 22050,
# 24000, 32000, 44100 and 48000 Hz, in both mono and stereo. So rates=None is
# a real claim.
#
# channels=(1,) is a POLICY, and the interesting line in this file.
#
# The wire will happily open two slots -- that was measured too. But the
# MAX98357A drives one speaker and picks what it plays by jumper: left, right,
# or (L+R)/2. On the common left-only setting, handing it a stereo stream
# means the right channel is simply discarded, and a listener loses half the
# music with nothing anywhere reporting a problem.
#
# Declaring one channel says: hand me mono, and if you have stereo I will
# average it so that nothing is thrown away. That routes stereo content
# through adapt_channels -- which is also, not by accident, the first time
# the software mixdown path runs on real hardware anywhere in this project.
#
# COST, because it is not free here. This firmware carries no audioif, so
# accel.best_remix() returns None and the portable remix runs. Measured
# END TO END on this board -- pushing two seconds of audio through the whole
# chain (adapter, pacing, I2S) against the wall clock, which is the number
# that decides whether it works, not the cost of the conversion alone:
#
#   16 kHz mono     1379 ms per 2000 ms of audio   keeps up (no conversion)
#   16 kHz stereo   1778 ms per 2000 ms            KEEPS UP
#   44.1 kHz stereo 4363 ms per 2000 ms            falls behind, 2.2x over
#
# So stereo source material works at 16 kHz on this board as it stands, and
# 44.1 kHz stereo needs audioif built into the firmware for the C remix.
# Mono source at any rate costs nothing, because no conversion happens.
#
# Wrapper order was tested and does not matter: adapter-inside-pacing 0.97x
# realtime, adapter-outside 0.95x. The arrangement below is the same as every
# other board here, which is worth more than 2%.
AUDIO_OUT = AudioCapability(
    AudioFormat(16000, 1, 16),
    rates=None,
    channels=(1,),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(_I2S_PORT, sck=_BCLK, ws=_LRC, sd=_DIN),
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _I2S_PORT,
        sck=Pin(_BCLK),
        ws=Pin(_LRC),
        sd=Pin(_DIN),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """MAX98357A on the Audio BFF: a raw ``PCMOutput``.

    Hand it stereo and it is averaged to mono rather than half-discarded --
    see the note on ``channels`` above, including what that costs on this
    chip. Needs no audioif for mono material; stereo material at a high rate
    does.
    """
    from audiodev import check_latency, pace_output, queue_bytes
    from audiodev.accel import best_remix

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    device = I2SPCMOutput(lambda: _stream(ibuf, wire), wire)
    if source is not wire:
        device = adapt_channels(device, source, remix=best_remix())
    # Paced, and not optionally: I2SPCMOutput arms I2S into asyncio mode, so a
    # full DMA returns zero from write() and an unpaced PCMOutput.write()
    # raises "audio stream made no write progress". Fill to space().
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player. Requires audioif in firmware; this board's
    build has none, so use ``pcm_out`` unless that changes."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
