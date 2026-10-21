
import lvgl as lv

from spotify_remote import artwork_cache

_JPEG_DECODER = None  # "jpegio", "tjpgd", or None until jpeg_supported() finds one


def _hex(color):
    return lv.color_hex(color)


def _jpeg_size(data):
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue

        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9):
            continue

        segment_size = (data[index] << 8) | data[index + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            height = (data[index + 3] << 8) | data[index + 4]
            width = (data[index + 5] << 8) | data[index + 6]
            return width, height

        index += segment_size

    return 0, 0


_decoder = None


def _decode_rgb565(data):
    """(descriptor, pixels) for a JPEG decoded once to RGB565, or None.

    LVGL's image cache is off in these builds (LV_CACHE_DEF_SIZE 0), so an
    lv.image showing a JPEG decodes it again on every redraw: ~124 ms for a
    300x300 cover on an ESP32-S3, more than once per frame, which tripled a
    full redraw of the Now screen (117 -> ~390 ms). Decoded here once, LVGL
    only copies pixels.
    """
    global _decoder
    try:
        import jpegio

        if _decoder is None:
            _decoder = jpegio.JpegDecoder()
        width, height = _decoder.open(data)
        pixels = bytearray(width * height * 2)
        _decoder.decode(pixels)
    except Exception:  # noqa: BLE001 - fall back to LVGL's own decoding
        return None
    descriptor = lv.image_dsc_t()
    descriptor.header.magic = lv.IMAGE_HEADER_MAGIC
    descriptor.header.cf = lv.COLOR_FORMAT.RGB565
    descriptor.header.w = width
    descriptor.header.h = height
    descriptor.header.stride = width * 2
    descriptor.data_size = len(pixels)
    descriptor.data = pixels
    return descriptor, pixels


def _image_descriptor(path):
    if path.startswith(artwork_cache.MEMORY_PREFIX):
        data = artwork_cache.memory_bytes(path)
        if data is None:
            return None, None
    else:
        with open(path, "rb") as file:
            data = file.read()

    if data.startswith(b"\xff\xd8") and jpeg_supported():
        if _JPEG_DECODER == "jpegio":
            decoded = _decode_rgb565(data)
            if decoded is not None:
                return decoded
        width, height = _jpeg_size(data)
    else:
        width = 0
        height = 0

    if not width or not height:
        return None, None

    descriptor = lv.image_dsc_t()
    descriptor.header.magic = lv.IMAGE_HEADER_MAGIC
    descriptor.header.cf = lv.COLOR_FORMAT.RAW
    descriptor.header.w = width
    descriptor.header.h = height
    descriptor.header.stride = 0
    descriptor.data_size = len(data)
    descriptor.data = data
    return descriptor, data


def jpeg_supported():
    """Return True when this LVGL build can decode JPEG (Spotify cover art)."""
    global _JPEG_DECODER
    if _JPEG_DECODER is None:
        try:
            # MicroPython firmware: displayif's jpegio registers the decoder
            # (LVGL's own TJPGD is off there). Idempotent; call it explicitly
            # because not every port registers on import (displayif#41).
            import jpegio

            jpegio.register_lvgl_decoder()
            _JPEG_DECODER = "jpegio"
        except (ImportError, AttributeError, RuntimeError):
            try:
                # CPython lvgl: LVGL's built-in TJPGD.
                lv.tjpgd_init()
                _JPEG_DECODER = "tjpgd"
            except AttributeError:
                pass
    return _JPEG_DECODER is not None


def jpeg_scalable():
    """Return True when decoded JPEGs can be scaled.

    jpegio decodes the whole image, so LVGL can transform it. LVGL's TJPGD
    decodes tile by tile and draws scaled images wrong (lvgl-python#23).
    """
    return jpeg_supported() and _JPEG_DECODER == "jpegio"


def set_thumbnail(image, path):
    """Show a cached image file in image, scaled to fit its size.

    Returns the (descriptor, data) pair the caller must keep alive while the
    image shows it, or None when the file cannot be shown.
    """
    descriptor, data = _image_descriptor(path)
    if descriptor is None:
        return None
    image.set_src(descriptor)
    image.set_inner_align(lv.image.ALIGN.CONTAIN)
    # LVGL's CONTAIN alignment centers an image but does not resize it. Set a
    # native scale so album art fits the row thumbnail instead of being cropped.
    try:
        source_w = int(descriptor.header.w)
        source_h = int(descriptor.header.h)
        target_w = int(image.get_width())
        target_h = int(image.get_height())
        if source_w > 0 and source_h > 0 and target_w > 0 and target_h > 0:
            scale = min(target_w * 256 // source_w, target_h * 256 // source_h)
            image.set_scale(max(1, min(256, scale)))
    except (AttributeError, TypeError, ValueError):
        pass
    return descriptor, data


class CoverArtView:
    def __init__(self, parent, size, bg_color, text_color):
        self.size = size
        self.path = None
        self.src = None
        self._data = None
        self._descriptor = None
        self._shown_once = False

        self.container = lv.obj(parent)
        self.container.set_size(size, size)
        self.container.set_style_bg_color(_hex(bg_color), 0)
        self.container.set_style_border_width(0, 0)
        self.container.remove_flag(lv.obj.FLAG.SCROLLABLE)

        self.image = lv.image(self.container)
        self.image.center()

        self.placeholder = lv.label(self.container)
        self.placeholder.set_width(size - 24)
        self.placeholder.set_style_text_color(_hex(text_color), 0)
        self.placeholder.set_text("No cover art")
        self.placeholder.center()

    def align(self, align, x, y):
        self.container.align(align, x, y)

    def set_art(self, path):
        # Same art (or the same missing art) as shown: nothing to do. This is
        # called on every now-playing refresh, and redoing it cost ~300 ms a
        # time on an ESP32-S3 (2026-09-25).
        if path == self.path and (self._descriptor is not None or self._shown_once):
            return
        self._shown_once = True

        self._release_art()
        self.path = path
        if not path:
            self._show_placeholder("No cover art")
            return

        descriptor, data = _image_descriptor(path)
        if descriptor is not None:
            try:
                self.image.set_src(descriptor)
                self.src = descriptor
                self._descriptor = descriptor
                self._data = data
                # LVGL's TJPGD decoder renders JPEGs in tiles and does not
                # support zoom/rotation. Keep native scale and choose a
                # reasonably sized Spotify image before it reaches the view.
                self.image.set_scale(256)
                self.image.center()
                self.image.remove_flag(lv.obj.FLAG.HIDDEN)
                self.placeholder.add_flag(lv.obj.FLAG.HIDDEN)
                self.image.invalidate()
                self.container.invalidate()
                return
            except Exception:
                pass

        self._show_placeholder("Cover unavailable")

    def _release_art(self):
        # No gc.collect(): a full collection is ~105 ms on a 5 MB PSRAM heap,
        # and the allocator collects when it needs the room.
        self.src = None
        self._data = None
        self._descriptor = None

    def _show_placeholder(self, text):
        self._release_art()
        self.image.add_flag(lv.obj.FLAG.HIDDEN)
        self.placeholder.set_text(text)
        self.placeholder.remove_flag(lv.obj.FLAG.HIDDEN)
        self.placeholder.center()
