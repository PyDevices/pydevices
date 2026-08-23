"""Direct MicroPython WebAssembly RGB565 display and browser input backend."""

import json

import _wasm_bridge
import events
import keys

from displaydev._desktop import DesktopDisplay
from displaydev._domkeys import enrich_mod, key_to_keycode, mod_mask
from displaydev.fbdisplay import FBDisplay

_POINTER_EVENT_TYPES = (events.Motion, events.Button, events.Finger)


def _buttons_tuple(buttons):
    return (1 if buttons & 1 else 0, 1 if buttons & 4 else 0, 1 if buttons & 2 else 0)


class WasmDevices:
    """Translate neutral bridge records into the project-wide ``events`` contract."""

    def __init__(self):
        self._pressed = set()
        self._pointer_pos = {}
        self._gamepad_axes = {}
        self._gamepad_buttons = {}

    def read(self):
        result = []
        batch, raw_count = _wasm_bridge.poll_events(_POINTER_EVENT_TYPES)
        if batch is None:
            return None
        if not raw_count:
            return batch
        for raw in batch:
            if isinstance(raw, str):
                event = self._convert(json.loads(raw))
            elif isinstance(raw, list) or raw[0] > 9:
                event = raw
            else:
                event = self._convert_fast(raw)
            if event is None:
                continue
            if isinstance(event, list):
                result.extend(event)
            else:
                result.append(event)
        return result or None

    def _convert_fast(self, item):
        kind = item[0]
        pos = (item[1], item[2]) if kind <= 5 else (0, 0)
        if kind in (1, 3):
            pointer_id = item[7]
            touch = item[8] != 0
            out = []
            down = kind == 1
            if touch:
                out.append(
                    events.Finger(
                        events.FINGERDOWN if down else events.FINGERUP,
                        pos,
                        pointer_id,
                        None,
                    )
                )
            out.append(
                events.Button(
                    events.MOUSEBUTTONDOWN if down else events.MOUSEBUTTONUP,
                    pos,
                    item[5] + 1,
                    touch,
                    None,
                )
            )
            self._pointer_pos[pointer_id] = pos
            return out
        if kind == 2:
            pointer_id = item[7]
            touch = item[8] != 0
            old = self._pointer_pos.get(pointer_id, pos)
            self._pointer_pos[pointer_id] = pos
            if touch:
                return events.Finger(events.FINGERMOTION, pos, pointer_id, None)
            rel = (item[3] or pos[0] - old[0], item[4] or pos[1] - old[1])
            return events.Motion(
                events.MOUSEMOTION, pos, rel, _buttons_tuple(item[6]), False, None
            )
        if kind == 5:
            dx, dy = item[3] / 1000, item[4] / 1000
            return events.Wheel(
                events.MOUSEWHEEL, False, -int(dx), -int(dy), -dx, -dy, False, None
            )
        if kind in (6, 7):
            name, location, flags = item[1], item[3], item[4]
            code = key_to_keycode(name, location)
            if kind == 6:
                self._pressed.add(code)
            else:
                self._pressed.discard(code)
            modifiers = mod_mask(flags & 2, flags & 8, flags & 1, flags & 4)
            return events.Key(
                events.KEYDOWN if kind == 6 else events.KEYUP,
                name,
                code,
                enrich_mod(modifiers, self._pressed),
                item[2],
                None,
            )
        return None

    def clear(self):
        _wasm_bridge.clear_events()
        self._pressed.clear()
        self._pointer_pos.clear()

    def _convert(self, item):
        kind = item.get("type")
        pos = (int(item.get("x", 0)), int(item.get("y", 0)))
        pointer_id = int(item.get("pointerId", 0))
        touch = item.get("pointerType", "mouse") != "mouse"
        if kind in ("pointerdown", "pointerup"):
            out = []
            if touch:
                out.append(
                    events.Finger(
                        events.FINGERDOWN if kind == "pointerdown" else events.FINGERUP,
                        pos,
                        pointer_id,
                        None,
                    )
                )
            out.append(
                events.Button(
                    events.MOUSEBUTTONDOWN
                    if kind == "pointerdown"
                    else events.MOUSEBUTTONUP,
                    pos,
                    int(item.get("button", 0)) + 1,
                    touch,
                    None,
                )
            )
            self._pointer_pos[pointer_id] = pos
            return out
        if kind == "pointermove":
            old = self._pointer_pos.get(pointer_id, pos)
            self._pointer_pos[pointer_id] = pos
            if touch:
                return events.Finger(events.FINGERMOTION, pos, pointer_id, None)
            rel = (
                int(item.get("movementX", pos[0] - old[0])),
                int(item.get("movementY", pos[1] - old[1])),
            )
            return events.Motion(
                events.MOUSEMOTION,
                pos,
                rel,
                _buttons_tuple(int(item.get("buttons", 0))),
                False,
                None,
            )
        if kind == "wheel":
            return events.Wheel(
                events.MOUSEWHEEL,
                False,
                -int(item.get("deltaX", 0)),
                -int(item.get("deltaY", 0)),
                -float(item.get("deltaX", 0)),
                -float(item.get("deltaY", 0)),
                False,
                None,
            )
        if kind in ("keydown", "keyup"):
            name = str(item.get("key", ""))
            code = key_to_keycode(name, int(item.get("location", 0)))
            if kind == "keydown":
                self._pressed.add(code)
            else:
                self._pressed.discard(code)
            modifiers = mod_mask(
                item.get("ctrlKey", False),
                item.get("shiftKey", False),
                item.get("altKey", False),
                item.get("metaKey", False),
            )
            modifiers = enrich_mod(modifiers, self._pressed)
            return events.Key(
                events.KEYDOWN if kind == "keydown" else events.KEYUP,
                name,
                code,
                modifiers,
                item.get("code"),
                None,
            )
        if kind == "gamepad":
            return self._gamepad(item)
        return None

    def _gamepad(self, item):
        index = int(item.get("index", 0))
        output = []
        axes = item.get("axes", ())
        old_axes = self._gamepad_axes.get(index, ())
        for axis, value in enumerate(axes):
            normalized = int(max(-1.0, min(1.0, float(value))) * 32767)
            old = old_axes[axis] if axis < len(old_axes) else 0
            if abs(normalized - old) >= 256:
                output.append(
                    events.JoyAxisMotion(events.JOYAXISMOTION, index, axis, normalized)
                )
        self._gamepad_axes[index] = [
            int(max(-1.0, min(1.0, float(v))) * 32767) for v in axes
        ]
        buttons = [
            bool(button.get("pressed", False)) for button in item.get("buttons", ())
        ]
        old_buttons = self._gamepad_buttons.get(index, ())
        for number, pressed in enumerate(buttons):
            old = old_buttons[number] if number < len(old_buttons) else False
            if pressed != old:
                cls = events.JoyButtonDown if pressed else events.JoyButtonUp
                event_type = events.JOYBUTTONDOWN if pressed else events.JOYBUTTONUP
                output.append(cls(event_type, index, number))
        self._gamepad_buttons[index] = buttons
        return output


class WasmDisplay(DesktopDisplay, FBDisplay):
    """A Python-owned RGB565 back buffer composited to a browser-scanned front buffer.

    Apps draw into ``_framebuffer`` (the logical, unscrolled surface) through
    the inherited :class:`FBDisplay` primitives. ``_displayed`` is the buffer
    actually registered with the browser and scanned every animation frame;
    :meth:`_composite` copies from the former to the latter, applying the
    vertical-scroll row shift the same way :class:`PSDisplay` does with
    ``drawImage`` — a plain byte-slice copy here since both buffers are RGB565.

    Attributes:
        needs_refresh (bool): True — ``appdev.App`` drives periodic ``show()``,
            so draws that never call ``show()`` explicitly (e.g. a scroll
            timer) still reach the composited front buffer.
        requires_async_timer (bool): True — single-threaded cooperative browser
            WASM, like :class:`PSDisplay`/:class:`JNDisplay`: without the
            async-driven host loop, ``app.every()`` timers (and the
            ``needs_refresh`` timer above) never fire.
    """

    needs_refresh = True
    requires_async_timer = True
    quit_chord = (keys.K_AC_BACK, 0)

    def __init__(
        self, width=320, height=240, canvas_id="display_canvas", *, quiet=False
    ):
        self._canvas_id = canvas_id
        self._framebuffer = bytearray(int(width) * int(height) * 2)
        self._displayed = bytearray(int(width) * int(height) * 2)
        self._devices = WasmDevices()
        super().__init__(self._framebuffer, int(width), int(height), quiet=quiet)
        self.get_events = self._devices.read

    def init(self):
        # Straight to DisplayDriver, matching PSDisplay/SDLDisplay/PGDisplay:
        # a full-height scroll region so vscsad() works before any explicit
        # set_vscroll/vscrdef, without firing _scroll_changed mid-init.
        self._reset_vscroll()
        if not _wasm_bridge.register_framebuffer(
            self._displayed, self.width, self.height, self._canvas_id
        ):
            raise RuntimeError(f"WASM canvas {self._canvas_id!r} was not found")
        self._composite()

    def _scroll_changed(self):
        """Repaint immediately; this backend has no deferred-render tick."""
        self._composite()

    def show(self, _timer=None):
        self._composite()

    def _composite(self):
        """Copy the back buffer to the front buffer, applying vscroll."""
        row_bytes = self.width * 2
        src = self._framebuffer
        dst = self._displayed
        y_start = self.vscsad()
        if not y_start:
            dst[:] = src
            return
        tfa, vsa, bfa = self._tfa, self._vsa, self._bfa
        if tfa:
            n = tfa * row_bytes
            dst[0:n] = src[0:n]
        top_h = vsa + tfa - y_start
        a, b = y_start * row_bytes, (y_start + top_h) * row_bytes
        da, db = tfa * row_bytes, (tfa + top_h) * row_bytes
        dst[da:db] = src[a:b]
        btm_h = vsa - top_h
        if btm_h:
            a2, b2 = tfa * row_bytes, (tfa + btm_h) * row_bytes
            dst[db : db + (b2 - a2)] = src[a2:b2]
        if bfa:
            n = bfa * row_bytes
            dst[len(dst) - n :] = src[len(src) - n :]

    def _deinit(self):
        self._devices.clear()
        _wasm_bridge.unregister_framebuffer()
