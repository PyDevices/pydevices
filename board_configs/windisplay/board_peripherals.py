"""Lazy audio devices for the dedicated WinDisplay board package."""

import sys

import boarddev

PERIPHERALS = frozenset({"audio_out", "audio_in"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _format():
    from audiodev import AudioFormat

    return AudioFormat(24000, 1, 16)


def audio_out(**kwargs):
    """Build the AudioOut sample player; keywords go straight to the win_audio
    transport."""
    from audiodev.sample_out import sample_out
    from audiodev import win_audio

    return sample_out(win_audio, _format(), **kwargs)


def audio_in(**kwargs):
    """Build the capture device; keywords go straight to the backend."""
    from audiodev.win_audio import audio_in as _audio_in

    return _audio_in(_format(), **kwargs)
