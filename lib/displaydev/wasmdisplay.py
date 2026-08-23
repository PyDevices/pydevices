# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
displaydev.wasmdisplay
"""

import uctypes
import framebuf

try:
    import _wasm_bridge
except ImportError:
    _wasm_bridge = None

from displaydev._desktop import DesktopDisplay
import keys


class WasmDisplay(DesktopDisplay):
    """
    Pure WebAssembly backend display utilizing shared memory.

    Provides a pure Python ``bytearray`` framebuffer wrapped in a ``framebuf``
    for native drawing speeds, exporting its memory address to the JavaScript
    host via ``_wasm_bridge``.
    """

    needs_refresh = True
    requires_async_timer = True
    quit_chord = (keys.K_AC_BACK, 0)

    def __init__(self, width=640, height=480, *, quiet=False):
        self._width = width
        self._height = height
        self._rotation = 0
        self.color_depth = 16

        # Allocate the RGB565 framebuffer and wrap it for drawing
        self._buffer = bytearray(width * height * 2)
        self._fb = framebuf.FrameBuffer(self._buffer, width, height, framebuf.RGB565)

        if _wasm_bridge is not None:
            _wasm_bridge.register_display(
                width, 
                height, 
                uctypes.addressof(self._buffer)
            )
            # Appdev will poll this to get the events (must return a list or None)
            self.get_events = _wasm_bridge.get_events
        else:
            self.get_events = lambda: None

        super().__init__(quiet=quiet)

    ############### Required API Methods ################

    def init(self) -> None:
        pass

    def fill_rect(self, x, y, w, h, c):
        self._fb.fill_rect(x, y, w, h, c)
        self._render_dirty = True
        return (x, y, w, h)

    def blit_rect(self, buf, x, y, w, h):
        src_fb = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
        self._fb.blit(src_fb, x, y)
        self._render_dirty = True
        return (x, y, w, h)

    def pixel(self, x, y, c):
        self._fb.pixel(x, y, c)
        self._render_dirty = True
        return (x, y, 1, 1)

    ############### Scrolling & Present ################

    def render(self, render_rect=None) -> None:
        """Tell the JS host that the frame is ready for composition."""
        if _wasm_bridge is not None:
            # We pass the rect if we have partial updates, otherwise full refresh.
            if render_rect is not None:
                _wasm_bridge.render_display(*render_rect)
            else:
                _wasm_bridge.render_display(0, 0, self.width, self.height)

    def show(self, _timer=None) -> None:
        if self._render_dirty:
            self.render()
            self._render_dirty = False

    ############### Pointer Mapping ################

    def map_pointer(self, local_x, local_y):
        """
        Coordinates emitted from the JS side are already mapped to framebuffer
        pixels, so we can just return them 1:1.
        """
        return (int(local_x), int(local_y))

    def map_pointer_rel(self, dx, dy):
        return (int(dx), int(dy))
