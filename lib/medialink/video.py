"""Pictures over a :class:`~medialink.Link`: a camera on one side, a screen
on the other.

:class:`Video` sends and receives JPEG frames. A frame is cut to the link's
packet size and sent a few packets at a time from ``service()``, paced to
the link's bandwidth, so sound on the same link goes out between them
instead of waiting behind a whole picture. A frame that loses a packet is
dropped on the far side and the next whole one is shown, so a lost packet
costs one picture, never the stream.

:class:`Screen` decodes a JPEG and puts it on a display, fitted and
centred. :class:`FileCamera` stands in for a camera where there isn't one:
it hands out the JPEG files in a folder, one a call, round and round.

A camera is anything whose ``take()`` returns one JPEG, as bytes or a
memoryview, or None when no frame is ready: ``cameraif.Camera`` on an
ESP32-P4 set to JPEG, or :class:`FileCamera`.
"""

from medialink import packet as _p
from medialink._compat import ticks_diff, ticks_ms

#: The video codec ids a frame's header carries.
JPEG = 1


class Video:
    """Send and receive pictures over ``link``.

    ``bandwidth`` is the most bits a second the pictures may use, the
    transport's own figure when None. ``burst`` is the most packets one
    ``service()`` sends: a board's network stack holds only a few incoming
    packets at a time, and a picture sent all at once overflows it.
    """

    def __init__(self, link, *, bandwidth=None, burst=4):
        self.link = link
        if bandwidth is None:
            bandwidth = link.transport.bandwidth
        self._rate = bandwidth // 8  # bytes a second
        self.burst = burst
        self._payload = None
        self._sent_at = ticks_ms()
        self._allowance = burst * link.room
        self.stats = {
            "sent": 0, "skipped": 0, "received": 0, "replaced": 0,
            "bytes": 0, "latency_ms": None, "max_latency_ms": None,
        }

    # --- sending -----------------------------------------------------------

    @property
    def ready(self):
        """True when the last picture has gone, so a new one can be taken."""
        return self._payload is None

    def send(self, jpeg, stamp=None, codec=JPEG):
        """Start sending one picture; ``service()`` sends the rest.

        ``stamp`` is when it was taken, in ``ticks_ms()``; now when None.
        Returns False, and sends nothing, while the last one is still going
        or there is no peer. The bytes must stay as they are until
        ``ready``.
        """
        if self._payload is not None or self.link.peer is None:
            self.stats["skipped"] += 1
            return False
        self._seq, self._frags = self.link._start(_p.VIDEO, len(jpeg))
        self._payload = memoryview(jpeg)
        self._codec = codec
        self._stamp = ticks_ms() if stamp is None else stamp
        self._frag = 0
        self.service()
        return True

    def service(self):
        """Send what the pace allows of the picture in flight."""
        if self._payload is None:
            # Idle: the next picture may start with a whole burst.
            self._sent_at = ticks_ms()
            self._allowance = self.burst * self.link.room
            return
        now = ticks_ms()
        room = self.link.room
        cap = self.burst * room
        self._allowance = min(cap, self._allowance + ticks_diff(now, self._sent_at) * self._rate // 1000)
        self._sent_at = now
        sent = 0
        while sent < self.burst and self._allowance > 0:
            frag = self._frag
            piece = self._payload[frag * room:(frag + 1) * room]
            self.link._fragment(_p.VIDEO, self._codec, 0, frag, self._frags, self._seq, self._stamp, piece)
            self._allowance -= len(piece)
            sent += 1
            self._frag = frag + 1
            if self._frag == self._frags:
                self._payload = None
                self.stats["sent"] += 1
                break

    # --- receiving ---------------------------------------------------------

    def receive(self):
        """The newest whole picture that has arrived, as a
        :class:`~medialink.Frame`, or None. Older ones not yet read are
        skipped, and counted in ``stats["replaced"]``."""
        frames = self.link.frames(_p.VIDEO)
        if not frames:
            return None
        self.stats["replaced"] += len(frames) - 1
        frame = frames[-1]
        self.stats["received"] += 1
        self.stats["bytes"] += len(frame.payload)
        if frame.age is not None:
            latency = frame.age + ticks_diff(ticks_ms(), frame.arrived)
            self.stats["latency_ms"] = latency
            if self.stats["max_latency_ms"] is None or latency > self.stats["max_latency_ms"]:
                self.stats["max_latency_ms"] = latency
        return frame


class Screen:
    """Show JPEG pictures on ``display`` (a displaydev driver, such as
    ``board_config.display_drv``), each fitted inside it and centred.

    A picture bigger than the display is decoded at a half, a quarter or an
    eighth of its size, whichever is the largest that fits. Decoding uses
    ``jpegio``: built into MicroPython firmware that carries it and into
    CircuitPython, and on CPython pydevices-desktop's, over Pillow.

    A picture the decoder can't read (a progressive JPEG, say, which
    jpegio's decoder doesn't take) shows nothing: ``errors`` counts them
    and ``last_error`` says why.
    """

    def __init__(self, display, background=0):
        import jpegio

        self.display = display
        self.background = background
        try:
            # The ESP32-P4's decoder engine, where there is one.
            self._decoder = jpegio.JpegDecoder(hardware=True)
        except (OSError, TypeError, ValueError):
            self._decoder = jpegio.JpegDecoder()
        self._pixels = None
        self._shape = None
        self.errors = 0
        self.last_error = None

    def show(self, jpeg):
        """Decode ``jpeg`` and put it on the display. Returns its size there,
        or None when it couldn't be read."""
        try:
            return self._show(jpeg)
        except (ValueError, RuntimeError, MemoryError) as error:
            self.errors += 1
            self.last_error = error
            return None

    def _show(self, jpeg):
        display = self.display
        decoder = self._decoder
        width, height = decoder.open(jpeg)
        scale = 0
        while scale < 3 and ((width >> scale) > display.width or (height >> scale) > display.height):
            scale += 1
        width, height = width >> scale, height >> scale
        x = (display.width - width) // 2
        y = (display.height - height) // 2
        if self._shape != (width, height):
            # A new size: clear what the last picture leaves showing.
            self._shape = (width, height)
            self._pixels = bytearray(width * height * 2)
            display.fill_rect(0, 0, display.width, display.height, self.background)
            self._present(0, 0, display.width, display.height)
        decoder.decode(self._pixels, scale)
        display.blit_rect(self._pixels, x, y, width, height)
        self._present(x, y, width, height)
        return width, height

    def _present(self, x, y, w, h):
        # A board's panel shows the rows that changed; elsewhere, the frame.
        flush = getattr(self.display, "flush_rect", None)
        if flush is None or not flush(x, y, w, h):
            show = getattr(self.display, "show", None)
            if show is not None:
                show()


class FileCamera:
    """A camera made of the JPEG files in ``folder``, in name order.

    ``take()`` returns the next file's bytes each call, and starts
    over after the last. Use it to send pictures from a computer with no
    camera, or known pictures whose arrival you want to check.
    """

    def __init__(self, folder):
        import os

        names = sorted(name for name in os.listdir(folder) if name.lower().endswith((".jpg", ".jpeg")))
        if not names:
            raise OSError("no JPEG files in %s" % folder)
        self.paths = [folder.rstrip("/") + "/" + name for name in names]
        self._next = 0

    def take(self):
        path = self.paths[self._next]
        self._next = (self._next + 1) % len(self.paths)
        with open(path, "rb") as file:
            return file.read()

    def capture_jpeg(self, quality=None):
        return self.take()

    def deinit(self):
        pass
