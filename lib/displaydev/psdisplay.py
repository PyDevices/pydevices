# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
displaydev.psdisplay
"""

from js import console, document
try:
    from pyscript.ffi import create_proxy
except ImportError:
    try:
        from pyodide.ffi import create_proxy
    except ImportError:
        create_proxy = lambda x: x

from displaydev._webcanvas import CanvasDisplay
from displaydev._webinput import WebInput, _buttons_tuple  # noqa: F401  (re-exported)
import keys


def log(*args):
    console.log(*args)


class PSDevices(WebInput):
    """
    Unified input for a PyScript canvas, registered as an appdev HOST device.

    Captures all available browser input on a single HTML element and turns it
    into ``events`` objects (matching the desktop SDL2 / PyGame event
    stream), drained through :meth:`read`:

    - **Pointer** (mouse via Pointer Events): ``MOUSEMOTION`` /
      ``MOUSEBUTTONDOWN`` / ``MOUSEBUTTONUP``.
    - **Touch / pen** (Pointer Events with ``pointerType`` other than
      ``mouse``): ``FINGERDOWN`` / ``FINGERUP`` / ``FINGERMOTION`` with
      ``pointerId`` as ``finger_id``, so LVGL gesture recognizers see
      multipoint contacts (same contract as SDL/pygame fingers).
    - **Wheel**: ``MOUSEWHEEL`` (also consumed by encoder devices).
    - **Keyboard**: ``KEYDOWN`` / ``KEYUP`` with SDL-style key codes, names and
      modifier masks (left/right modifier variants via key location).
    - **Gamepad** (Gamepad API, polled on each :meth:`read`): ``JOYAXISMOTION``,
      ``JOYBUTTONDOWN`` / ``JOYBUTTONUP``.

    Quit chord handling is configured on :class:`PSDisplay` via ``quit_chord``
    (default ``(keys.K_AC_BACK, 0)`` for browser/TV Back).
    :class:`~appdev.HostEvents` applies the chord when constructed with
    ``display=``.

    Note:
        The element must be focused to receive key events.  The constructor sets
        ``tabindex`` and calls :meth:`_focus_canvas` so keyboard input goes to the
        game; pointer down on the canvas refocuses it.

    Args:
        id (str): The id of the element to watch (usually the canvas).
        display (PSDisplay, optional): Pass the same ``PSDisplay`` used as
            ``QueueDevice`` ``data`` (for ``touch_scale`` pointer mapping).
    """

    def __init__(self, id, display=None):
        super().__init__(display)
        self.canvas = document.getElementById(id)

        # Clean up any existing PSDevices listeners attached to this canvas
        old_devices = getattr(self.canvas, "_ps_devices", None)
        if old_devices is not None and hasattr(old_devices, "deinit"):
            try:
                old_devices.deinit()
            except Exception:
                pass
        self.canvas._ps_devices = self

        try:
            self.canvas.tabIndex = 0  # make the element focusable for key events
            self.canvas.style.touchAction = "none"  # don't scroll/zoom on touch
        except Exception:
            pass


        # Proxy functions are required for javascript
        self._proxies = {
            "pointerdown": create_proxy(self._on_pointer_down),
            "pointerup": create_proxy(self._on_pointer_up),
            "pointercancel": create_proxy(self._on_pointer_up),
            "pointermove": create_proxy(self._on_pointer_move),
            "wheel": create_proxy(self._on_wheel),
            "contextmenu": create_proxy(self._on_contextmenu),
            "keydown": create_proxy(self._on_keydown),
            "keyup": create_proxy(self._on_keyup),
        }
        for name, proxy in self._proxies.items():
            self.canvas.addEventListener(name, proxy)
        self._focus_canvas()

    def deinit(self):
        """Detach DOM event listeners and destroy Pyodide proxies."""
        if hasattr(self, "_proxies") and self._proxies:
            for name, proxy in self._proxies.items():
                try:
                    self.canvas.removeEventListener(name, proxy)
                    if hasattr(proxy, "destroy"):
                        proxy.destroy()
                except Exception:
                    pass
            self._proxies.clear()
        if hasattr(self, "_queue"):
            self._queue.clear()


class PSDisplay(CanvasDisplay):
    """Emulate a display on a PyScript HTML canvas.

    Args:
        id (str): DOM id of the canvas element.
        width (int, optional): Panel width; defaults to the canvas width.
        height (int, optional): Panel height; defaults to the canvas height.
        quiet (bool): Suppress init chatter when True.

    Attributes:
        needs_refresh (bool): True — ``appdev.App`` drives periodic ``show()``.
    """

    quit_chord = (keys.K_AC_BACK, 0)

    def __init__(self, id, width=None, height=None, *, quiet=False):
        self._canvas_id = id
        super().__init__(document.getElementById(id), width, height, quiet=quiet)
        # Per-canvas input; drain is the appdev.App host_read callable.
        self._ps_devices = PSDevices(id, self)
        self.get_events = self._ps_devices.read

    def _new_buffer(self, width, height):
        return document.createElement("canvas")

    @property
    def touch_scale(self):
        """CSS layout pixels per framebuffer pixel, read live.

        ``HostEventsDevice`` divides mouse coordinates by this, the same
        contract as ``SDLDisplay``'s window scale. It is the inverse of
        :meth:`_pointer_scale`, and it is read at each event because the page
        can resize the canvas (a ``max-width`` rule, a window resize) after
        :meth:`init` has run.
        """
        sx, _sy = self._pointer_scale()
        return 1.0 / sx if sx else 1.0

    @touch_scale.setter
    def touch_scale(self, value):
        # DisplayDriver.__init__ assigns a default; the layout decides here.
        pass

    def _pointer_scale(self):
        """Framebuffer pixels per CSS layout pixel (1.0 when layout is 1:1)."""
        canvas = getattr(self, "_canvas", None)
        if canvas is None:
            return 1.0, 1.0
        rect = canvas.getBoundingClientRect()
        rw, rh = float(rect.width), float(rect.height)
        if rw <= 0 or rh <= 0:
            return 1.0, 1.0
        return float(self._canvas.width) / rw, float(self._canvas.height) / rh

    def map_pointer(self, local_x, local_y):
        """
        Map element-local pointer coordinates to framebuffer ``(x, y)``.

        ``PSDevices`` maps touch/pen to panel pixels at capture (``FINGER*``);
        mouse coords stay CSS-local and ``HostEventsDevice`` applies
        ``touch_scale``.
        """
        sx, sy = self._pointer_scale()
        return (int(float(local_x) * sx), int(float(local_y) * sy))

    def map_pointer_rel(self, dx, dy):
        """Map a DOM pointer delta (``movementX``/``movementY``) to framebuffer pixels."""
        sx, sy = self._pointer_scale()
        return (int(float(dx) * sx), int(float(dy) * sy))
