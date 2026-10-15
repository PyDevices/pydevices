# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
displaydev._webinput

Browser input turned into ``events`` objects, shared by the PyScript canvas
(:mod:`displaydev.psdisplay`, which listens on the DOM itself) and the Web
Worker display (:mod:`displaydev.workerdisplay`, which is handed the same
events by the page). Nothing here touches ``document``, so it imports in a
worker too.
"""

import events
import keys
from displaydev._domkeys import (
    dom_key_scrolls_page,
    enrich_mod,
    key_to_keycode,
    mod_mask,
)

try:  # Gamepads are a page API; a worker has no getGamepads().
    from js import navigator
except ImportError:
    navigator = None


def _buttons_tuple(buttons):
    """Convert a DOM ``buttons`` bitmask to an (left, middle, right) tuple."""
    return (
        1 if buttons & 1 else 0,  # left
        1 if buttons & 4 else 0,  # middle
        1 if buttons & 2 else 0,  # right
    )


class WebInput:
    """Pointer, wheel, keyboard and gamepad input as an appdev HOST device.

    Subclasses decide where the browser events come from; the handlers below
    turn each one into ``events`` objects, drained through :meth:`read`.
    """

    canvas = None

    def __init__(self, display=None):
        self._display = display
        self._queue = []
        self._pressed = set()
        # Gamepad state keyed by gamepad index: (axes list, pressed-bool list).
        self._gp_axes = {}
        self._gp_buttons = {}

    def _focus_canvas(self):
        """Move keyboard focus to the canvas so keys reach the app, not the page."""
        try:
            self.canvas.focus()
        except Exception:
            pass

    def read(self):
        """
        Returns queued input events for an appdev device.

        Polls connected gamepads (if any) and returns all events received since
        the last call.

        Returns:
            list or None: The events, or None if there were none.
        """
        self._poll_gamepads()
        if not self._queue:
            return None
        queued = self._queue
        self._queue = []
        return queued

    ############### Pointer (mouse / touch / pen) ################

    def _is_touch(self, e):
        try:
            return e.pointerType != "mouse"
        except Exception:
            return False

    def _map_pos(self, x, y):
        try:
            return (int(x), int(y))
        except Exception:
            return (int(float(x)), int(float(y)))

    def _map_rel(self, dx, dy):
        try:
            return (int(dx), int(dy))
        except Exception:
            return (int(float(dx)), int(float(dy)))

    def _local_xy(self, e):
        """Element-local CSS pixels (prefer ``client*`` - rect for synthetics)."""
        try:
            rect = self.canvas.getBoundingClientRect()
            return float(e.clientX) - float(rect.left), float(e.clientY) - float(rect.top)
        except Exception:
            return float(e.offsetX), float(e.offsetY)

    def _pointer_pos(self, e):
        """Framebuffer pixels for host scaling / LVGL fingers."""
        x, y = self._local_xy(e)
        # Fingers must be panel-normalized (SDL contract); mouse stays CSS and
        # HostEventsDevice applies ``touch_scale``.
        if self._is_touch(e) and self._display is not None:
            try:
                return self._display.map_pointer(x, y)
            except Exception:
                pass
        return self._map_pos(x, y)

    def _finger_id(self, e):
        try:
            return int(e.pointerId)
        except Exception:
            return 0

    def _on_pointer_down(self, e):
        self._focus_canvas()
        try:
            self.canvas.setPointerCapture(e.pointerId)
        except Exception:
            pass
        pos = self._pointer_pos(e)
        if self._is_touch(e):
            # Multipoint path for LVGL gestures (VirtualDevices tracks fingers).
            self._queue.append(events.Finger(events.FINGERDOWN, pos, self._finger_id(e), None))
        self._queue.append(
            events.Button(
                events.MOUSEBUTTONDOWN,
                pos,
                getattr(e, "button", 0) + 1,  # DOM 0/1/2 -> SDL 1/2/3
                False,
                None,
            )
        )

    def _on_pointer_up(self, e):
        pos = self._pointer_pos(e)
        if self._is_touch(e):
            self._queue.append(events.Finger(events.FINGERUP, pos, self._finger_id(e), None))
        self._queue.append(
            events.Button(
                events.MOUSEBUTTONUP,
                pos,
                getattr(e, "button", 0) + 1,
                False,
                None,
            )
        )

    def _on_pointer_move(self, e):
        pos = self._pointer_pos(e)
        if self._is_touch(e):
            self._queue.append(events.Finger(events.FINGERMOTION, pos, self._finger_id(e), None))
            return
        self._queue.append(
            events.Motion(
                events.MOUSEMOTION,
                pos,
                self._map_rel(e.movementX, e.movementY),
                _buttons_tuple(e.buttons),
                False,
                None,
            )
        )

    def _on_wheel(self, e):
        try:
            e.preventDefault()
        except Exception:
            pass
        # DOM deltaY > 0 means scrolling down; SDL/PyGame report up as positive.
        x = -1 if e.deltaX < 0 else (1 if e.deltaX > 0 else 0)
        y = 1 if e.deltaY < 0 else (-1 if e.deltaY > 0 else 0)
        self._queue.append(
            events.Wheel(events.MOUSEWHEEL, False, x, y, e.deltaX, e.deltaY, False, None)
        )

    def _on_contextmenu(self, e):
        # Suppress the browser menu so right-click is usable as a button event.
        try:
            e.preventDefault()
        except Exception:
            pass

    ############### Keyboard ################

    def _enqueue_key(self, type, keycode, mod):
        self._queue.append(events.Key(type, keys.keyname(keycode), keycode, mod, 0, None))

    def _suppress_browser_scroll(self, e, keycode):
        if dom_key_scrolls_page(keycode):
            try:
                e.preventDefault()
            except Exception:
                pass

    def _on_keydown(self, e):
        keycode = key_to_keycode(e.key, e.location)
        self._suppress_browser_scroll(e, keycode)
        if e.repeat:  # ignore auto-repeat
            return
        self._pressed.add(keycode)
        mod = enrich_mod(mod_mask(e.ctrlKey, e.shiftKey, e.altKey, e.metaKey), self._pressed)
        self._enqueue_key(events.KEYDOWN, keycode, mod)

    def _on_keyup(self, e):
        keycode = key_to_keycode(e.key, e.location)
        self._suppress_browser_scroll(e, keycode)
        self._pressed.discard(keycode)
        mod = enrich_mod(mod_mask(e.ctrlKey, e.shiftKey, e.altKey, e.metaKey), self._pressed)
        self._enqueue_key(events.KEYUP, keycode, mod)

    ############### Gamepad ################

    def _poll_gamepads(self):
        if navigator is None:
            return
        try:
            pads = navigator.getGamepads()
        except Exception:
            return
        for i in range(pads.length):
            pad = pads[i]
            if not pad:
                continue
            gid = pad.index

            axes = pad.axes
            cur_axes = [float(axes[a]) for a in range(axes.length)]
            prev_axes = self._gp_axes.get(gid, [0.0] * len(cur_axes))
            for a in range(len(cur_axes)):
                prev = prev_axes[a] if a < len(prev_axes) else 0.0
                if cur_axes[a] != prev:
                    self._queue.append(
                        events.JoyAxisMotion(events.JOYAXISMOTION, gid, a, cur_axes[a])
                    )
            self._gp_axes[gid] = cur_axes

            btns = pad.buttons
            cur_btns = [bool(btns[b].pressed) for b in range(btns.length)]
            prev_btns = self._gp_buttons.get(gid, [False] * len(cur_btns))
            for b in range(len(cur_btns)):
                prev = prev_btns[b] if b < len(prev_btns) else False
                if cur_btns[b] != prev:
                    if cur_btns[b]:
                        self._queue.append(events.JoyButtonDown(events.JOYBUTTONDOWN, gid, b))
                    else:
                        self._queue.append(events.JoyButtonUp(events.JOYBUTTONUP, gid, b))
            self._gp_buttons[gid] = cur_btns
