"""Optional C accelerators for audiodev, from audioif when it is present.

This module exists to be a *choice*. ``audiodev/__init__.py`` and every
transport backend import no audioif at all -- that is what lets a headless
PCM consumer (a Spotify Connect speaker, a USB audio pump) run on firmware
with no DSP package in it. But the pure-Python channel remix in
``audiodev`` is a per-sample Python loop, which is fine for a 10 ms chunk on
a desktop and much too slow for 44.1 kHz stereo on an MCU.

So the fast path is offered here rather than reached for there. A caller
that has audioif asks::

    from audiodev.accel import best_remix
    pcm = adapt_channels(pcm, fmt, remix=best_remix())

and a caller that does not, does not import this module. The dependency
arrow never inverts, and nothing silently degrades: ``best_remix()`` returns
``None`` when no C implementation is available, which ``adapt_channels``
reads as "use the portable one".

``audiodev.sample_out`` already requires audioif (it pulls
``audiocore.get_buffer``), so it may use this freely.
"""


def best_remix():
    """Return ``audiomath.remix_s16``, or ``None`` when audioif is absent.

    ``audiomath`` is the MicroPython usermod name; ``_audioif`` is the
    CPython extension. Both expose the same shared C
    (``src/shared/audioif_remix.c``).
    """
    try:
        from audiomath import remix_s16

        return remix_s16
    except ImportError:
        pass
    try:
        from _audioif import remix_s16

        return remix_s16
    except ImportError:
        return None


def have_accel():
    """True when a C remix is available. Useful in a board's self-test."""
    return best_remix() is not None


__all__ = ("best_remix", "have_accel")
