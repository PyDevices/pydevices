# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
displaydev._webcanvas

The drawing half shared by the PyScript canvas (:class:`PSDisplay`) and the
Web Worker canvas (:class:`WorkerDisplay`): an offscreen buffer the size of
the panel, copied to the visible canvas with vertical scroll applied.

``blit_rect`` converts a whole RGB565 buffer to RGBA in one JavaScript call.
Going through the Python-to-JavaScript bridge once per pixel costs about two
seconds for a full 1280x720 frame; one call costs a few milliseconds.
"""

from displaydev import color_rgb
from displaydev._desktop import DesktopDisplay

_blit565 = None


def blit565(ctx, buf, x, y, w, h):
    """Put a little-endian RGB565 buffer on a 2D context at ``(x, y)``."""
    global _blit565
    from pyodide.ffi import to_js

    if _blit565 is None:
        from js import Function

        _blit565 = Function.new(
            "ctx", "src", "x", "y", "w", "h",
            """
            const img = ctx.createImageData(w, h);
            const out = new Uint32Array(img.data.buffer);
            for (let i = 0, j = 0, n = w * h; j < n; i += 2, j++) {
              const lo = src[i], hi = src[i + 1];
              const r = (hi & 0xF8) | ((hi >> 5) & 0x07);
              const g = ((hi << 5) & 0xE0) | ((lo >> 3) & 0x1F);
              const b = ((lo << 3) & 0xF8) | ((lo >> 2) & 0x07);
              out[j] = 0xFF000000 | (b << 16) | (g << 8) | r;
            }
            ctx.putImageData(img, x, y);
            """,
        )
    _blit565(ctx, to_js(memoryview(buf)), x, y, w, h)


class CanvasDisplay(DesktopDisplay):
    """A panel drawn on an HTML canvas or an OffscreenCanvas.

    Subclasses pass the visible canvas and provide :meth:`_new_buffer`, which
    makes the offscreen canvas everything is drawn to first.
    """

    needs_refresh = True

    def __init__(self, canvas, width=None, height=None, *, quiet=False):
        self._canvas = canvas
        self._vis_ctx = canvas.getContext("2d")
        self._buffer = None
        self._buf_ctx = None
        self._width = width or canvas.width
        self._height = height or canvas.height
        self._requires_byteswap = False
        self._rotation = 0
        self.color_depth = 16
        super().__init__(quiet=quiet)

    def _new_buffer(self, width, height):
        raise NotImplementedError

    ############### Required API Methods ################

    def init(self) -> None:
        """
        Initializes the display instance.  Called by __init__ and rotation setter.
        """
        self._canvas.width = self.width
        self._canvas.height = self.height
        if self._buffer is None:
            self._buffer = self._new_buffer(self.width, self.height)
            self._buf_ctx = self._buffer.getContext("2d")
        self._buffer.width = self.width
        self._buffer.height = self.height
        # Match PGDisplay / SDLDisplay / JNDisplay: default full-height scroll region
        # so vscsad() works before an explicit set_vscroll/vscrdef.
        self._reset_vscroll()

    def fill_rect(self, x, y, w, h, c):
        """
        Fills a rectangle with the given color.

        Args:
            x (int): The x-coordinate of the top-left corner of the rectangle.
            y (int): The y-coordinate of the top-left corner of the rectangle.
            w (int): The width of the rectangle.
            h (int): The height of the rectangle.
            c (int): The color to fill the rectangle with.

        Returns:
            (tuple): A tuple containing the x, y, w, h values
        """
        r, g, b = color_rgb(c)
        self._buf_ctx.fillStyle = f"rgb({r},{g},{b})"
        self._buf_ctx.fillRect(x, y, w, h)
        self.render((x, y, w, h))
        return (x, y, w, h)

    def blit_rect(self, buf, x, y, w, h):
        """
        Blits a buffer to the display.

        Args:
            buf (bytearray): The buffer to blit, RGB565 little-endian.
            x (int): The x-coordinate of the top-left corner of the buffer.
            y (int): The y-coordinate of the top-left corner of the buffer.
            w (int): The width of the buffer.
            h (int): The height of the buffer.

        Returns:
            (tuple): A tuple containing the x, y, w, h values
        """
        BPP = self.color_depth // 8
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError("The provided x, y, w, h values are out of range")
        if len(buf) != w * h * BPP:
            raise ValueError("The source buffer is not the correct size")
        blit565(self._buf_ctx, buf, x, y, w, h)
        self.render((x, y, w, h))
        return (x, y, w, h)

    def pixel(self, x, y, c):
        """
        Sets a pixel to the given color.

        Args:
            x (int): The x-coordinate of the pixel.
            y (int): The y-coordinate of the pixel.
            c (int): The color to set the pixel to.

        Returns:
            (tuple): A tuple containing the x, y, w & h values.
        """
        return self.fill_rect(x, y, 1, 1, c)

    ############### Scrolling (ILI9341-style, like SDLDisplay / PGDisplay) ################

    def _scroll_changed(self) -> None:
        """Repaint immediately; this backend has no deferred-render tick."""
        self.render()

    def render(self, render_rect=None) -> None:
        """Copy the offscreen buffer to the visible canvas, applying vertical scroll."""
        buf = self._buffer
        vis = self._vis_ctx
        w, h = self.width, self.height
        y_start = self.vscsad()
        if not y_start:
            if render_rect is not None:
                x, y, rw, rh = render_rect
                vis.drawImage(buf, x, y, rw, rh, x, y, rw, rh)
            else:
                vis.drawImage(buf, 0, 0, w, h, 0, 0, w, h)
            return

        tfa = self._tfa
        vsa = self._vsa
        bfa = self._bfa
        if tfa > 0:
            vis.drawImage(buf, 0, 0, w, tfa, 0, 0, w, tfa)

        vsa_top_height = vsa + tfa - y_start
        vis.drawImage(buf, 0, y_start, w, vsa_top_height, 0, tfa, w, vsa_top_height)

        vsa_btm_height = vsa - vsa_top_height
        vis.drawImage(buf, 0, tfa, w, vsa_btm_height, 0, tfa + vsa_top_height, w, vsa_btm_height)

        if bfa > 0:
            vis.drawImage(buf, 0, tfa + vsa, w, bfa, 0, tfa + vsa, w, bfa)

    def show(self, _timer=None) -> None:
        """Present the offscreen canvas (alias of :meth:`render`)."""
        self.render()
