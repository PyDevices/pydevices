# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Shared support for the non-MCU (desktop) display backends.

Everything here is host-side: desktop work-area probing, window scale fitting,
and the :class:`DesktopDisplay` base shared by ``SDLDisplay``, ``PGDisplay``,
``WinDisplay``, ``PSDisplay``, ``JNDisplay``, and ``AndroidSDLDisplay``.

MCU backends (``busdisplay``, ``fbdisplay``, ``pixeldisplay``) stay on
``DisplayDriver`` and never import this module, so none of this code lands on
a microcontroller. ``displaydev/__init__.py`` must never import it either --
the dependency runs one way.
"""

import sys

from displaydev import (
    _DESKTOP_SCALE_MARGIN,
    _DESKTOP_WINDOW_CHROME_H,
    _DESKTOP_WINDOW_CHROME_W,
    DisplayDriver,
)

def desktop_work_area(display_index=0):
    """Return ``(x, y, w, h)`` of the usable work area, or zeros if unknown.

    Prefers the OS work area (taskbar / dock excluded). Used by desktop drivers
    that do not have a native usable-bounds API (e.g. PyGame).
    """
    display_index = int(display_index)
    if sys.platform == "win32":
        try:
            import uwin32

            area = uwin32.SystemParametersInfoW_GETWORKAREA()
            if area[2] > 0 and area[3] > 0:
                return area
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes

            class _RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = _RECT()
            # SPI_GETWORKAREA
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                w = int(rect.right - rect.left)
                h = int(rect.bottom - rect.top)
                if w > 0 and h > 0:
                    return int(rect.left), int(rect.top), w, h
        except Exception:
            pass

    # SDL2 usable bounds when libSDL2 is loadable (CPython desktop).
    try:
        import ctypes

        sdl = None
        for name in ("SDL2", "SDL2-2.0", "libSDL2-2.0.so.0", "libSDL2.so"):
            try:
                sdl = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if sdl is not None and hasattr(sdl, "SDL_GetDisplayUsableBounds"):

            class _SDL_Rect(ctypes.Structure):
                _fields_ = [
                    ("x", ctypes.c_int),
                    ("y", ctypes.c_int),
                    ("w", ctypes.c_int),
                    ("h", ctypes.c_int),
                ]

            rect = _SDL_Rect()
            fn = sdl.SDL_GetDisplayUsableBounds
            fn.argtypes = [ctypes.c_int, ctypes.POINTER(_SDL_Rect)]
            fn.restype = ctypes.c_int
            if fn(display_index, ctypes.byref(rect)) == 0 and rect.w > 0 and rect.h > 0:
                return int(rect.x), int(rect.y), int(rect.w), int(rect.h)
    except Exception:
        pass
    return 0, 0, 0, 0


def fit_scale_to_desktop(
    width,
    height,
    scale,
    desktop_w,
    desktop_h,
    *,
    margin=_DESKTOP_SCALE_MARGIN,
    chrome_w=0,
    chrome_h=0,
):
    """Return the largest scale <= *scale* so the window fits on the desktop.

    *desktop_w* / *desktop_h* should be the usable work area when available
    (taskbar / dock excluded). *margin* is padding inside that area; *chrome_w*
    / *chrome_h* reserve OS window frame outside the client (title bar, borders).
    """
    if scale <= 0 or desktop_w <= 0 or desktop_h <= 0:
        return 1.0 if scale <= 0 else scale
    max_w = desktop_w - margin - chrome_w
    max_h = desktop_h - margin - chrome_h
    if max_w <= 0 or max_h <= 0:
        return scale
    fit = min(max_w / width, max_h / height)
    if fit < scale:
        return fit
    return scale


def notify_board_config_scale_override(driver_name, requested, fitted, *, quiet=False):
    """Tell the user when a desktop driver reduces board_config scale to fit the screen.

    Args:
        driver_name: Display class name for the log line (e.g. ``"SDLDisplay"``).
        requested: Scale requested by board_config / constructor.
        fitted: Scale after :func:`fit_scale_to_desktop`.
        quiet: When True, skip printing.
    """
    if quiet or fitted == requested:
        return
    print(
        f"{driver_name}: overriding board_config scale {requested} -> {fitted:.2f} to fit desktop"
    )


class DesktopDisplay(DisplayDriver):
    """Base for every non-MCU backend ``displaydev.auto`` can select.

    Carries the vertical-scroll overrides and the window scale fit that the
    host backends would otherwise each copy. Subclasses say what a scroll
    change means by overriding :meth:`_scroll_changed`.
    """

    _render_dirty = False
    _scale = 1.0

    def _scroll_changed(self) -> None:
        """React to a scroll definition / offset change.

        Default marks the frame dirty for the next ``show()``; backends that
        repaint eagerly (PSDisplay, JNDisplay) override this to render.
        """
        self._render_dirty = True

    def _reset_vscroll(self) -> None:
        """Set a full-height scroll region without repainting.

        Backends call this from ``init()``, where the surface may not be ready
        to paint yet. Goes straight to ``DisplayDriver`` so
        :meth:`_scroll_changed` does not fire mid-init; the frame is marked
        dirty so the first ``show()`` still composites.
        """
        DisplayDriver.vscrdef(self, 0, self.height, 0)
        self._vssa = False
        self._render_dirty = True

    def vscrdef(self, tfa: int, vsa: int, bfa: int) -> None:
        """
        Set the vertical scroll definition.

        Args:
            tfa (int): The top fixed area.
            vsa (int): The vertical scroll area.
            bfa (int): The bottom fixed area.
        """
        super().vscrdef(tfa, vsa, bfa)
        self._scroll_changed()

    def vscsad(self, vssa=None) -> int:
        """
        Set or get the vertical scroll start address.

        Args:
            vssa (int): The vertical scroll start address. Defaults to None.

        Returns:
            int: The vertical scroll start address.
        """
        if vssa is not None:
            super().vscsad(vssa)
            self._scroll_changed()
        return self._vssa

    def _fit_scale(self, desktop_w, desktop_h, quiet, requested=None):
        """Return the largest scale <= ``requested`` that fits the work area.

        Announces the override when board_config asked for more than fits.

        Args:
            desktop_w (int): Usable work area width, or 0 when unknown.
            desktop_h (int): Usable work area height, or 0 when unknown.
            quiet (bool): When True, skip the override notice.
            requested (float): The scale board_config asked for (default:
                ``self._scale``). Pass it again to refit after a rotation, so a
                scale shrunk for one orientation can grow back in the other.

        Returns:
            float: The fitted scale.
        """
        if requested is None:
            requested = self._scale
        fitted = fit_scale_to_desktop(
            self.width,
            self.height,
            requested,
            desktop_w,
            desktop_h,
            chrome_w=_DESKTOP_WINDOW_CHROME_W,
            chrome_h=_DESKTOP_WINDOW_CHROME_H,
        )
        notify_board_config_scale_override(
            self.__class__.__name__, requested, fitted, quiet=quiet
        )
        return fitted


class FrameRecorderMixin:
    """ffmpeg recording for backends that can export the visible frame as RGB24.

    Mixed into ``SDLDisplay`` and ``PGDisplay`` only. Backends without an RGB24
    export path do not get these methods, so ``hasattr(display,
    "open_frame_recorder")`` stays a meaningful capability check.
    """

    _frame_recorder = None

    @property
    def frame_recording(self) -> bool:
        """True while an ffmpeg frame recorder is attached."""
        return self._frame_recorder is not None

    def open_frame_recorder(self, path, *, fps=12, width=None, height=None):
        """Attach an ffmpeg recorder that receives one RGB24 frame per ``show()``."""
        from frame_recorder import FFmpegFrameRecorder

        self.close_frame_recorder()
        w = int(self.width * self._scale) if width is None else width
        h = int(self.height * self._scale) if height is None else height
        self._frame_recorder = FFmpegFrameRecorder(path, w, h, fps)
        return self._frame_recorder

    def close_frame_recorder(self):
        """Finalize and detach the active frame recorder."""
        recorder = self._frame_recorder
        self._frame_recorder = None
        if recorder is not None:
            return recorder.close()
        return 0

    def _record_frame(self, rgb_bytes) -> None:
        recorder = self._frame_recorder
        if recorder is not None:
            recorder.write(rgb_bytes)
