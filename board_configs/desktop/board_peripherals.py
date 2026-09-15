"""Audio roles for desktop hosts, over whichever backend this machine has.

Audio roles follow the shared contract (docs/audio.md): one name, one return
type. ``pcm_out``/``pcm_in`` hand back a raw ``PCMOutput``/``PCMInput``;
``audio_out`` hands back an ``AudioOut`` sample player. There is no
``audio_in`` -- capture has no player layer.

Unlike the single-backend host packages beside this one, the backend here is
probed at first use via ``audiodev.auto``.
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
    """Raw PCM sink at *format* (``None`` = this host's default).

    Keyword arguments go straight to the selected transport, which is why
    sdl2/win agree on names (``latency``, ``samples``, ``queue_ms``,
    ``coalesce_ms``, ``poll_ms``). An interactive caller asks for
    ``latency="low"``; the default stays buffered for throughput.
    """
    from audiodev.auto import pcm_out as _auto

    wire, source = negotiate(AUDIO_OUT, format)
    _select_backend()
    device = _auto(wire, **kwargs)
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return device


def _pcm_in(format=None, **kwargs):
    """Raw PCM source at *format*; see :func:`_pcm_out` for the keywords."""
    from audiodev.auto import pcm_in as _auto

    wire, _ = negotiate(AUDIO_IN, format)
    if _select_backend() == "sdl2_audio":
        # Shorter than the backend default: capture is consumed live here, so
        # a long queue only adds lag to whatever is listening.
        kwargs.setdefault("queue_ms", 150)
    return _auto(wire, **kwargs)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player: ``play(sample, loop=)``/``stop()``/
    ``pause()``/``resume()``/``playing`` over any CircuitPython-shaped
    audiosample (``synthio.Synthesizer``, ``audiomixer.Mixer``,
    ``audiocore.RawSample``/``WaveFile``, effects).

    Requires audioif; use ``pcm_out`` if you only have PCM bytes.
    """
    from audiodev.auto import audio_out as _auto

    wire, source = negotiate(AUDIO_OUT, format)
    if source is not wire:
        raise ValueError("desktop audio_out does not remix; use pcm_out")
    _select_backend()
    return _auto(wire, **kwargs)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
