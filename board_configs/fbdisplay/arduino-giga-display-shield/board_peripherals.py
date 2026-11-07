# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for the Arduino GIGA R1 WiFi with the GIGA Display Shield. PERIPHERALS = lazy roles only.

Audio is the headphone jack, which the STM32H747's DAC drives directly:
left on PA4 (A12), right on PA5 (A13). The firmware's ``audioio.AudioOut``
plays it, with the audio pump under it. ``audio_out`` is a sample player
over it and ``pcm_out`` takes raw PCM; both reach the same DAC, and
anything playing on both at once is summed. The DAC has 12 bits, so each
16-bit sample loses its low four, and there is no codec, so volume is
scaled in software.
"""
import boarddev
import sys

from audiodev import AudioCapability, AudioFactory, AudioFormat, DACWire, negotiate

PERIPHERALS = frozenset({"wlan", "audio_out", "pcm_out"})

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out"})

# TIM6 paces the DAC from the timer clock, so any rate opens. Both channels
# are wired to the jack; a mono stream plays on both.
AUDIO_OUT = AudioCapability(
    AudioFormat(22050, 2, 16),
    rates=None,
    channels=(1, 2),
    native_channels=2,
    bits=(16,),
    wire=DACWire("PA4", "PA5"),
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """The headphone jack's DAC: a raw ``PCMOutput``. Push bytes with ``write()``.

    ``format`` is the write() contract; ``None`` is 22.05 kHz stereo 16-bit.
    ``latency`` and ``queue_ms`` are accepted for the role's call shape; the
    pump's ring is fixed. A caller writing faster than realtime should gate
    on ``space()``: what doesn't fit the stash is dropped rather than
    blocking the interpreter.
    """
    from audiodev import check_latency, pace_output
    from audiodev.pump import PumpPCMOutput

    check_latency(latency)
    wire, _source = negotiate(AUDIO_OUT, format)
    return pace_output(PumpPCMOutput(wire, wire=AUDIO_OUT.wire))


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over the DAC: ``play(sample, loop=)``,
    ``stop()``, ``pause()``, ``resume()`` and ``playing`` over any audiosample.
    """
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
