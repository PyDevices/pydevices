"""board_peripherals for a QT Py ESP32 Pico carrying an Adafruit Audio BFF.

HEARD WORKING 2026-09-15, on a QT Py ESP32 Pico with the BFF stacked on it.
Brad listened to: a sustained 440 Hz tone at 16 kHz mono; an A-C#-E-A
arpeggio; and a 44.1 kHz stereo pair with 440 Hz left and 660 Hz right. All
correct, at half and at full scale.

That stereo pair is the useful one -- it came back as a power chord, both
notes sounding together, which confirms by ear that the amplifier really does
average L+R in hardware the way Adafruit documents. The channel policy below
rests on that, not on the datasheet.

The wire had been measured before the board went on: every rate from 8 kHz to
48 kHz, mono and stereo, opened on these exact pins -- including GPIO15, a
strapping pin -- and drain-timed within 1 permille.

Gain is set by solder pads on the BFF's underside: 6, 9 or 12 dB, defaulting
to 9 with none bridged. Nothing here touches it; it is a hardware choice, and
the one to reach for if full scale is still too quiet. machine.I2S clocks into unconnected pins as happily as into an
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

# Adafruit Audio BFF (product 5769) pads on the QT Py ESP32 Pico.
#
#   A1 = GPIO25 -> DIN    A2 = GPIO27 -> LRC    A3 = GPIO15 -> BCLK
#   A0 = GPIO26 -> microSD chip select (NOT audio; see _SD_CS)
#
# Note this is shifted one pad from the I2S Amplifier BFF (5770), which uses
# A0/A1/A2 for DIN/LRC/BCLK. Building against the wrong guide puts the bit
# clock on the SD card's chip select. The pad names are Adafruit's; the GPIO
# numbers were read off the CircuitPython board definition running on this
# board's twin.
#
# GPIO15 is a boot strapping pin on the classic ESP32 (MTDO). It drives I2S
# correctly after boot -- measured at every rate below -- but it is the pin to
# suspect first if the board ever comes up strangely with the BFF fitted.
_BCLK = 15
_LRC = 27
_DIN = 25

# The Audio BFF also carries a microSD slot on the SPI bus, chip-selected from
# A0. Not wired up here: this file exists to test the audio contract. A board
# config that shipped would want an sdcard role too, since playing WAVs off
# that card is what the board is for.
_SD_CS = 26

_I2S_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

# --- what this board can actually do --------------------------------------
#
# Measured on the pins above, all within 1 permille: 8000, 16000, 22050,
# 24000, 32000, 44100 and 48000 Hz, in both mono and stereo. So rates=None is
# a real claim.
#
# channels=(1, 2) with native_channels=1, which is the same shape as the
# ESP32-P4 and for the same reason: two slots on the wire, one speaker at the
# end of them.
#
# An earlier draft of this file declared channels=(1,) on the theory that the
# MAX98357A picks a single channel by jumper, so that handing it stereo would
# silently discard the right half unless we averaged in software first. That
# is true of the I2S Amplifier BFF (5770). It is NOT true of this board: the
# Audio BFF is, in Adafruit's words, "pre-configured for stereo mix output" --
# the amplifier averages L+R itself, in hardware, with no jumper and no cost.
#
# So stereo content opens two slots and nothing is mixed down in software,
# and this board does not after all give the project a case where the
# software remix is genuinely required. adapt_channels stays exercised by
# unit tests and by a deliberately-configured rig run, not by a board that
# needs it. Saying otherwise here would be arranging the evidence.
#
# COST, for the deliberate mono-wire configuration only -- the production
# path above never converts. This firmware carries no audioif, so
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
    AudioFormat(16000, 2, 16),
    rates=None,
    channels=(1, 2),
    native_channels=1,          # one speaker; the amp averages L+R itself
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

    Takes mono or stereo. Stereo opens two slots and the amplifier averages
    them into its one speaker in hardware, so nothing is converted and
    nothing is lost -- and no audioif is needed at any rate.
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
