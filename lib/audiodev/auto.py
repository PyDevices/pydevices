"""Optional host backend selection. Backends never import this module.

``pygame_audio`` and ``web_audio`` (PyScript/Pyodide) are no longer offered
here: both run an interpreter that cannot load the ``audioif``
usermod, so neither can ever back an :class:`~audiodev.sample_out.AudioOut`
-- see docs/audio.md. Both modules still exist and still work as raw PCM
transports (``write()``/``readinto()``, no sample playback); the boards that
want them (``pgdisplay``, ``psdisplay``) import them directly rather than
through :func:`select_backend`. Auto-selected desktop backends are now
MicroPython/CircuitPython-only: ``win_audio`` on Windows (via ``uwin32``),
``sdl2_audio`` everywhere else (via ``usdl2``).
"""

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


def select_backend():
    """Return ``wasm_audio``, ``win_audio``, or ``sdl2_audio``."""
    kind = host_kind()
    if kind == "wasm":
        return "wasm_audio"
    if kind == "jupyter":
        return "sdl2_audio"
    if _uwin32_available():
        return "win_audio"
    return "sdl2_audio"


def _impl(name, direction):
    if name == "wasm_audio":
        from audiodev import wasm_audio as mod
    elif name == "win_audio":
        from audiodev import win_audio as mod
    else:
        from audiodev import sdl2_audio as mod
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
    :func:`select_backend`. This is what a board's ``audio_out`` role returns."""
    from audiodev.sample_out import AudioOut

    return AudioOut(audio_out(format, **kwargs))


def AutoAudio(format=None, **kwargs):
    """Convenience alias for :func:`sample_audio_out`."""
    return sample_audio_out(format, **kwargs)
