# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""svgio on CPython: SVG decode, the same API as MicroPython's built-in
svgio (micropython-pydevices' modules/svgio), over resvg and Pillow.

    d = svgio.SvgDecoder()
    w, h = d.open("wifi.svg", width=48)          # or bytes, or a stream
    d.decode(pixels, alpha)                      # RGB565 and coverage
    d.decode(fb_buf, x=10, y=10, stride=480)     # blended over what's there

An app imports svgio and doesn't care which runtime it's on. Pixels are
native-order (little-endian) RGB565, as displaydev framebuffers hold them.
resvg reads more SVG than the MicroPython module does, so a file that draws
the same everywhere keeps to what that module reads: shapes, paths,
strokes, transforms, opacity and gradients, with text turned into paths.
"""

import io

try:
    import resvg_py
    from PIL import Image, ImageChops
except ImportError as e:  # pragma: no cover - the message is the point
    raise ImportError(
        "svgio needs resvg-py and Pillow on CPython. Install them with:  pip install resvg-py pillow"
    ) from e

_MAX = 32767


def _render(text, zoom):
    """The SVG drawn at zoom, as a Pillow RGBA image."""
    try:
        png = resvg_py.svg_to_bytes(svg_string=text, zoom=zoom, skip_system_fonts=True)
    except ValueError:
        raise ValueError("svgio: not an SVG with a size") from None
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _to_565(rgb):
    """A Pillow RGB image as native-order RGB565 bytes, truncating as the C module does."""
    r, g, b = rgb.split()
    # the two bytes of each pixel, built from disjoint bits so add() never clips
    hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
    return Image.merge("LA", (lo, hi)).tobytes()


class SvgDecoder:
    """``SvgDecoder()``: ``open(source, width=)``, then ``decode(target, alpha)``."""

    def __init__(self):
        self._text = None
        self._size = None
        self._zoom = 1.0

    @property
    def width(self):
        if self._size is None:
            raise RuntimeError("width needs a successful open()")
        return self._size[0]

    @property
    def height(self):
        if self._size is None:
            raise RuntimeError("height needs a successful open()")
        return self._size[1]

    def open(self, source, *, width=None, height=None, scale=None):
        """``source``: bytes-like, a path, or a binary stream. Returns (width, height)."""
        if sum(v is not None for v in (width, height, scale)) > 1:
            raise ValueError("give one of width, height and scale")
        self._text = self._size = None
        if isinstance(source, str):
            with open(source, "rb") as f:
                data = f.read()
        elif hasattr(source, "read"):
            data = source.read()
        else:
            data = bytes(memoryview(source).cast("B"))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("svgio: not an SVG with a size") from None
        own = _render(text, 1.0).size
        if width is not None:
            zoom = width / own[0]
        elif height is not None:
            zoom = height / own[1]
        else:
            zoom = 1.0 if scale is None else float(scale)
        w, h = int(own[0] * zoom + 0.5), int(own[1] * zoom + 0.5)
        if not (zoom > 0 and 1 <= w <= _MAX and 1 <= h <= _MAX):
            raise ValueError("svgio: the size must come to 1..32767 pixels a side")
        self._text, self._size, self._zoom = text, (w, h), zoom
        return w, h

    def decode(self, target, alpha=None, *, x=0, y=0, stride=None):
        """RGB565 into ``target`` and coverage into ``alpha``; ``target`` alone blends."""
        if self._text is None:
            raise RuntimeError("decode() needs a successful open()")
        if target is None and alpha is None:
            raise ValueError("give a target, an alpha buffer, or both")
        w, h = self._size
        stride = w if stride is None else stride
        if x < 0 or y < 0 or x + w > stride:
            raise ValueError("the image doesn't fit across the target at that x and stride")
        pix = memoryview(target).cast("B") if target is not None else None
        cov = memoryview(alpha).cast("B") if alpha is not None else None
        last = (y + h - 1) * stride + x + w
        if pix is not None and pix.nbytes < last * 2:
            raise ValueError("target has %d bytes; it needs %d" % (pix.nbytes, last * 2))
        if cov is not None and cov.nbytes < last:
            raise ValueError("alpha has %d bytes; it needs %d" % (cov.nbytes, last))

        image = _render(self._text, self._zoom)
        if image.size != (w, h):
            # resvg rounds its canvas up; the C module rounds to nearest
            canvas = Image.new("RGBA", (w, h))
            canvas.paste(image.crop((0, 0, min(w, image.width), min(h, image.height))), (0, 0))
            image = canvas
        a = image.getchannel("A")
        rows = range(h)

        if cov is not None:
            mask = a.tobytes()
            for j in rows:
                at = (y + j) * stride + x
                cov[at : at + w] = mask[j * w : (j + 1) * w]
            if pix is not None:
                px = _to_565(image.convert("RGB"))
                for j in rows:
                    at = ((y + j) * stride + x) * 2
                    pix[at : at + w * 2] = px[j * w * 2 : (j + 1) * w * 2]
            return

        # Blended over what the target holds, widened to 8 bits a channel.
        under = b"".join(bytes(pix[((y + j) * stride + x) * 2 : ((y + j) * stride + x + w) * 2]) for j in rows)
        back = Image.frombuffer("RGB", (w, h), under, "raw", "BGR;16", 0, 1)
        px = _to_565(Image.composite(image.convert("RGB"), back, a))
        for j in rows:
            at = ((y + j) * stride + x) * 2
            pix[at : at + w * 2] = px[j * w * 2 : (j + 1) * w * 2]
