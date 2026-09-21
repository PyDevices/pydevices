"""Audio roles for the dedicated PGDisplay board package.

Audio roles follow the shared contract (docs/audio.md): one name, one return
type. ``pcm_out``/``pcm_in`` hand back a raw ``PCMOutput``/``PCMInput``;
``audio_out`` hands back an ``AudioOut`` sample player. There is no
``audio_in`` -- capture has no player layer.
"""

import sys

import boarddev
from audiodev import AudioCapability, AudioFactory, AudioFormat, adapt_channels, negotiate

PERIPHERALS = frozenset({"audio_out", "pcm_out", "pcm_in"})

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = PERIPHERALS

_DEFAULT = AudioFormat(24000, 1, 16)

# A host mixer takes whatever it is handed and resamples in the OS layer, so
# rates are continuous and both channel counts open natively.
AUDIO_OUT = AudioCapability(
    _DEFAULT, rates=None, channels=(1, 2), native_channels=2, bits=(8, 16, 32)
)
AUDIO_IN = AudioCapability(
    _DEFAULT, rates=None, channels=(1, 2), native_channels=1, bits=(8, 16, 32)
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _backend():
    from audiodev import pygame_audio

    return pygame_audio


def _pcm_out(format=None, **kwargs):
    """Raw PCM sink at *format* (``None`` = this host's default)."""
    wire, source = negotiate(AUDIO_OUT, format)
    device = _backend().pcm_out(wire, **kwargs)
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return device


def _pcm_in(format=None, **kwargs):
    """Raw PCM source at *format* (``None`` = this host's default)."""
    wire, _ = negotiate(AUDIO_IN, format)
    return _backend().pcm_in(wire, **kwargs)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player: ``play(sample, loop=)``/``stop()``/
    ``pause()``/``resume()``/``playing`` over any CircuitPython-shaped
    audiosample. Requires audiodsp; use ``pcm_out`` if you only have PCM."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
