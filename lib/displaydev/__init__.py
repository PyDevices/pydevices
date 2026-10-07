# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Portable display driver core for MicroPython, CircuitPython, and CPython.

Each backend is a separate submodule; import only what your target needs::

    from displaydev import DisplayDriver, color565, capabilities
    from displaydev.busdisplay import BusDisplay

Optional host selection lives in :mod:`displaydev.auto` and is never imported
from here. Backends never import that module.
"""

import gc
import sys

try:
    import micropython as _mp
except ImportError:  # bare CPython
    _mp = None


def _mp_native(f):
    """Apply ``@micropython.native`` when the port provides it."""
    deco = getattr(_mp, "native", None) if _mp is not None else None
    return deco(f) if deco is not None else f


def _install_byteswap():
    """Select a fast array implementation when available, else portable Python."""
    try:
        try:
            import numpy as np
        except ImportError:
            from ulab import numpy as np

        def byteswap(buf):
            """Swap a 16-bit pixel buffer in place using numpy or ulab."""
            npbuf = np.frombuffer(buf, dtype=np.uint16)
            npbuf.byteswap(inplace=True)

        return byteswap, "array"
    except Exception:
        pass

    @_mp_native
    def byteswap(buf):
        """Swap 16-bit pixel bytes in place (portable fallback)."""
        n = len(buf)
        if n & 1:
            raise ValueError("buffer size must be a multiple of 2")
        for i in range(0, n, 2):
            b0 = buf[i]
            buf[i] = buf[i + 1]
            buf[i + 1] = b0

    return byteswap, "native" if getattr(_mp, "native", None) else "pure_python"


byteswap, _BYTESWAP_BACKEND = _install_byteswap()

__all__ = [
    "DisplayDriver",
    "alloc_buffer",
    "byteswap",
    "capabilities",
    "color332",
    "color565",
    "color565_swapped",
    "color_rgb",
    "env_bool",
    "env_float",
    "env_get",
    "env_int",
    "env_set",
]

_DEFAULT_AUTO_REFRESH_PERIOD = 33
_DESKTOP_SCALE_MARGIN = 48
# OS window frame outside the client area (title bar / borders). Usable display
# bounds exclude the taskbar/dock but not chrome; reserve these when fitting.
_DESKTOP_WINDOW_CHROME_W = 16
_DESKTOP_WINDOW_CHROME_H = 48

# Process-local overrides for ports without ``os.environ`` / ``os.putenv``.
_overrides = {}


def env_set(name, value):
    """Set an environment variable portably (CPython, MicroPython, CircuitPython).

    Always records a process-local override so ``env_bool`` sees the value even
    when the host ``os`` module has no ``environ``. When available, also updates
    ``os.environ`` or calls ``os.putenv``.
    """
    text = "" if value is None else str(value)
    _overrides[name] = text

    import os

    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            environ[name] = text
            return
        except Exception:
            pass
    putenv = getattr(os, "putenv", None)
    if putenv is not None:
        try:
            putenv(name, text)
        except Exception:
            pass


def env_bool(name, default=False):
    """Read a truthy/falsey environment variable with a portable fallback chain."""
    raw = _env_raw(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return bool(default)


def env_get(name, default=None):
    """Read a string environment variable portably (honors ``env_set`` overrides)."""
    raw = _env_raw(name)
    if raw is None:
        return default
    return raw


def env_int(name, default=0):
    """Read an integer environment variable portably (honors ``env_set`` overrides)."""
    raw = _env_raw(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


def env_float(name, default=0.0):
    """Read a floating-point environment variable portably."""
    raw = _env_raw(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def _env_raw(name):
    if name in _overrides:
        return _overrides[name]

    import os

    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            value = environ.get(name)
        except Exception:
            value = None
        if value is not None:
            return value
    getenv = getattr(os, "getenv", None)
    if getenv is None:
        return None
    try:
        return getenv(name)
    except Exception:
        return None


def capabilities():
    """Static metadata for the modular displaydev install model (no backend imports)."""
    return {
        "dialect": sys.implementation.name,
        "byteswap": _BYTESWAP_BACKEND,
        "modules": {
            "busdisplay": {"appdev": False, "auto_refresh": False},
            "fbdisplay": {"appdev": False, "auto_refresh": False},
            "pixeldisplay": {"appdev": False, "auto_refresh": False},
            "sdldisplay": {
                "appdev": True,
                "auto_refresh": True,
                "default_period_ms": _DEFAULT_AUTO_REFRESH_PERIOD,
                "async_default": False,
                "touch_scale": "1.0 (logical renderer size)",
                "scroll_emulation": True,
            },
            "pgdisplay": {
                "appdev": True,
                "auto_refresh": True,
                "default_period_ms": _DEFAULT_AUTO_REFRESH_PERIOD,
                "async_default": False,
                "touch_scale": "window scale",
                "scroll_emulation": True,
            },
            "windisplay": {
                "appdev": True,
                "auto_refresh": True,
                "default_period_ms": _DEFAULT_AUTO_REFRESH_PERIOD,
                "async_default": False,
                "touch_scale": "1.0 (wndproc maps to panel coords)",
                "scroll_emulation": True,
            },
            "psdisplay": {
                "appdev": True,
                "auto_refresh": True,
                "default_period_ms": _DEFAULT_AUTO_REFRESH_PERIOD,
                "async_default": True,
                "touch_scale": "canvas layout scale",
                "scroll_emulation": True,
            },
            "jndisplay": {
                "appdev": True,
                "auto_refresh": True,
                "default_period_ms": _DEFAULT_AUTO_REFRESH_PERIOD,
                "async_default": True,
                "touch_scale": "1.0",
                "scroll_emulation": True,
            },
            "auto": {
                "appdev": True,
                "auto_refresh": True,
                "host_select": True,
            },
        },
    }


def alloc_buffer(size):
    """
    Create a new buffer of the specified size.

    Prefers SPIRAM/PSRAM when the port exposes it:

    * **MicroPython ESP32** — ``esp32.idf_heap_caps_malloc``-style helpers when
      present; otherwise a normal ``bytearray`` (large objects may still land
      in PSRAM depending on IDF heap config).
    * **CircuitPython** — GC ``bytearray``; on ESP32-S3 boards with PSRAM,
      large allocations are typically served from SPIRAM. For display surfaces,
      prefer ``displayio.Bitmap`` (see ``FBDisplay(..., bitmap=...)``) so paints
      go through C ``bitmaptools`` into PSRAM rather than Python loops.

    Args:
        size (int): The size of the buffer to create.

    Returns:
        (memoryview): The new buffer.
    """
    size = int(size)
    # MicroPython / forks that expose heap_caps to Python.
    for mod_name, fn_name, caps in (
        ("esp32", "idf_heap_caps_malloc", None),
        ("esp32", "heap_caps_malloc", 0x400),  # MALLOC_CAP_SPIRAM on IDF
    ):
        try:
            mod = __import__(mod_name)
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            ptr = fn(size) if caps is None else fn(size, caps)
            if ptr:
                import uctypes

                return memoryview(uctypes.bytearray_at(ptr, size))
        except Exception:
            pass

    return memoryview(bytearray(size))


def color565(r, g=None, b=None):
    """
    Convert RGB values to a 16-bit color value.

    Args:
        r (int, tuple or list): The red value or a tuple or list of RGB values.
        g (int): The green value.
        b (int): The blue value.

    Returns:
        (int): The 16-bit color value
    """
    if isinstance(r, (tuple, list)):
        r, g, b = r[:3]
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def color565_swapped(r, g=0, b=0):
    """
    Convert RGB to 16-bit RGB565 with byte order swapped for some displays.

    Args:
        r (int | tuple | list): Red value, or an (r, g, b) sequence.
        g (int): Green value when r is an int.
        b (int): Blue value when r is an int.

    Returns:
        int: Byte-swapped RGB565 color.
    """
    if isinstance(r, (tuple, list)):
        r, g, b = r[:3]
    color = color565(r, g, b)
    return (color & 0xFF) << 8 | (color & 0xFF00) >> 8


def color332(r, g, b):
    """
    Convert RGB to 8-bit RGB332 color.

    Args:
        r (int): Red (0-255).
        g (int): Green (0-255).
        b (int): Blue (0-255).

    Returns:
        int: RGB332 color byte.
    """
    return (r & 0xE0) | ((g >> 3) & 0x1C) | (b >> 6)


def color_rgb(color):
    """
    Expand a display color to an (r, g, b) tuple.

    Args:
        color (int | tuple | list | bytearray): 16-bit RGB565 int or 2-3 byte sequence.

    Returns:
        tuple[int, int, int]: Red, green, blue (0-255 each).
    """
    if isinstance(color, int):
        # convert 16-bit int color to 2 bytes
        color = (color & 0xFF, color >> 8)
    if len(color) == 2:
        r = color[1] & 0xF8 | (color[1] >> 5) & 0x7  # 5 bit to 8 bit red
        g = color[1] << 5 & 0xE0 | (color[0] >> 3) & 0x1F  # 6 bit to 8 bit green
        b = color[0] << 3 & 0xF8 | (color[0] >> 2) & 0x7  # 5 bit to 8 bit blue
    else:
        r, g, b = color
    return (r, g, b)


@_mp_native
def _blit_transparent_rgb565(blit_rect, buf, x, y, w, h, key):
    """Scan RGB565 runs and blit non-key spans (``@micropython.native`` when available)."""
    key16 = key & 0xFFFF
    k0 = key16 & 0xFF
    k1 = (key16 >> 8) & 0xFF
    stride = w * 2
    for j in range(h):
        rowstart = j * stride
        colstart = 0
        while colstart < stride:
            i = rowstart + colstart
            if buf[i] != k0 or buf[i + 1] != k1:
                colend = colstart + 2
                while colend < stride:
                    ei = rowstart + colend
                    if buf[ei] == k0 and buf[ei + 1] == k1:
                        break
                    colend += 2
                blit_rect(
                    buf[rowstart + colstart : rowstart + colend],
                    x + (colstart >> 1),
                    y + j,
                    (colend - colstart) >> 1,
                    1,
                )
                colstart = colend
            else:
                colstart += 2


@_mp_native
def _blit_transparent_generic(blit_rect, buf, x, y, w, h, bpp, key):
    """Scan packed runs for non-RGB565 depths."""
    key_bytes = key.to_bytes(bpp, "little")
    stride = w * bpp
    for j in range(h):
        rowstart = j * stride
        colstart = 0
        while colstart < stride:
            startoffset = rowstart + colstart
            if buf[startoffset : startoffset + bpp] != key_bytes:
                colend = colstart
                while colend < stride:
                    endoffset = rowstart + colend
                    if buf[endoffset : endoffset + bpp] == key_bytes:
                        break
                    colend += bpp
                blit_rect(
                    buf[rowstart + colstart : rowstart + colend],
                    x + colstart // bpp,
                    y + j,
                    (colend - colstart) // bpp,
                    1,
                )
                colstart = colend
            else:
                colstart += bpp


class FrameClock:
    """A display's frame cadence as a subscription: ``subscribe(fn)`` calls
    ``fn()`` once per frame, on the main thread, from ``multimer``.

    ``period_ms`` is the frame period the backend knows about; ``count`` and
    ``last`` (``ticks_ms``) say what has been delivered; ``stop()`` releases
    the underlying timer. A backend with a host frame signal (vsync, the
    browser's animation frame) subclasses this and overrides ``_start`` /
    ``_stop`` to deliver from that signal instead of a timer.
    """

    def __init__(self, period_ms, name=None):
        self._period_ms = max(1, int(period_ms))
        self.name = name or "frame"
        self.count = 0
        self.last = None
        self._subs = []
        self._timer = None

    @property
    def period_ms(self):
        return self._period_ms

    @period_ms.setter
    def period_ms(self, value):
        value = max(1, int(value))
        if value == self._period_ms:
            return
        self._period_ms = value
        if self._timer is not None:
            self._stop()
            self._start()

    @property
    def running(self):
        return self._timer is not None

    def subscribe(self, fn):
        if not callable(fn):
            raise ValueError("fn must be callable")
        if fn not in self._subs:
            self._subs.append(fn)
        if self._timer is None:
            self._start()
        return fn

    def unsubscribe(self, fn):
        try:
            self._subs.remove(fn)
        except ValueError:
            pass
        if not self._subs:
            self.stop()

    def stop(self):
        self._stop()

    def _start(self):
        import multimer

        self._timer = multimer.every(self._period_ms, self._tick, name=self.name)

    def _stop(self):
        t = self._timer
        self._timer = None
        if t is not None:
            t.deinit()

    def _tick(self, _timer=None):
        self.count += 1
        try:
            from multimer import ticks_ms

            self.last = ticks_ms()
        except ImportError:
            pass
        for fn in tuple(self._subs):
            fn()


_fps_clock_cache = None


def _fps_clock():
    """``(now, diff)`` for timing presents: ``diff(later, earlier)`` is in µs.

    ``time.ticks_us`` on MicroPython, ``perf_counter_ns`` on CPython,
    ``monotonic_ns`` on CircuitPython, and ``supervisor.ticks_ms`` (ms steps)
    on a CircuitPython build without long ints. Chosen on first use, so a
    driver that never measures never pays for it.
    """
    global _fps_clock_cache
    if _fps_clock_cache is None:
        import time

        ticks_us = getattr(time, "ticks_us", None)
        ns = getattr(time, "perf_counter_ns", None) or getattr(time, "monotonic_ns", None)
        if ticks_us is not None:
            _fps_clock_cache = (ticks_us, time.ticks_diff)
        elif ns is not None:

            def now():
                return ns() // 1000

            def diff(a, b):
                return a - b

            _fps_clock_cache = (now, diff)
        else:
            from supervisor import ticks_ms

            def diff_ms(a, b):
                return (((a - b) + 0x10000000) & 0x1FFFFFFF) - 0x10000000

            def diff(a, b):
                return diff_ms(a, b) * 1000

            _fps_clock_cache = (ticks_ms, diff)
    return _fps_clock_cache


class _FpsMeter:
    """Frame and present-time counters for one display (see ``measure_fps``).

    Counts go into a window that is folded into the totals once a second, so
    the per-frame arithmetic stays on small ints (no heap on a board) and the
    last whole second's rate falls out of the fold. Wall time is added up
    between events rather than read against a start time, so a 32-bit
    board's wrapping ``ticks_us`` is fine as long as something happens every
    few minutes (a frame, ``fps()``, the ``fps_print`` line).
    """

    def __init__(self, now, diff):
        self.now = now
        self.diff = diff
        self.reset()

    def reset(self):
        self.mark = self.now()
        self.win_us = 0
        self.win_frames = 0
        self.win_present = 0
        self.win_flushes = 0
        self.win_pixels = 0
        self.frame_us = 0
        self.frame_max = 0
        self.last_fps = None
        self.seconds = 0.0
        self.frames = 0
        self.present_us = 0.0
        self.flushes = 0
        self.pixels = 0

    def _advance(self, t):
        self.win_us += self.diff(t, self.mark)
        self.mark = t
        if self.win_us >= 1000000:
            self._fold()

    def _fold(self):
        w = self.win_us
        if w > 0:
            self.last_fps = self.win_frames * 1000000 / w
        self.seconds += w / 1000000
        self.frames += self.win_frames
        self.present_us += self.win_present
        self.flushes += self.win_flushes
        self.pixels += self.win_pixels
        self.win_us = 0
        self.win_frames = 0
        self.win_present = 0
        self.win_flushes = 0
        self.win_pixels = 0

    def frame(self, t, dt):
        """A present ended at ``t`` after ``dt`` µs; it finished a frame."""
        f = self.frame_us + dt
        self.frame_us = 0
        if f > self.frame_max:
            self.frame_max = f
        self.win_present += dt
        self.win_frames += 1
        self._advance(t)

    def flush(self, t, dt, pixels):
        """A ``flush_rect`` ended at ``t`` after ``dt`` µs: part of a frame."""
        self.frame_us += dt
        self.win_present += dt
        self.win_flushes += 1
        self.win_pixels += pixels
        self._advance(t)

    def snapshot(self):
        self._advance(self.now())
        seconds = self.seconds + self.win_us / 1000000
        frames = self.frames + self.win_frames
        present = self.present_us + self.win_present
        if self.last_fps is not None:
            fps = self.last_fps
        elif self.win_us > 0:
            fps = self.win_frames * 1000000 / self.win_us
        else:
            fps = 0.0
        return {
            "fps": round(fps, 1),
            "avg_fps": round(frames / seconds, 1) if seconds > 0 else 0.0,
            "frames": frames,
            "seconds": round(seconds, 1),
            "present_ms": round(present / frames / 1000, 2) if frames else 0.0,
            "present_ms_max": round(self.frame_max / 1000, 2),
            "busy": round(present / (seconds * 1000000), 3) if seconds > 0 else 0.0,
            "flushes": self.flushes + self.win_flushes,
            "pixels": self.pixels + self.win_pixels,
        }


def _fps_line(s):
    line = "fps %.1f avg %.1f frames %d present %.1f ms (max %.1f) busy %d%%" % (
        s["fps"],
        s["avg_fps"],
        s["frames"],
        s["present_ms"],
        s["present_ms_max"],
        round(s["busy"] * 100),
    )
    if s["flushes"]:
        line += " flushes %d" % s["flushes"]
    return line


class DisplayDriver:
    """
    Base class for all display backends (BusDisplay, SDLDisplay, PGDisplay, FBDisplay, etc.).

    Subclasses implement drawing (``blit_rect``, ``fill_rect``, ``pixel``),
    presentation (``show()``), and teardown (``quit()`` / ``deinit()``). Most
    applications use a concrete driver from ``board_config.display`` rather than
    instantiating this class directly.

    Periodic presentation when needed is driven by ``appdev.App`` (see
    ``needs_refresh``).

    ``share_framebuffer``: when True, a GUI may bind the panel scanout
    buffer(s) from :meth:`framebuffers` for direct rendering (e.g. LVGL
    ``DISPLAY_RENDER_MODE.DIRECT``). Default False — desktop/bus drivers keep
    their own draw buffers.

    Frame rate: :meth:`measure_fps` (or ``PYDEVICES_FPS=1``) counts frames and
    times presents; :meth:`fps` reads them. Off by default, and nothing is
    wrapped or timed while it is off.
    """

    needs_refresh = False
    # The frame-rate meter while measuring (measure_fps); None means off.
    _fps = None
    _fps_timer = None
    # The display's own frame period: what ``appdev.App`` presents at and what a
    # GUI's refresh timer is set to. A backend that can measure its host's
    # refresh (vsync, requestAnimationFrame) sets it; 33 ms otherwise.
    # ``PYDEVICES_REFRESH_MS`` overrides it per instance when the driver starts.
    refresh_period_ms = 33
    share_framebuffer = False
    # HostEventsDevice reads this ``(key, mod)`` tuple; None disables keyboard quit.
    quit_chord = None

    @property
    def frame_clock(self):
        """This display's :class:`FrameClock`: "call me once per frame".

        Created on first use. Backends with a real frame signal override
        ``_make_frame_clock``; the default is a ``multimer`` timer at
        :attr:`refresh_period_ms`.
        """
        fc = getattr(self, "_frame_clock", None)
        if fc is None:
            fc = self._make_frame_clock()
            self._frame_clock = fc
        return fc

    def _make_frame_clock(self):
        return FrameClock(self.refresh_period_ms, name="frame:%s" % (self.__class__.__name__,))

    def framebuffers(self):
        """Return panel buffers for direct GUI paint, or ``None``.

        When sharing is supported, returns
        ``(buf1, buf2_or_None, nbytes, stride_bytes)``.
        """
        return None

    def __init__(self, *, quiet=False):
        """Initialize shared display state and call subclass :meth:`init`.

        Args:
            quiet: When True, suppress init / rotation chatter.
        """
        self._quiet = quiet
        if not self._quiet:
            print(f"Initializing {self.__class__.__name__}...")
        gc.collect()

        self.byteswap = byteswap
        # Subclasses (e.g. PGDisplay) may set touch_scale before super().__init__
        # to match window scaling; do not clobber a preconfigured value.
        if getattr(self, "touch_scale", None) is None:
            self.touch_scale = 1.0
        self._vssa = False  # False means no vertical scroll
        self._auto_byteswap = self.requires_byteswap
        self._touch_device = None
        self.init()
        gc.collect()
        self._deinitialized = False
        self._apply_refresh_override()
        if not self._quiet:
            print(f"{self.__class__.__name__}: initialized.")
            if self.requires_byteswap:
                print(
                    f"{self.__class__.__name__}: requires_byteswap = True"
                    f" (byteswap={_BYTESWAP_BACKEND})"
                )
                if _BYTESWAP_BACKEND == "pure_python":
                    print(
                        f"{self.__class__.__name__}: warning: slow byteswap fallback; "
                        "install utils/byteswap (GitHub MIP) for viper/numpy swap"
                    )
        every = env_float("PYDEVICES_FPS_PRINT", 0)
        if every > 0:
            self.fps_print(every)
        elif env_bool("PYDEVICES_FPS"):
            self.measure_fps(True)

    def _apply_refresh_override(self):
        """``PYDEVICES_REFRESH_MS=N`` replaces this display's frame period.

        Read once, when the driver starts, after the backend's own ``init()``
        has had its say, so it wins over a backend's default (33 ms, or the
        browser's 16). ``appdev.App``'s refresh timer, the frame clock and
        ``display_driver``'s LVGL refresh timer all read
        :attr:`refresh_period_ms`, so LVGL and non-LVGL apps both follow it.
        Unset, empty, zero or not a number leaves the backend's period alone.
        """
        period = env_int("PYDEVICES_REFRESH_MS", 0)
        if period <= 0:
            return
        self.refresh_period_ms = period
        fc = getattr(self, "_frame_clock", None)
        if fc is not None:
            fc.period_ms = period

    def __del__(self):
        self.deinit()

    ############### Universal API Methods, not usually overridden ################

    @property
    def width(self) -> int:
        """The width of the display in pixels."""
        if ((self._rotation // 90) & 0x1) == 0x1:  # if rotation index is odd
            return self._height
        return self._width

    @property
    def height(self) -> int:
        """The height of the display in pixels."""
        if ((self._rotation // 90) & 0x1) == 0x1:  # if rotation index is odd
            return self._width
        return self._height

    @property
    def rotation(self) -> int:
        """
        The rotation of the display.
        """
        return self._rotation

    @rotation.setter
    def rotation(self, value) -> None:
        """
        Sets the rotation of the display.

        Args:
            value (int): The rotation of the display in degrees.
        """

        if value % 90 != 0:
            value = value * 90

        if value == self._rotation:
            return

        if not self._quiet:
            print(f"{self.__class__.__name__}.rotation():  Setting rotation to {value}")
        self._rotation_helper(value)
        if not self._quiet:
            print("done setting rotation")

        self._rotation = value

        if self._touch_device is not None:
            self._touch_device.rotation = value

        self.init()

    @property
    def touch_device(self) -> object:
        """
        The touch device.
        """
        return self._touch_device

    @touch_device.setter
    def touch_device(self, value) -> None:
        """
        Sets the touch device.

        Args:
            value (object): The touch device.
        """
        if hasattr(value, "rotation") or value is None:
            self._touch_device = value
        else:
            raise ValueError("touch_device must have a rotation attribute")
        self._touch_device.rotation = self.rotation

    def fill(self, color):
        """
        Fill the display with a color.

        Args:
            color (int): The color to fill the display with.
        """
        return self.fill_rect(0, 0, self.width, self.height, color)

    def scroll(self, dx, dy) -> None:
        """
        Scroll the display.

        Args:
            dx (int): The number of pixels to scroll horizontally.
            dy (int): The number of pixels to scroll vertically.
        """
        if dy != 0:
            if self._vssa is not None:
                self.vscsad(self._vssa + dy)
            else:
                self.vscsad(dy)
        if dx != 0:
            raise NotImplementedError("Horizontal scrolling not supported")

    def disable_auto_byteswap(self, value: bool) -> bool:
        """
        Disable byte swapping in the display driver.

        If self.requires_byteswap and the guest application is capable of byte swapping color data
        check to see if byte swapping can be disabled.  If so, disable it.

        Usage:
            ```
            # If byte swapping is required and the display driver is capable of having byte swapping disabled,
            # disable it and set a flag so we can swap the color bytes as they are created.
            if display_drv.requires_byteswap:
                needs_swap = display_drv.disable_auto_byteswap(True)
            else:
                needs_swap = False
            ```

        Args:
            value (bool): Whether to disable byte swapping.

        Returns:
            (bool): Whether byte swapping was disabled successfully.

        """
        if self._requires_byteswap:
            self._auto_byteswap = not value
        else:
            self._auto_byteswap = False
        if not self._quiet:
            print(f"{self.__class__.__name__}:  auto byte swapping = {self._auto_byteswap}")
        return not self._auto_byteswap

    @property
    def requires_byteswap(self) -> bool:
        """
        Whether the display requires byte swapping.
        """
        return self._requires_byteswap

    def blit_transparent(self, buf: memoryview, x: int, y: int, w: int, h: int, key: int):
        """
        Blit a buffer with transparency.

        Args:
            buf (memoryview): The buffer to blit.
            x (int): The x coordinate to blit to.
            y (int): The y coordinate to blit to.
            w (int): The width to blit.
            h (int): The height to blit.
            key (int): The color key to use for transparency.

        Returns:
            (tuple): The x, y, w, h coordinates of the blitted area.
        """
        bpp = self.color_depth // 8
        if bpp == 2:
            _blit_transparent_rgb565(self.blit_rect, buf, x, y, w, h, key)
        else:
            _blit_transparent_generic(self.blit_rect, buf, x, y, w, h, bpp, key)
        return (x, y, w, h)

    @property
    def vscroll(self) -> int:
        """
        The vertical scroll position relative to the top fixed area.

        Returns:
            (int): The vertical scroll position.
        """
        return self.vscsad() - self._tfa

    @vscroll.setter
    def vscroll(self, y) -> None:
        """
        Set the vertical scroll position relative to the top fixed area.

        Args:
            y (int): The vertical scroll position.
        """
        self.vscsad((y % self._vsa) + self._tfa)

    def set_vscroll(self, tfa=0, bfa=0) -> None:
        """
        Set the vertical scroll definition and move the vertical scroll to the top.

        Args:
            tfa (int): The top fixed area.
            bfa (int): The bottom fixed area.
        """
        self.vscrdef(tfa, self.height - tfa - bfa, bfa)
        self.vscroll = 0

    @property
    def tfa(self) -> int:
        """
        The top fixed area set by set_vscroll or vscrdef.

        Returns:
            (int): The top fixed area.
        """
        return self._tfa

    @property
    def vsa(self) -> int:
        """
        The vertical scroll area set by set_vscroll or vscrdef.

        Returns:
            (int): The vertical scroll area.
        """
        return self._vsa

    @property
    def bfa(self) -> int:
        """
        The bottom fixed area set by set_vscroll or vscrdef.

        Returns:
            (int): The bottom fixed area.
        """
        return self._bfa

    def translate_point(self, point) -> tuple:
        """
        Translate a point from real coordinates to scrolled coordinates.

        Useful for touch events.

        Args:
            point (tuple): The x and y coordinates to translate.

        Returns:
            (tuple): The translated x and y coordinates.
        """
        x, y = point
        if self.vscsad() and self.tfa < y < self.height - self.bfa:
            y = y + self.vscsad() - self.tfa
            if y >= (self.vsa + self.tfa):
                y %= self.vsa
        return x, y

    def scroll_by(self, value):
        """Scroll vertically by ``value`` pixels relative to the current offset.

        Args:
            value: Signed pixel delta applied to :attr:`vscroll`.
        """
        self.vscroll += value

    def scroll_to(self, value):
        """Set the absolute vertical scroll offset.

        Args:
            value: New :attr:`vscroll` position.
        """
        self.vscroll = value

    @property
    def tfa_area(self):
        """
        Top fixed area for vertical scrolling.

        Returns:
            tuple[int, int, int, int]: ``(x, y, width, height)`` of the top fixed band.
        """
        return (0, 0, self.width, self.tfa)

    @property
    def vsa_area(self):
        """
        The vertical scroll area as an Area object.

        Returns:
            (tuple): The vertical scroll area.
        """
        return (0, self.tfa, self.width, self.vsa)

    @property
    def bfa_area(self):
        """
        The bottom fixed area as an Area object.

        Returns:
            (tuple): The bottom fixed area.
        """
        return (0, self.tfa + self.vsa, self.width, self.bfa)

    ############### Frame rate ################

    def measure_fps(self, on=True):
        """Count frames and time presents (``on=True``), or stop (``on=False``).

        Switched on, the instance's ``show`` and ``flush_rect`` are wrapped
        with timers; switched off they are the class's own methods again. A
        frame is one ``show()``, or one :meth:`frame_done` from a GUI that
        presents with ``flush_rect`` (LVGL on a direct-framebuffer panel).
        ``flush_rect`` calls are counted as ``flushes`` and ``pixels``, not
        frames. ``PYDEVICES_FPS=1`` switches it on when the driver starts.

        Returns:
            bool: Whether it is measuring now.
        """
        if on:
            if self._fps is None:
                now, diff = _fps_clock()
                self._fps = _FpsMeter(now, diff)
                self._fps_wrapped = []
                self._fps_wrap("show")
                self._fps_wrap("flush_rect")
        elif self._fps is not None:
            self.fps_print(0)
            for name, wrapper, prev in self._fps_wrapped:
                if getattr(self, name, None) is not wrapper:
                    continue  # someone wrapped ours since: leave theirs alone
                if prev is None:
                    delattr(self, name)
                else:
                    setattr(self, name, prev)
            self._fps_wrapped = []
            self._fps = None
        return self._fps is not None

    def _fps_wrap(self, name):
        orig = getattr(self, name, None)
        if orig is None:
            return
        try:
            own = name in self.__dict__
        except AttributeError:
            own = False
        meter = self._fps
        now = meter.now
        diff = meter.diff
        if name == "flush_rect":

            def wrapper(x, y, w, h, *args, **kwargs):
                t = now()
                try:
                    return orig(x, y, w, h, *args, **kwargs)
                finally:
                    t1 = now()
                    meter.flush(t1, diff(t1, t), w * h)

        else:

            def wrapper(*args, **kwargs):
                t = now()
                try:
                    return orig(*args, **kwargs)
                finally:
                    t1 = now()
                    meter.frame(t1, diff(t1, t))

        self._fps_wrapped.append((name, wrapper, orig if own else None))
        setattr(self, name, wrapper)

    def frame_done(self):
        """A GUI that presents with ``flush_rect`` says a frame's last area is done.

        ``display_driver`` calls this on a direct-framebuffer panel when the
        last area was presented by ``flush_rect`` and no ``show()`` followed.
        Does nothing unless :meth:`measure_fps` is on.
        """
        meter = self._fps
        if meter is not None:
            meter.frame(meter.now(), 0)

    def fps(self):
        """The frame rate and present times, or ``None`` when not measuring.

        Returns a dict: ``fps`` (the last whole second), ``avg_fps`` (since
        :meth:`measure_fps` or :meth:`fps_reset`), ``frames``, ``seconds``,
        ``present_ms`` / ``present_ms_max`` (mean and worst time presenting a
        frame, its ``flush_rect`` calls included), ``busy`` (the share of
        wall time spent presenting: high means the display is the
        bottleneck, low means the app is), ``flushes`` and ``pixels``.
        """
        meter = self._fps
        return None if meter is None else meter.snapshot()

    def fps_reset(self):
        """Start a fresh measurement (does nothing when not measuring)."""
        if self._fps is not None:
            self._fps.reset()

    def fps_print(self, seconds=5):
        """Print a one-line summary every ``seconds``; ``0`` stops it.

        Switches :meth:`measure_fps` on. The line is short, for agents
        tailing a log::

            fps 29.8 avg 29.5 frames 1180 present 4.2 ms (max 12.0) busy 13%

        ``PYDEVICES_FPS_PRINT=N`` starts it when the driver starts.
        """
        timer = self._fps_timer
        self._fps_timer = None
        if timer is not None:
            timer.deinit()
        if not seconds or seconds <= 0:
            return
        self.measure_fps(True)
        import multimer

        def _print(_timer=None):
            meter = self._fps
            if meter is not None:
                print(_fps_line(meter.snapshot()))

        self._fps_timer = multimer.every(
            max(1, int(seconds * 1000)), _print, name="fps:%s" % (self.__class__.__name__,)
        )

    ############### Common API Methods, sometimes overridden ################

    def vscrdef(self, tfa: int, vsa: int, bfa: int) -> None:
        """
        Set the vertical scroll definition.  Should be overridden by the
        subclass and called as super().vscrdef(tfa, vsa, bfa).

        Args:
            tfa (int): The top fixed area.
            vsa (int): The vertical scroll area.
            bfa (int): The bottom fixed area.
        """
        if tfa + vsa + bfa != self.height:
            raise ValueError("Sum of top, scroll and bottom areas must equal screen height")
        self._tfa = tfa
        self._vsa = vsa
        self._bfa = bfa

    def vscsad(self, vssa: int | None = None) -> int:
        """
        Set or get the vertical scroll start address.  Should be overridden by the
        subclass and called as super().vscsad(y).

        Args:
            vssa (int): The vertical scroll start address.

        Returns:
            (int): The vertical scroll start address.
        """
        if vssa is not None:
            while vssa < 0:
                vssa += self._height
            if vssa >= self._height:
                vssa %= self._height
            self._vssa = vssa
        return vssa

    def _rotation_helper(self, value):
        """
        Helper function to set the rotation of the display.

        Args:
            value (int): The rotation of the display in degrees.
        """
        # override this method in subclasses to handle rotation

    ############### Empty API Methods, must be overridden if applicable ################

    @property
    def power(self) -> bool:
        """The power state of the display."""
        return -1

    @power.setter
    def power(self, value: bool) -> None:
        """
        Set the power state of the display.  Should be overridden by the subclass.

        Args:
            value (bool): True to power on, False to power off.
        """
        return

    @property
    def brightness(self) -> float:
        """The brightness of the display."""
        return -1

    @brightness.setter
    def brightness(self, value: float) -> None:
        """
        Set the brightness of the display.  Should be overridden by the subclass.

        Args:
            value (int, float): The brightness value from 0 to 1.
        """
        return

    def invert_colors(self, value: bool) -> None:
        """
        Invert the colors of the display.  Should be overridden by the subclass.

        Args:
            value (bool): True to invert the colors, False to restore the colors.
        """
        return

    def reset(self) -> None:
        """
        Perform a reset of the display.  Should be overridden by the subclass.
        """
        return

    def hard_reset(self) -> None:
        """
        Perform a hardware reset of the display.  Should be overridden by the subclass.
        """
        return

    def soft_reset(self) -> None:
        """
        Perform a software reset of the display.  Should be overridden by the subclass.
        """
        return

    def sleep_mode(self, value: bool) -> None:
        """
        Set the sleep mode of the display.  Should be overridden by the subclass.

        Args:
            value (bool): True to enter sleep mode, False to exit sleep mode.
        """
        return

    def deinit(self) -> None:
        """
        Run subclass cleanup. Idempotent.

        The broker owns the shared refresh timer, so there is no display-owned
        timer to stop here; ``board_config`` stops the timer on quit via
        ``app.stop_timer``.
        """
        if getattr(self, "_deinitialized", False):
            return
        self._deinitialized = True
        if self._fps_timer is not None:
            self.fps_print(0)  # the counts stay readable after quit
        self._deinit()

    def _deinit(self) -> None:
        """Subclass resource cleanup hook, called after the timer is stopped."""
        return

    def quit(self, code: int = 0, force: bool = False) -> None:
        """Release display resources (REPL-safe unless ``force=True``). Called on QUIT."""
        self.deinit()
        if force:
            raise SystemExit(code)

    def force_quit(self, code: int = 0) -> None:
        """Release resources then exit the process (alias for ``quit(code, force=True)``)."""
        self.quit(code, force=True)

    def show(self, *args, **kwargs) -> None:
        """
        Show the display.  Base class method does nothing.  May be overridden by subclasses.
        """
        return
