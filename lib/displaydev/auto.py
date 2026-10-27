# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Optional host backend selection. Backends never import this module.

Selects ``PSDisplay`` / ``JNDisplay`` / ``WinDisplay``→``PGDisplay``→
``SDLDisplay`` (or Android ``AndroidSDLDisplay``) from the host so
board configs stay MCU-shaped wiring only. Explicit boards import a backend
directly; this factory is convenience only.

Returns the display driver directly. Desktop drivers expose ``get_events`` for
``appdev.App(host_read=...)``.

The host backends are rows of the :mod:`backends` registry (experimental), so a
backend of your own can join them. See "Experimental: your own backend" in
docs/guides/displays.md.
"""

import sys

import backends

__all__ = ["AutoDisplay", "host_kind"]


def host_kind():
    """Return ``"wasm"``, ``"android"``, ``"pyscript"``, ``"jupyter"``, or ``"desktop"``."""
    try:
        import _wasm_bridge  # noqa: F401

        return "wasm"
    except ImportError:
        pass
    if sys.platform == "android":
        return "android"
    try:
        import pyscript  # noqa: F401

        return "pyscript"
    except Exception:
        pass
    try:
        get_ipython()  # noqa: F821
        return "jupyter"
    except Exception:
        return "desktop"



# The backends in the box, in the order they are tried. Each probe says whether
# this host can run it; each factory builds it (and may raise Decline, which
# moves on to the next one, the way a failed import always did).
def _on(kind):
    return lambda: host_kind() == kind


def _on_windows():
    return host_kind() == "desktop" and sys.platform == "win32"


def _on_desktop():
    return host_kind() == "desktop"


_BUILTIN = (
    ("wasm", "displaydev.auto:_make_wasm", _on("wasm")),
    ("pyscript", "displaydev.auto:_make_pyscript", _on("pyscript")),
    ("jupyter", "displaydev.auto:_make_jupyter", _on("jupyter")),
    ("android", "displaydev.auto:_make_android", _on("android")),
    ("win", "displaydev.auto:_make_win", _on_windows),
    ("pygame", "displaydev.auto:_make_pygame", _on_desktop),
    ("sdl", "displaydev.auto:_make_sdl", _on_desktop),
)

for _name, _spec, _probe in _BUILTIN:
    backends.register("display", _name, _spec, probe=_probe, builtin=True)


def _make_wasm(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    from displaydev.wasmdisplay import WasmDisplay

    return WasmDisplay(width, height, canvas_id, quiet=quiet)


def _make_pyscript(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    from displaydev.psdisplay import PSDisplay

    return PSDisplay(canvas_id, width, height, quiet=quiet)


def _make_jupyter(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    from displaydev.jndisplay import JNDisplay

    return JNDisplay(width, height, quiet=quiet)


def _make_android(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    import usdl2

    from displaydev.androidsdl import AndroidSDLDisplay

    # Do not use SDL_WINDOW_FULLSCREEN_DESKTOP: it toggles immersive mode after
    # the Activity SurfaceView/GL buffers are created, and Android then rejects
    # presents (BLASTBufferQueue size mismatch → black screen after splash).
    # buildozer.spec keeps fullscreen=0; SHOWN + HIGHDPI matches that surface.
    # AndroidSDLDisplay locks Activity orientation from logical aspect.
    return AndroidSDLDisplay(
        width=width,
        height=height,
        rotation=rotation,
        title=title,
        scale=scale,
        quiet=quiet,
        window_flags=(usdl2.SDL_WINDOW_SHOWN | usdl2.SDL_WINDOW_ALLOW_HIGHDPI),
    )


def _make_win(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    try:
        from displaydev.windisplay import WinDisplay

        return WinDisplay(
            width=width,
            height=height,
            rotation=rotation,
            title=title,
            scale=scale,
            quiet=quiet,
            maximized=maximized,
        )
    except Exception:
        pass
    # pygame / SDL fallback: SDL2 WASAPI glitches with pygame small-chunk
    # playback; DirectSound does not. Must land before PGDisplay.pg.init().
    from boarddev import env_get, env_set

    if env_get("SDL_AUDIODRIVER") is None:
        env_set("SDL_AUDIODRIVER", "directsound")
    raise backends.Decline("WinDisplay")


def _make_pygame(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    try:
        from displaydev.pgdisplay import PGDisplay
    except Exception:
        raise backends.Decline("PGDisplay")
    return PGDisplay(
        width=width,
        height=height,
        rotation=rotation,
        title=title,
        scale=scale,
        quiet=quiet,
    )


def _make_sdl(width, height, rotation, scale, title, canvas_id, quiet, maximized):
    from displaydev.sdldisplay import SDLDisplay

    return SDLDisplay(
        width=width,
        height=height,
        rotation=rotation,
        title=title,
        scale=scale,
        quiet=quiet,
    )


def AutoDisplay(
    width=320,
    height=240,
    rotation=0,
    scale=1.0,
    title="displaydev",
    canvas_id=None,
    *,
    quiet=False,
    maximized=False,
    **kwargs
):
    """Construct a host-appropriate display driver.

    Args:
        width, height, rotation, scale, title: Forwarded to PG/SDL constructors
            (PS/JN ignore rotation/scale/title as their APIs dictate).
        canvas_id: PyScript canvas DOM id for the primary ``PSDisplay``.
        quiet: Suppress driver init chatter when True.
        maximized: Open maximised, the panel exactly the window's client area
            at scale 1 (width, height and scale are then ignored). WinDisplay
            only, for now; the other backends open at width x height.
        **kwargs: Experimental. Passed on to the backend that wins, so a
            registered backend can take its own options (``tv=...``).

    The search order (experimental) is the ``PYDEVICES_DISPLAY`` environment
    variable, then the backends a board config asked for with ``require``, then the ones in
    the box. See :mod:`backends`.

    Returns:
        A ``PSDisplay``, ``JNDisplay``, ``WinDisplay``, ``PGDisplay``, or
        ``SDLDisplay`` with ``get_events`` set for board_config wiring; or
        whatever registered backend was asked for.
    """
    from boarddev import env_get

    if canvas_id is None:
        canvas_id = env_get("PYDEVICES_CANVAS_ID", "display_canvas")
    override = env_get("PYDEVICES_DISPLAY")

    for name, spec, builtin in backends.candidates("display", override):
        try:
            factory = backends.load(spec)
            if builtin:
                if kwargs:
                    raise TypeError(
                        "AutoDisplay() got %s, which the %s backend doesn't take"
                        % (", ".join(sorted(kwargs)), name)
                    )
                return factory(width, height, rotation, scale, title, canvas_id, quiet, maximized)
            # a backend from outside the box gets the size and what you added
            return factory(width=width, height=height, **kwargs)
        except backends.Decline:
            if override:
                raise ImportError(
                    "display backend %r (PYDEVICES_DISPLAY) can't run here" % name
                )
    raise ImportError(
        "no usable display backend; the ones registered are: %s"
        % ", ".join(backends.names("display"))
    )
