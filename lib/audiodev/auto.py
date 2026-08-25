"""Optional host backend selection. Backends never import this module."""

import sys


def host_kind():
    try:
        import _wasm_bridge  # noqa: F401

        return "wasm"
    except ImportError:
        pass
    try:
        get_ipython()  # noqa: F821
        return "jupyter"
    except Exception:
        return "desktop"


def _uwin32_available():
    if sys.platform != "win32":
        return False
    try:
        import uwin32  # noqa: F401

        return True
    except Exception:
        return False


def _module_available(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _is_micropython():
    return getattr(getattr(sys, "implementation", None), "name", "") == "micropython"


def select_backend():
    """Return the first usable output backend in the documented probe order."""
    if _is_micropython() and _module_available("_wasm_bridge"):
        return "wasm_audio"
    if not _is_micropython() and sys.platform == "emscripten":
        return "web_audio"
    if _uwin32_available():
        return "win_audio"
    if _module_available("usdl2"):
        return "sdl2_audio"
    if not _is_micropython() and _module_available("pygame"):
        return "pygame_audio"
    raise ImportError(
        "no usable audio transport: install pygame-ce, install/provide usdl2, "
        "or explicitly wrap an SDL, WASAPI, Web Audio, I2S, wasm, or emulated transport"
    )


def _impl(name, direction):
    if name == "wasm_audio":
        from audiodev import wasm_audio as mod
    elif name == "win_audio":
        from audiodev import win_audio as mod
    elif name == "sdl2_audio":
        from audiodev import sdl2_audio as mod
    elif name == "web_audio":
        from audiodev import web_audio as mod
    elif name == "pygame_audio":
        from audiodev import pygame_audio as mod
    else:
        raise ValueError("unknown audiodev backend: %s" % name)
    return getattr(mod, direction)


def audio_out(format=None, **kwargs):
    """Construct a raw PCM transport via :func:`select_backend`.

    Low-level escape hatch (raw ``write()``); most callers want
    :func:`sample_audio_out`, which wraps this in an :class:`AudioOut` sample
    player.
    """
    return _impl(select_backend(), "audio_out")(format, **kwargs)


def audio_in(format=None, **kwargs):
    """Construct capture via :func:`select_backend`. Forward kwargs unchanged."""
    return _impl(select_backend(), "audio_in")(format, **kwargs)


def sample_audio_out(format=None, **kwargs):
    """Construct an :class:`~audiodev.sample_out.AudioOut` sample player via
    :func:`select_backend`. This is what a board's ``audio_out`` role returns.

    ``chunk_ms``/``lookahead_chunks``/``max_catchup_chunks`` go to the
    :class:`AudioOut` pump; everything else goes to the transport factory.
    ``latency="low"`` also shrinks the pump's chunk to 20ms (a 40ms schedule
    with the default 2-chunk lookahead) -- the transport profile alone cannot
    lower note-to-sound latency below what the pump keeps rendered ahead."""
    from audiodev.sample_out import AudioOut

    pump_kwargs = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump_kwargs[key] = kwargs.pop(key)
    if kwargs.get("latency") == "low":
        pump_kwargs.setdefault("chunk_ms", 10)
    return AudioOut(audio_out(format, **kwargs), **pump_kwargs)


def AutoAudio(format=None, **kwargs):
    """Convenience alias for :func:`sample_audio_out`."""
    return sample_audio_out(format, **kwargs)
