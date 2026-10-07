"""pngio on CPython: PNG encode and decode, the same API as MicroPython's
built-in pngio (micropython-pydevices' modules/pngio), over Pillow.

    png = pngio.PngEncoder(level=1).encode(fb, 480, 270)        # bytes
    d = pngio.PngDecoder(); w, h = d.open(png); d.decode(buf)   # RGB565 into buf

An app imports pngio and doesn't care which runtime it's on. Pixels are
native-order (little-endian) RGB565 by default, as displaydev framebuffers
hold them; RGB565 widens by bit replication (31 -> 255) and narrows by
truncation, as the C module does, so a round trip is exact.
"""

import io

try:
    from PIL import Image, ImageChops
except ImportError as e:  # pragma: no cover - the message is the point
    raise ImportError(
        "pngio needs Pillow on CPython. Install it with:  pip install pillow"
    ) from e

RGB565 = 0
GS8 = 1
RGB888 = 2

_IN_BPP = {RGB565: 2, GS8: 1, RGB888: 3}


def _rows(buffer, width, height, stride, bpp):
    """The image's bytes, tight, from a buffer whose rows are stride pixels apart."""
    data = memoryview(buffer).cast("B")
    if stride == width:
        return bytes(data[: width * height * bpp])
    row, step = width * bpp, stride * bpp
    return b"".join(bytes(data[y * step : y * step + row]) for y in range(height))


class PngEncoder:
    """``PngEncoder(level=1)``: level 1 (fastest) to 9 (smallest)."""

    def __init__(self, level=1):
        if not 1 <= level <= 9:
            raise ValueError("level must be 1..9")
        self.level = level

    def encode(self, buffer, width, height, *, format=RGB565, stride=None, swap=False):
        if format not in _IN_BPP:
            raise ValueError("format must be RGB565, GS8 or RGB888")
        if not (1 <= width <= 32767 and 1 <= height <= 32767):
            raise ValueError("width and height must be 1..32767")
        stride = width if stride is None else stride
        if stride < width:
            raise ValueError("stride must be at least width")
        bpp = _IN_BPP[format]
        need = (stride * (height - 1) + width) * bpp
        have = memoryview(buffer).nbytes
        if have < need:
            raise ValueError("buffer has %d bytes; %dx%d needs %d" % (have, width, height, need))
        data = _rows(buffer, width, height, stride, bpp)
        if format == RGB565:
            if swap:
                b = bytearray(data)
                b[0::2], b[1::2] = data[1::2], data[0::2]
                data = bytes(b)
            # Pillow's BGR;16 is native little-endian 5-6-5, widened by replication
            im = Image.frombuffer("RGB", (width, height), data, "raw", "BGR;16", 0, 1)
        elif format == GS8:
            im = Image.frombuffer("L", (width, height), data, "raw", "L", 0, 1)
        else:
            im = Image.frombuffer("RGB", (width, height), data, "raw", "RGB", 0, 1)
        out = io.BytesIO()
        im.save(out, "PNG", compress_level=self.level)
        return out.getvalue()


class PngDecoder:
    """``PngDecoder()``: ``open(source)``, then ``decode(target, x, y)``."""

    def __init__(self):
        self._image = None
        self._size = None

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

    def open(self, source):
        """``source``: bytes-like, a path, or a binary stream. Returns (width, height)."""
        self._image = None
        if isinstance(source, str):
            with open(source, "rb") as f:
                data = f.read()
        elif hasattr(source, "read"):
            data = source.read()
        else:
            data = bytes(memoryview(source).cast("B"))
        try:
            im = Image.open(io.BytesIO(data))
            if im.format != "PNG":
                raise ValueError
            if im.info.get("interlace"):
                raise ValueError("interlaced PNG isn't supported")
        except ValueError as e:
            raise ValueError("pngio: %s" % (e or "not a PNG")) from None
        except Exception:
            raise ValueError("pngio: not a PNG") from None
        self._image = im
        self._size = im.size
        return im.size

    def decode(self, target, x=0, y=0, *, stride=None):
        """Native-order RGB565 into ``target``, the image's top-left at (x, y)."""
        if self._image is None:
            raise RuntimeError("decode() without open()")
        w, h = self._size
        stride = w if stride is None else stride
        if x < 0 or y < 0 or x + w > stride:
            raise ValueError("the image doesn't fit across the target at that x and stride")
        out = memoryview(target).cast("B")
        need = ((y + h - 1) * stride + x + w) * 2
        if out.nbytes < need:
            raise ValueError("target has %d bytes; %dx%d at (%d, %d) with stride %d needs %d"
                             % (out.nbytes, w, h, x, y, stride, need))
        try:
            # the pixels are read here, as the C module inflates them in decode()
            rgb = self._image.convert("RGB")
        except Exception:
            self._image = None
            raise ValueError("pngio: PNG image data is corrupt") from None
        r, g, b = rgb.split()
        # the two bytes of each pixel, built from disjoint bits so add() never clips
        hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
        lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
        px = Image.merge("LA", (lo, hi)).tobytes()
        row = w * 2
        for j in range(h):
            at = ((y + j) * stride + x) * 2
            out[at:at + row] = px[j * row:(j + 1) * row]
        self._image = None
