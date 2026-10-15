# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
displaydev.workerdisplay

A display for Python running in a Web Worker: it draws on an
``OffscreenCanvas`` the page transferred to the worker, and takes its input
from events the page relays.

Running the app in a worker leaves the page's main thread free, so a long
redraw never holds up anything the page has to do on time (Web MIDI, audio
hand-offs, input). The page side is a few lines of JavaScript:

.. code-block:: javascript

    const off = canvas.transferControlToOffscreen();
    worker.postMessage({type: "canvas", canvas: off}, [off]);
    // then, for every pointer, wheel and key event on the canvas:
    worker.postMessage({type: "input", event: {
        type: e.type,                      // pointerdown, pointerup, pointercancel,
                                           // pointermove, wheel, keydown, keyup
        x: e.offsetX, y: e.offsetY,        // CSS pixels inside the canvas
        movementX: e.movementX, movementY: e.movementY,
        button: e.button, buttons: e.buttons,
        pointerType: e.pointerType, pointerId: e.pointerId,
        deltaX: e.deltaX, deltaY: e.deltaY,
        key: e.key, location: e.location, repeat: e.repeat,
        ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
    }});
    // and whenever the canvas's CSS size changes:
    worker.postMessage({type: "resize", width: rect.width, height: rect.height});

In the worker, hand each ``input`` event to :func:`feed` and each
``resize`` to :meth:`WorkerDisplay.set_css_size`. The events come out of
``display_drv.get_events`` exactly as :class:`PSDisplay` produces them, so
``appdev`` and LVGL's ``display_driver`` work unchanged. The page should
call ``preventDefault()`` itself on ``wheel``, ``contextmenu`` and the keys
that scroll a page; a worker can't.

Gamepads aren't available in a worker.
"""

from displaydev._webcanvas import CanvasDisplay
from displaydev._webinput import WebInput
import keys

_current = None


class WorkerDevices(WebInput):
    """Input for a :class:`WorkerDisplay`, fed by events the page relays."""

    _HANDLERS = {
        "pointerdown": "_on_pointer_down",
        "pointerup": "_on_pointer_up",
        "pointercancel": "_on_pointer_up",
        "pointermove": "_on_pointer_move",
        "wheel": "_on_wheel",
        "keydown": "_on_keydown",
        "keyup": "_on_keyup",
    }

    def feed(self, event):
        """Queue one relayed browser event (a JS object or a ``dict``)."""
        if isinstance(event, dict):
            event = _Event(event)
        name = self._HANDLERS.get(str(event.type))
        if name:
            getattr(self, name)(event)

    def _local_xy(self, e):
        return float(e.x), float(e.y)

    def _poll_gamepads(self):
        pass


class _Event:
    """Attribute access over a plain ``dict`` (tests, or a converted JS object)."""

    def __init__(self, d):
        self.__dict__.update(d)

    def __getattr__(self, name):
        raise AttributeError(name)


class WorkerDisplay(CanvasDisplay):
    """Emulate a display on an ``OffscreenCanvas``, from a Web Worker.

    Args:
        canvas: The ``OffscreenCanvas`` the page transferred to this worker.
        width (int, optional): Panel width; defaults to the canvas width.
        height (int, optional): Panel height; defaults to the canvas height.
        quiet (bool): Suppress init chatter when True.
    """

    quit_chord = (keys.K_AC_BACK, 0)

    def __init__(self, canvas, width=None, height=None, *, quiet=False):
        global _current
        self._css_size = None
        super().__init__(canvas, width, height, quiet=quiet)
        self._devices = WorkerDevices(self)
        self.get_events = self._devices.read
        self.feed = self._devices.feed
        _current = self

    def _new_buffer(self, width, height):
        from js import OffscreenCanvas

        return OffscreenCanvas.new(width, height)

    def set_css_size(self, width, height):
        """Tell the display how big the page shows the canvas, in CSS pixels."""
        self._css_size = (float(width), float(height))

    def _pointer_scale(self):
        """Framebuffer pixels per CSS pixel (1.0 until the page says otherwise)."""
        if not self._css_size:
            return 1.0, 1.0
        cw, ch = self._css_size
        if cw <= 0 or ch <= 0:
            return 1.0, 1.0
        return float(self.width) / cw, float(self.height) / ch

    @property
    def touch_scale(self):
        """CSS pixels per framebuffer pixel, the same contract as ``PSDisplay``."""
        sx, _sy = self._pointer_scale()
        return 1.0 / sx if sx else 1.0

    @touch_scale.setter
    def touch_scale(self, value):
        # DisplayDriver.__init__ assigns a default; the page's layout decides.
        pass

    def map_pointer(self, local_x, local_y):
        """Map canvas-local CSS pixels to framebuffer ``(x, y)``."""
        sx, sy = self._pointer_scale()
        return (int(float(local_x) * sx), int(float(local_y) * sy))

    def map_pointer_rel(self, dx, dy):
        """Map a pointer delta in CSS pixels to framebuffer pixels."""
        sx, sy = self._pointer_scale()
        return (int(float(dx) * sx), int(float(dy) * sy))


def feed(event):
    """Hand a relayed ``input`` event to the most recent :class:`WorkerDisplay`."""
    if _current is not None:
        _current.feed(event)


def resize(width, height):
    """Hand a relayed ``resize`` to the most recent :class:`WorkerDisplay`."""
    if _current is not None:
        _current.set_css_size(width, height)
