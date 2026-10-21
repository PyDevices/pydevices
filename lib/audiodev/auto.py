"""Optional host backend selection. Backends never import this module."""

import sys

import backends


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


def _wasm_probe():
    return _is_micropython() and _module_available("_wasm_bridge")


def _web_probe():
    return not _is_micropython() and sys.platform == "emscripten"


def _pygame_probe():
    return not _is_micropython() and _module_available("pygame")


# The transports in the box, in the order they are tried. A spec names a module
# that provides ``pcm_out`` and ``pcm_in``.
for _name, _spec, _probe in (
    ("wasm_audio", "audiodev.wasm_audio", _wasm_probe),
    ("web_audio", "audiodev.web_audio", _web_probe),
    ("win_audio", "audiodev.win_audio", lambda: _uwin32_available()),
    ("sdl2_audio", "audiodev.sdl2_audio", lambda: _module_available("usdl2")),
    ("pygame_audio", "audiodev.pygame_audio", _pygame_probe),
):
    backends.register("audio", _name, _spec, probe=_probe, builtin=True)


def select_backend():
    """Return the name of the first usable output backend.

    Experimental search order: ``PYDEVICES_AUDIO`` if set, then the backends a
    board config ``require``d (see :mod:`backends`), then the ones in the box
    in the documented probe order: wasm, Web Audio, Windows, SDL2, pygame.
    """
    for name, _spec, _builtin in backends.candidates("audio", backends.env("PYDEVICES_AUDIO")):
        return name
    raise ImportError(
        "no usable audio transport: install pygame-ce, install/provide usdl2, "
        "or explicitly wrap an SDL, WASAPI, Web Audio, I2S, wasm, or emulated transport"
    )


def _impl(name, direction):
    spec = backends.spec("audio", name)
    if spec is None:
        raise ValueError("unknown audiodev backend: %s" % name)
    return getattr(backends.load(spec), direction)


def pcm_out(format=None, **kwargs):
    """Construct a raw :class:`~audiodev.PCMOutput` via :func:`select_backend`.

    Push bytes at it with ``write()``. This is what a consumer that already
    has PCM wants -- a Connect speaker, a USB audio pump -- and it needs no
    audiodsp, because no sample graph is ever pulled.
    """
    return _impl(select_backend(), "pcm_out")(format, **kwargs)


def pcm_in(format=None, **kwargs):
    """Construct a raw :class:`~audiodev.PCMInput` via :func:`select_backend`."""
    return _impl(select_backend(), "pcm_in")(format, **kwargs)


def audio_out(format=None, **kwargs):
    """Construct an :class:`~audiodev.sample_out.AudioOut` sample player.

    ``play(sample)`` over a CircuitPython-shaped audiosample. This is what a
    board's ``audio_out`` role returns, and the name means the same thing
    here as it does there -- see ``pcm_out`` for the raw sink.

    ``chunk_ms``/``lookahead_chunks``/``max_catchup_chunks`` go to the
    :class:`AudioOut` pump; everything else goes to the transport factory.
    ``latency="low"`` also shrinks the pump's chunk to 20ms (a 40ms schedule
    with the default 2-chunk lookahead) -- the transport profile alone cannot
    lower note-to-sound latency below what the pump keeps rendered ahead.
    """
    from audiodev.sample_out import AudioOut

    pump_kwargs = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump_kwargs[key] = kwargs.pop(key)
    if kwargs.get("latency") == "low":
        pump_kwargs.setdefault("chunk_ms", 10)
        if sys.platform == "win32":
            # WASAPI shared mode plus soft timers can stall the pump for
            # tens of ms; a 2-chunk (20ms) cushion starved audibly (a click
            # at nearly every note - measured 68 buffer-empty events in 12s
            # of the drum machine). Six chunks (60ms) measured 2, at a
            # note-to-sound cost that stays acceptable for live pads.
            pump_kwargs.setdefault("lookahead_chunks", 6)
        elif host_kind() == "wasm":
            # A browser is the same shape and for the same reason. The 10ms
            # tick this profile asks for is not what a page delivers: the
            # gallery's piano, measured buffer by buffer out of the page's
            # own AudioContext, gets one every 23ms and sometimes 90. A
            # 2-chunk cushion is 20ms, so the sink is dry before the next
            # tick BY CONSTRUCTION -- measured as ~10 gaps a second, 2-6% of
            # the stream replaced by silence, which is a continuous granular
            # crackle under the note. Six chunks is 60ms, past the median tick and past all
            # but the worst.
            pump_kwargs.setdefault("lookahead_chunks", 6)
    return AudioOut(pcm_out(format, **kwargs), **pump_kwargs)
