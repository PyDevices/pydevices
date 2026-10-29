"""jpegio on CPython: JPEG decode and encode, the same API as MicroPython's
built-in jpegio (micropython-pydevices' modules/jpegio), over Pillow.

    d = jpegio.JpegDecoder(); w, h = d.open(jpeg); d.decode(buf, scale)   # RGB565 into buf
    jpeg = jpegio.JpegEncoder(quality=80).encode(buf, w, h)              # bytes

An app imports jpegio and doesn't care which runtime it's on. Pixels are
native-order (little-endian) RGB565, as displaydev framebuffers hold them.
The pixels Pillow decodes are close to TJpgDec's but not the same bytes;
``scale`` shrinks by 1, 1/2, 1/4 or 1/8 as the C module does.
"""

import io

try:
    from PIL import Image, ImageChops
except ImportError as e:  # pragma: no cover - the message is the point
    raise ImportError(
        "jpegio needs Pillow on CPython. Install it with:  pip install pillow"
    ) from e

RGB565 = 0
GRAY = 1


def _rgb565(image):
    """Native-order RGB565 bytes of a Pillow image."""
    r, g, b = image.convert("RGB").split()
    # The two bytes of each pixel, built from disjoint bits so add() never clips.
    hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
    return Image.merge("LA", (lo, hi)).tobytes()


class JpegDecoder:
    """``JpegDecoder()``: ``open(source)``, then ``decode(target, scale, x, y)``.

    ``hardware=True`` asks for a decoder engine, which a computer doesn't
    have, so it raises OSError as the C module does on a chip without one.
    """

    def __init__(self, *, hardware=False):
        if hardware:
            raise OSError("no JPEG decoder engine on this computer")
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
        self._size = None
        if isinstance(source, str):
            with open(source, "rb") as f:
                data = f.read()
        elif hasattr(source, "read"):
            data = source.read()
        else:
            data = bytes(memoryview(source).cast("B"))
        try:
            image = Image.open(io.BytesIO(data))
            if image.format != "JPEG":
                raise ValueError
        except Exception:
            raise ValueError("jpegio: not a JPEG") from None
        self._image = image
        self._size = image.size
        return image.size

    def decode(self, target, scale=0, x=0, y=0, *, stride=None):
        """Native-order RGB565 into ``target`` (a buffer, or a callable taking
        ``(x, y, w, h, mv)`` per block of rows), the image's top-left at (x, y)."""
        if self._image is None:
            raise RuntimeError("decode() without open()")
        if scale not in (0, 1, 2, 3):
            raise ValueError("scale must be 0..3")
        w, h = self._size[0] >> scale, self._size[1] >> scale
        image = self._image
        if callable(target):
            if stride is not None:
                raise TypeError("stride isn't accepted with a callable target")
        else:
            stride = w if stride is None else stride
            if x < 0 or y < 0 or x + w > stride:
                raise ValueError("the image doesn't fit across the target at that x and stride")
            out = memoryview(target).cast("B")
            need = ((y + h - 1) * stride + x + w) * 2
            if out.nbytes < need:
                raise ValueError("target has %d bytes; %dx%d at (%d, %d) with stride %d needs %d"
                                 % (out.nbytes, w, h, x, y, stride, need))
        self._image = None  # one-shot, as the C module is
        try:
            if scale:
                image.draft("RGB", (w, h))
                image = image.convert("RGB").resize((w, h))
            pixels = _rgb565(image)
        except Exception:
            raise ValueError("jpegio: JPEG image data is corrupt") from None
        row = w * 2
        if callable(target):
            # Strips of 16 rows, in raster order, as the C module's blocks come.
            for top in range(0, h, 16):
                rows = min(16, h - top)
                block = memoryview(pixels[top * row:(top + rows) * row]).cast("H")
                target(x, y + top, w, rows, block)
            return
        for j in range(h):
            at = ((y + j) * stride + x) * 2
            out[at:at + row] = pixels[j * row:(j + 1) * row]


class JpegEncoder:
    """``JpegEncoder(quality=80, subsampling=420)``. ``hardware=True`` raises
    OSError: a computer has no JPEG engine. ``exact`` is accepted and ignored."""

    def __init__(self, quality=80, subsampling=420, *, hardware=None, exact=True):
        if not 1 <= quality <= 100:
            raise ValueError("quality must be 1..100")
        if subsampling not in (420, 444):
            raise ValueError("subsampling must be 420 or 444")
        if hardware:
            raise OSError("no JPEG engine on this computer")
        self.quality = quality
        self.subsampling = subsampling
        self.hardware = False

    def encode(self, buffer, width, height, *, format=RGB565, stride=None, swap=False):
        if format not in (RGB565, GRAY):
            raise ValueError("format must be RGB565 or GRAY")
        bpp = 2 if format == RGB565 else 1
        stride = width * bpp if stride is None else stride
        data = memoryview(buffer).cast("B")
        if data.nbytes < stride * (height - 1) + width * bpp:
            raise ValueError("buffer is too small for %dx%d" % (width, height))
        rows = b"".join(bytes(data[j * stride:j * stride + width * bpp]) for j in range(height))
        if format == GRAY:
            image = Image.frombuffer("L", (width, height), rows, "raw", "L", 0, 1)
        else:
            if swap:
                swapped = bytearray(rows)
                swapped[0::2], swapped[1::2] = rows[1::2], rows[0::2]
                rows = bytes(swapped)
            # Pillow's BGR;16 is native little-endian 5-6-5.
            image = Image.frombuffer("RGB", (width, height), rows, "raw", "BGR;16", 0, 1)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=self.quality, subsampling=2 if self.subsampling == 420 else 0)
        return out.getvalue()
