# MicroPython USB MTP/PTP host: photos and files off a phone or a camera.
# MIT license; Copyright (c) 2026 Brad Barnett
#
#     import usb.core
#     from usb.host.mtp import MTP
#
#     phone = MTP(usb.core.find(custom_match=MTP.match))
#     for handle in phone.photos():
#         info = phone.info(handle)
#         print(info.name, info.size)
#         phone.get(handle, "/sd/" + info.name)     # or phone.read(handle), phone.thumb(handle)
#     phone.close()
#
# A phone in "File transfer" (MTP) or "Photo transfer" (PTP) USB mode, or a
# camera, speaks PTP's transactions over one bulk pair: a command container,
# an optional data phase, a response. This is the handful a photo frame
# needs: open a session, list storages and objects (GetObjectHandles),
# describe one (GetObjectInfo), and fetch it whole, in parts, or as its
# thumbnail. Reading only; nothing is written to the phone.
#
# A phone shares no storage until its screen is unlocked and someone taps
# Allow on its "Allow access to phone data?" prompt. Until then it opens a
# session and describes itself, and anything that lists files raises
# NoStorageError.
#
# Start the USB host before you plug the phone in. A Samsung phone that no
# host enumerates within about two minutes decides it's on a charger and
# stops answering on USB until it's plugged in again.
import struct

import usb.core

#: Object formats, for handles(format=...).
ASSOCIATION = 0x3001   # a folder
JPEG = 0x3801          # EXIF/JPEG
PNG = 0x380B
HEIF = 0xB301          # what newer phones shoot by default (MTP's vendor range)
IMAGES = (JPEG, PNG, 0x3807, 0x3808, 0x380D, HEIF)   # JPEG, PNG, GIF, JFIF, TIFF, HEIF

_OPEN_SESSION = 0x1002
_CLOSE_SESSION = 0x1003
_GET_DEVICE_INFO = 0x1001
_GET_STORAGE_IDS = 0x1004
_GET_STORAGE_INFO = 0x1005
_GET_OBJECT_HANDLES = 0x1007
_GET_OBJECT_INFO = 0x1008
_GET_OBJECT = 0x1009
_GET_THUMB = 0x100A
_GET_PARTIAL_OBJECT = 0x101B

_OK = 0x2001
_INVALID_STORAGE = 0x2008
_SESSION_ALREADY_OPEN = 0x201E

_COMMAND, _DATA, _RESPONSE = 1, 2, 3
_ALL = 0xFFFFFFFF
_CHUNK = 16384


class MTPError(OSError):
    """A response other than OK. ``code`` is PTP's response code."""

    def __init__(self, op, code, message=None):
        super().__init__(5, message or "PTP op 0x%04x answered 0x%04x" % (op, code))
        self.op = op
        self.code = code


class NoStorageError(MTPError):
    """The device shares no storage yet: a phone that is locked, or whose
    "Allow access to phone data?" prompt hasn't been answered."""


class ObjectInfo:
    """What GetObjectInfo says about one object.

    Android fills ``width`` and ``height`` with 256 and ``thumb_size`` with
    204800 for every picture, whatever its real size; read the image's own
    header when you need its size.
    """

    def __init__(self, handle, data):
        (self.storage, self.format, _prot, self.size, _thumb_fmt, self.thumb_size,
         _tw, _th, self.width, self.height, _depth, self.parent) = struct.unpack_from("<IHHIHIIIIIII", data, 0)
        self.handle = handle
        pos = 42 + 2 + 4 + 4   # association type and description, sequence number
        self.name, pos = _string(data, pos)
        self.captured, pos = _string(data, pos)
        self.modified, pos = _string(data, pos)

    @property
    def is_folder(self):
        return self.format == ASSOCIATION

    def __repr__(self):
        return "<ObjectInfo %r %d bytes>" % (self.name, self.size)


def _string(data, pos):
    """A PTP string (a count of UTF-16 units, the last a NUL) and where the next field starts."""
    if pos >= len(data):
        return "", pos
    n = data[pos]
    pos += 1
    if not n:
        return "", pos
    chars = []
    for i in range(n - 1):
        (u,) = struct.unpack_from("<H", data, pos + 2 * i)
        chars.append(chr(u))
    return "".join(chars), pos + 2 * n


def _array(data):
    (n,) = struct.unpack_from("<I", data, 0)
    return list(struct.unpack_from("<%dI" % n, data, 4))


def _find(dev):
    """(interface, bulk IN, bulk OUT, IN packet size), or None.

    PTP is interface class 6/1/1. Android's MTP mode is a vendor interface
    (FF/FF/00) with a bulk pair and an interrupt IN, which adb's (FF/42/01)
    isn't.
    """
    cfg = dev.configuration_descriptor()
    i, cur, ep_in, ep_out, ep_int, mps = cfg[0], None, None, None, None, 64
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            if cur is not None and ep_in and ep_out and ep_int:
                return cur, ep_in, ep_out, mps
            cls = (cfg[i + 5], cfg[i + 6], cfg[i + 7])
            ok = cfg[i + 3] == 0 and (cls == (6, 1, 1) or cls == (0xFF, 0xFF, 0))
            cur, ep_in, ep_out, ep_int = (cfg[i + 2] if ok else None), None, None, None
        elif cfg[i + 1] == 5 and cur is not None:
            kind = cfg[i + 3] & 3
            if kind == 2 and cfg[i + 2] & 0x80:
                ep_in, mps = cfg[i + 2], cfg[i + 4] | cfg[i + 5] << 8
            elif kind == 2:
                ep_out = cfg[i + 2]
            elif kind == 3 and cfg[i + 2] & 0x80:
                ep_int = cfg[i + 2]
        i += cfg[i]
    if cur is not None and ep_in and ep_out and ep_int:
        return cur, ep_in, ep_out, mps
    return None


class MTP:
    @staticmethod
    def match(dev):
        """For usb.core.find(custom_match=...): a phone in MTP or PTP mode, or a camera."""
        return _find(dev) is not None

    def __init__(self, dev, timeout=5000):
        found = _find(dev) if dev is not None else None
        if found is None:
            raise ValueError("not an MTP or PTP device")
        self.dev = dev
        self.timeout = timeout
        self._itf, self._in, self._out, self._mps = found
        self._tid = 0
        self._buf = bytearray(_CHUNK)
        self._session = False
        try:
            self._transaction(_OPEN_SESSION, (1,))
        except MTPError as e:
            if e.code != _SESSION_ALREADY_OPEN:
                raise
        self._session = True

    # -- transactions

    def _transaction(self, op, params=(), sink=None):
        """One command, its data phase if any, and the response.

        Returns the data as bytes, or, with ``sink(chunk)``, hands it over a
        piece at a time and returns how much there was. Raises MTPError on
        a response other than OK.
        """
        self._tid = (self._tid + 1) & 0xFFFFFFFF
        n = len(params)
        cmd = struct.pack("<IHHI%dI" % n, 12 + 4 * n, _COMMAND, op, self._tid, *params)
        self.dev.write(self._out, cmd, self.timeout)
        data = None if sink is not None else []
        total = 0
        while True:
            size = self._mps * (len(self._buf) // self._mps)
            got = self._read(self._buf, size)
            length, kind, code, _tid = struct.unpack_from("<IHHI", self._buf, 0)
            if kind == _RESPONSE:
                if code != _OK:
                    raise MTPError(op, code)
                break
            if kind != _DATA:
                raise OSError(5, "PTP container type %d" % kind)
            total = length - 12
            self._data_phase(memoryview(self._buf)[12:got], length, got, got == size, sink if sink else data.append)
        if sink is not None:
            return total
        return b"".join(data) if data else b""

    def _read(self, buf, size):
        mv = memoryview(buf)[:size]
        return self.dev.read(self._in, mv, self.timeout)

    def _data_phase(self, first, length, got, full, put):
        # ``full``: the last read filled its buffer, so the transfer hasn't
        # seen its end; a short or zero-length packet ends one early.
        if len(first):
            put(bytes(first))
        left = length - got
        while left > 0:
            # Ask for no more than what's left, rounded to whole packets, so the
            # transfer ends on its own and nothing of the response is taken.
            want = min(len(self._buf), (left + self._mps - 1) // self._mps * self._mps)
            n = self._read(self._buf, want)
            if n == 0:
                raise OSError(5, "PTP data phase ended early")
            put(bytes(memoryview(self._buf)[:min(n, left)]))
            left -= n
            full = n == want
        if full and length % self._mps == 0:
            # A data phase that fills its last packet ends with a zero-length
            # one, which no read has taken yet.
            self.dev.read(self._in, self._buf, 200, raise_on_timeout=False)

    # -- what's on it

    def device_info(self):
        """(manufacturer, model, version, serial) as the device states them."""
        d = self._transaction(_GET_DEVICE_INFO)
        pos = 8
        _ext, pos = _string(d, pos)
        pos += 2
        for _ in range(5):   # operations, events, properties, capture and playback formats
            (n,) = struct.unpack_from("<I", d, pos)
            pos += 4 + 2 * n
        out = []
        for _ in range(4):
            s, pos = _string(d, pos)
            out.append(s)
        return tuple(out)

    def storages(self):
        """The storage IDs: a phone's internal storage, an SD card."""
        return _array(self._transaction(_GET_STORAGE_IDS))

    def storage_info(self, storage):
        """(description, capacity bytes, free bytes)."""
        d = self._transaction(_GET_STORAGE_INFO, (storage,))
        cap_lo, cap_hi, free_lo, free_hi = struct.unpack_from("<IIII", d, 6)
        desc, _ = _string(d, 26)
        return desc, cap_hi << 32 | cap_lo, free_hi << 32 | free_lo

    def handles(self, storage=_ALL, format=0, parent=None):
        """Object handles: the top of each storage, or the folder ``parent``.

        ``format`` narrows to one object format (``JPEG``), where the device
        allows it. ``parent=0`` asks for every object at once, which some
        devices refuse or answer slowly.
        """
        if parent is None:
            parent = _ALL
        try:
            return _array(self._transaction(_GET_OBJECT_HANDLES, (storage, format, parent)))
        except MTPError as e:
            # Asked for every storage when there are none, Android answers
            # Invalid_StorageID.
            if e.code == _INVALID_STORAGE and storage == _ALL and not self.storages():
                raise NoStorageError(
                    _GET_OBJECT_HANDLES, _INVALID_STORAGE,
                    "no storage shared: unlock the phone and allow access to its data") from None
            raise

    def info(self, handle):
        """An :class:`ObjectInfo`: name, format, size, parent, dates, image size."""
        return ObjectInfo(handle, self._transaction(_GET_OBJECT_INFO, (handle,)))

    def walk(self, parent=None, storage=_ALL):
        """Every object under ``parent`` (the top by default), folders first,
        as ObjectInfo, one folder at a time."""
        folders = [parent]
        while folders:
            here = folders.pop()
            for handle in self.handles(storage, 0, here):
                info = self.info(handle)
                yield info
                if info.is_folder:
                    folders.append(handle)

    def find(self, *path, storage=_ALL):
        """The handle of a folder or file by its names from the top, as in
        ``find("DCIM", "Camera")``, or None."""
        parent = None
        for name in path:
            for handle in self.handles(storage, 0, parent):
                if self.info(handle).name == name:
                    parent = handle
                    break
            else:
                return None
        return parent

    def photos(self, folder=("DCIM", "Camera"), formats=IMAGES):
        """Handles of the pictures in a folder (a phone camera's by default)."""
        parent = self.find(*folder)
        if parent is None:
            return []
        return [h for h in self.handles(_ALL, 0, parent) if self.info(h).format in formats]

    # -- fetching

    def read(self, handle):
        """The whole object, as bytes. For a big one use get() or read_part()."""
        return self._transaction(_GET_OBJECT, (handle,))

    def read_part(self, handle, offset, size):
        """``size`` bytes from ``offset`` (32-bit offsets: the first 4 GB)."""
        return self._transaction(_GET_PARTIAL_OBJECT, (handle, offset, size))

    def thumb(self, handle):
        """The object's thumbnail, a small JPEG for a picture."""
        return self._transaction(_GET_THUMB, (handle,))

    def get(self, handle, dest):
        """Copy an object to a file (a path or anything with ``write``)
        without holding it in RAM. Returns the byte count."""
        if hasattr(dest, "write"):
            return self._transaction(_GET_OBJECT, (handle,), sink=dest.write)
        with open(dest, "wb") as f:
            return self._transaction(_GET_OBJECT, (handle,), sink=f.write)

    def close(self):
        if self._session:
            self._session = False
            try:
                self._transaction(_CLOSE_SESSION)
            except (OSError, usb.core.USBError):
                pass
