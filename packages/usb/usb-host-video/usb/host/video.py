# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# MicroPython USB video host: frames from a webcam on the host port.
# MIT license; Copyright (c) 2026 Brad Barnett
#
#     import usb.core
#     from usb.host.video import Camera
#
#     usb.core.start(classes=("uvc",))
#     cam = Camera(usb.core.find(custom_match=Camera.match), max_size=(320, 240))
#     print(cam.encoding, cam.width, cam.height, cam.fps)    # what it agreed to
#     buf = bytearray(cam.frame_bytes)
#     cam.start()
#     while True:
#         n = cam.read(buf)            # a whole frame (a JPEG, or YUY2), or 0
#
# Any class-compliant camera: a Logitech, or a PyDevices board running
# usb-device-video. The camera's descriptors are read here, a mode is
# negotiated with it (UVC's PROBE and COMMIT: the camera says what a mode
# costs on the bus), and its frames stream in over isochronous transfers,
# moved in C and assembled into whole frames in a ring. MJPEG is preferred
# when the camera offers it, since it carries a far larger picture through
# the same bus.
import _usbhost

from machine import USBDevice

from . import _uvc

_SET_CUR = 0x01
_GET_CUR = 0x81
_PROBE = 0x0100             # VS_PROBE_CONTROL << 8
_COMMIT = 0x0200            # VS_COMMIT_CONTROL << 8
# The negotiation block: 26 bytes in UVC 1.0, 34 in 1.1. A 1.0 camera
# answers the first 26, which hold every field read here.
_PROBE_LEN = 34
_CTRL_MS = 3000
_CT_AE_PRIORITY = 0x03      # Camera Terminal control: may exposure slow the frame rate?
_ITT_CAMERA = 0x0201


def _negotiate(dev, itf, format_index, frame_index, interval):
    """PROBE, read back what the camera will do, COMMIT that verbatim.
    Returns (dwMaxPayloadTransferSize, dwMaxVideoFrameSize): the camera says
    what a mode costs on the bus, and that picks the alternate setting."""
    probe = bytearray(_PROBE_LEN)
    probe[2] = format_index
    probe[3] = frame_index
    probe[4:8] = interval.to_bytes(4, "little")
    dev.ctrl_transfer(0x21, _SET_CUR, _PROBE, itf, probe, _CTRL_MS)
    got = bytearray(_PROBE_LEN)
    dev.ctrl_transfer(0xA1, _GET_CUR, _PROBE, itf, got, _CTRL_MS)
    # Committing anything but what the camera just answered is how a stream
    # ends up in a mode neither side agreed to.
    dev.ctrl_transfer(0x21, _SET_CUR, _COMMIT, itf, got, _CTRL_MS)
    return int.from_bytes(got[22:26], "little"), int.from_bytes(got[18:22], "little")


class Camera:
    @staticmethod
    def match(dev):
        """For usb.core.find(custom_match=...): a device with a video
        streaming interface."""
        return bool(_uvc.formats(dev.configuration_descriptor()))

    def __init__(self, dev, *, encoding=None, max_size=None, fps=None, in_limit=None):
        """Negotiate the largest mode up to ``max_size`` (w, h) the camera
        and the bus can carry. ``encoding`` "mjpeg" or "yuy2" insists on one
        (None prefers MJPEG); ``fps`` asks for a rate (None: the highest that
        fits); ``in_limit`` caps the bytes per isochronous packet, for a host
        controller with a small FIFO (an ESP32-S3's is 600 when it streams
        video).

        The host takes one transaction per microframe, so only the alternate
        settings that carry one (up to 944 bytes on a Logitech C920e, 7.5 MB/s
        at high speed) are used. A camera asks for more than that for its
        larger MJPEG modes, because it reserves for the worst frame, and
        a real frame takes far less: with ``in_limit`` left as ``None`` such a
        mode is streamed on the largest alternate setting there is, and
        ``best_effort`` says so. Uncompressed modes are never taken
        that way, since their bandwidth is exactly what the camera says."""
        if dev is None:
            raise ValueError("no camera")
        self.dev = dev
        self._id = dev._id
        blob = dev.configuration_descriptor()
        self._formats = _uvc.formats(blob)
        self._blob = blob
        # A host transaction is one packet a microframe: an alternate setting
        # that promises two or three is more than it can take.
        self._alts = tuple(a for a in _uvc.alt_settings(blob) if a.per_frame == 1)
        if not self._formats:
            raise ValueError("not a USB video device")
        self._open = False
        self._ring = None
        self._hdr = bytearray(4)
        self._scratch = None
        self._last = (0,) * 8
        self.best_effort = False
        picked = self._negotiate(encoding, max_size, fps, in_limit)
        if picked is None:
            why = ""
            if self._over_limit is not None:
                why = " (the smallest it asked for was %d-byte packets, over in_limit=%d)" % (
                    self._over_limit, in_limit)
            raise ValueError("no mode the camera and this bus can both carry%s; it offers: %s"
                             % (why, "; ".join(self.modes())))
        fmt, frame, interval, payload, frame_bytes, alt = picked
        self.best_effort = alt.max_packet < payload
        self._fmt, self._alt = fmt, alt
        self.encoding = fmt.encoding
        self.width, self.height = frame.width, frame.height
        self.fps = round(_uvc.fps(interval), 2)
        self.payload = payload
        self.frame_bytes = frame_bytes

    def modes(self):
        """What the camera offers, as strings."""
        return [_uvc.describe(f, fr) for f in self._formats for fr in f.frames]

    def _negotiate(self, encoding, max_size, fps, in_limit):
        max_w, max_h = max_size or (10000, 10000)
        found = []
        for fmt in self._formats:
            if encoding and fmt.encoding.lower() != encoding.lower():
                continue
            for frame in fmt.frames:
                if frame.width <= max_w and frame.height <= max_h:
                    rank = 1 if fmt.encoding == "mjpeg" else 0
                    found.append((frame.width * frame.height, rank, fmt, frame))
        found.sort(key=lambda c: (c[0], c[1]), reverse=True)
        self._over_limit = None     # the smallest payload in_limit refused
        for _, _, fmt, frame in found:
            intervals = list(frame.intervals) or [0]
            if fps:
                intervals.sort(key=lambda i: abs(_uvc.fps(i) - fps) if i else 0)
            else:
                intervals.sort()    # shortest interval, the highest rate, first
            for interval in intervals:
                payload, frame_bytes = _negotiate(self.dev, fmt.interface, fmt.index, frame.index, interval)
                if in_limit and payload > in_limit:
                    if self._over_limit is None or payload < self._over_limit:
                        self._over_limit = payload
                    continue
                alt = _uvc.alt_for_payload(self._alts, payload)
                if alt is None and not in_limit and fmt.encoding == "mjpeg":
                    alt = self._largest_alt()
                if alt is not None:
                    return fmt, frame, interval, payload, frame_bytes, alt
        return None

    def _largest_alt(self):
        best = None
        for a in self._alts:
            if a.transfer == "isoc" and (best is None or a.max_packet > best.max_packet):
                best = a
        return best

    def hold_frame_rate(self, hold=True):
        """Keep the camera at the frame rate it agreed to, or let it lower it.

        Most cameras, in a dim room, lengthen the exposure and send fewer
        frames than the mode says: a C920e asked for 30 a second gave 22 at
        640x480. With ``hold`` true, the default, the camera keeps its rate and
        lets the picture get darker or noisier instead.

        Args:
            hold: True to hold the rate, False for the camera's own default.

        Returns:
            True if the camera took the setting, False if it has no such
            control.
        """
        vc = ct = None
        for length, dtype, body in _uvc.descriptors(self._blob):
            if dtype == _uvc.DT_INTERFACE and length >= 9:
                if body[5] == _uvc.CLASS_VIDEO and body[6] == _uvc.SUBCLASS_VIDEOCONTROL:
                    vc = body[2]
            elif dtype == _uvc.DT_CS_INTERFACE and vc is not None and length >= 8 and body[2] == 0x02:
                if body[4] | body[5] << 8 == _ITT_CAMERA:
                    ct = body[3]
        if vc is None or ct is None:
            return False
        try:
            self.dev.ctrl_transfer(0x21, _SET_CUR, _CT_AE_PRIORITY << 8, ct << 8 | vc,
                                   bytes((0 if hold else 1,)), _CTRL_MS)
        except OSError:
            return False
        return True

    def start(self):
        if not self._open:
            a = self._alt
            itf = self._fmt.interface
            # A program cut off mid-stream (Ctrl-C) leaves its stream and the
            # interface's streaming alternate setting behind, and a second
            # Camera started on top of them got EBUSY and left the camera in a
            # state only an unplug cleared. Let go of what is there first.
            try:
                _usbhost.host_stream(self._id, a.endpoint, None)
            except OSError:
                pass
            self._park()
            self.dev.set_interface_altsetting(itf, a.alt)
            # Room for a whole frame waiting while the next one builds, each
            # led by its length; the ring rounds up to a power of two.
            ring = USBDevice.Ring(2 * (self.frame_bytes + 4))
            try:
                _usbhost.host_stream(self._id, a.endpoint, ring, a.max_packet, video=True,
                                   max_frame=self.frame_bytes)
            except BaseException:
                self._park()
                raise
            self._ring = ring
            self._open = True

    def read(self, buf):
        """The newest whole frame into buf, returning its length, or 0 when
        no new frame has arrived. Older frames waiting are skipped, and so is
        a frame larger than buf."""
        if not self._open:
            return 0
        r, hdr, n = self._ring, self._hdr, 0
        while r.any() >= 4:
            r.readinto(hdr, 4)
            size = hdr[0] | hdr[1] << 8 | hdr[2] << 16 | hdr[3] << 24
            if size <= len(buf):
                r.readinto(buf, size)
                n = size
            else:
                self._skip(size)
        return n

    def _skip(self, size):
        if self._scratch is None:
            self._scratch = bytearray(512)
        while size > 0:
            size -= self._ring.readinto(self._scratch, min(size, 512))

    def stats(self):
        """(frames, packets, bytes, dropped_full, dropped_torn, dropped_big,
        errors, empty). After stop(), the stream's last."""
        if not self._open:
            return self._last
        st = _usbhost.host_stream_stats(self._id, self._alt.endpoint)
        if not st:
            return self._last
        packets, nbytes, full, _, errors, empty, frames, torn, big = st
        return (frames, packets, nbytes, full, torn, big, errors, empty)

    def stop(self):
        if self._open:
            self._last = self.stats()
            _usbhost.host_stream(self._id, self._alt.endpoint, None)
            self._open = False
            self._ring = None
            self._park()

    def _park(self):
        # Back to alternate 0, the zero-bandwidth setting, and let go of it,
        # so the camera stops holding isochronous schedule.
        itf = self._fmt.interface
        try:
            self.dev.set_interface_altsetting(itf, 0)
        except OSError:
            pass
        try:
            self.dev._release(itf)
        except OSError:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
