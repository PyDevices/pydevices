# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Audio roles for a Raspberry Pi with a PiTFT, through the Pi's own sound output.

Audio roles follow the shared contract (docs/guides/audio.md): one name, one return
type. ``pcm_out`` hands back a raw ``PCMOutput``; ``audio_out`` hands back an
``AudioOut`` sample player. The Pi has no microphone, so there is no ``pcm_in``.
Sound goes wherever the Pi sends it: the headphone jack, or HDMI when a screen
with speakers is connected.
"""

import sys

import boarddev
from audiodev import AudioCapability, AudioFactory, AudioFormat, adapt_channels, negotiate

PERIPHERALS = frozenset({"audio_out", "pcm_out"})

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = PERIPHERALS

_DEFAULT = AudioFormat(24000, 1, 16)

# The Pi's sound server takes whatever it is handed and resamples, so rates
# are continuous and both channel counts open natively.
AUDIO_OUT = AudioCapability(
    _DEFAULT, rates=None, channels=(1, 2), native_channels=2, bits=(8, 16, 32)
)

_BACKEND = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _select_backend():
    global _BACKEND
    if _BACKEND is None:
        from audiodev.auto import select_backend

        _BACKEND = select_backend()
    return _BACKEND


def _pcm_out(format=None, **kwargs):
    """Raw PCM sink at *format* (``None`` = this board's default).

    Keyword arguments go straight to the selected transport (``latency``,
    ``samples``, ``queue_ms``, ``coalesce_ms``, ``poll_ms``). An interactive
    caller asks for ``latency="low"``; the default stays buffered for
    throughput.
    """
    from audiodev.auto import pcm_out as _auto

    wire, source = negotiate(AUDIO_OUT, format)
    _select_backend()
    device = _auto(wire, **kwargs)
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return device


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player: ``play(sample, loop=)``/``stop()``/
    ``pause()``/``resume()``/``playing`` over any CircuitPython-shaped
    audiosample (``synthio.Synthesizer``, ``audiomixer.Mixer``,
    ``audiocore.RawSample``/``WaveFile``, effects).

    Requires audiodsp; use ``pcm_out`` if you only have PCM bytes.
    """
    from audiodev.auto import audio_out as _auto

    wire, source = negotiate(AUDIO_OUT, format)
    if source is not wire:
        raise ValueError("audio_out does not remix; use pcm_out")
    _select_backend()
    return _auto(wire, **kwargs)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
