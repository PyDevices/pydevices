"""Lazy audio devices for the dedicated JNDisplay board package."""

import sys

import boarddev

PERIPHERALS = frozenset({"audio_out", "audio_in"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _format():
    from audiodev import AudioFormat

    return AudioFormat(24000, 1, 16)


def audio_out(**kwargs):
    """Build the AudioOut sample player; keywords go straight to the sdl2
    transport.

    A notebook cell drives ``service()`` from its own loop (or calls
    ``.transport.write()`` directly for raw PCM), so the queue is kept short
    by default rather than at the backend's buffered depth.
    """
    from audiodev.sample_out import sample_out
    from audiodev import sdl2_audio

    kwargs.setdefault("queue_ms", 150)
    return sample_out(sdl2_audio, _format(), **kwargs)


def audio_in(**kwargs):
    """Build the capture device; see :func:`audio_out` for the keyword contract."""
    from audiodev.sdl2_audio import audio_in as _audio_in

    kwargs.setdefault("queue_ms", 150)
    return _audio_in(_format(), **kwargs)
