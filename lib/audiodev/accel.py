"""Optional C accelerators for audiodev, from audioif when it is present.

This module exists to be a *choice*. ``audiodev/__init__.py`` and every
transport backend import no audioif at all -- that is what lets a headless
PCM consumer (a Spotify Connect speaker, a USB audio pump) run on firmware
with no DSP package in it. But the pure-Python channel remix in
``audiodev`` is a per-sample Python loop, which is fine for a 10 ms chunk on
a desktop and much too slow for 44.1 kHz stereo on an MCU.

**How slow is slow.** Measured on a QT Py ESP32 Pico (240 MHz), converting a
10 ms chunk of stereo to mono with the portable implementation:

    16000 Hz   6.3 ms   0.63x realtime   usable
    24000 Hz   9.4 ms   0.94x realtime   marginal, no headroom for an app
    44100 Hz  17.3 ms   1.73x realtime   cannot feed a live stream

So the common claim that ``pcm_out`` needs no audioif in firmware holds only
while the format matches the wire -- which is the usual case, because a board
whose wire takes two slots needs no remix at all. A board that must genuinely
mix down at a high rate needs the C implementation, and therefore needs
audioif built in. Offline or low-rate work is fine on the portable one.

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
