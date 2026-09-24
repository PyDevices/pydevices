"""Files over Bluetooth: CircuitPython's BLE file-transfer protocol, both sides.

CircuitPython boards serve this protocol from their supervisor
(``supervisor/shared/bluetooth/file_transfer.c``). This module lets a
MicroPython board serve it too, so one client reaches files on either
interpreter. The protocol is Adafruit's, documented with their client in
`Adafruit_CircuitPython_BLE_File_Transfer
<https://github.com/adafruit/Adafruit_CircuitPython_BLE_File_Transfer>`_:
service ``0xFEBB``, a version characteristic, and one transfer
characteristic that the client writes commands to and the board answers on
with notifications. It reads, writes (at an offset), deletes, makes
directories, lists them and moves, and the board paces every write with a
"free space" count so it never receives more than it can hold.

On the board, opt in from ``main.py`` (nothing starts it for you)::

    import bledev.filetransfer
    bledev.filetransfer.start(password="correct horse", name="rack")

It's served beside the REPL of :mod:`bledev.repl` by default (``console=False``
serves files alone), from interrupts, so it keeps working at the ``>>>``
prompt and while your program runs. From a laptop or another board::

    import bledev.filetransfer as ft
    files = await ft.connect(ble, "correct horse", name="rack")
    await files.write("/hello.txt", b"hi")
    print(await files.read("/hello.txt"), await files.listdir("/"))

**The lock.** CircuitPython protects the transfer characteristic with
pairing. bledev uses the REPL's password by default, the same way WebREPL
does: the service carries one more characteristic (``AUTH``), the client
writes the password to it, and until it's right every command is answered
with :data:`STATUS_LOCKED`. One attempt per connection; a wrong password is
hung up on. Logging in to the REPL over the same connection unlocks files
too. Without pairing the link isn't encrypted, so a sniffer nearby can capture
the password.

``start(pairing=...)`` adds pairing, as for :mod:`bledev.repl`: the transfer
and ``AUTH`` characteristics then refuse a host that hasn't paired, and with
a passkey the password can go (``password=False``). ``AUTH`` then reads 1
once the link is paired. A client connecting to a CircuitPython board finds
no ``AUTH`` characteristic, pairs ("just works", as CircuitPython asks) and
skips the password.

The protocol carries no checksum of its own beyond the link layer's CRC, so a
client that must be sure checks what landed (mpftp compares SHA-256).
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import struct

from . import (
    BLEError,
    BLETimeoutError,
    DisconnectedError,
    GattError,
    NEEDS_PAIRING,
    UnsupportedError,
    UUID,
    connect_and_set_up,
    wait_ms,
)

SERVICE = UUID(0xFEBB)
VERSION = UUID("adaf0100-4669-6c65-5472-616e73666572")
TRANSFER = UUID("adaf0200-4669-6c65-5472-616e73666572")
#: bledev's addition: write the password here. CircuitPython has no such
#: characteristic (it uses pairing), which is how a client tells them apart.
AUTH = UUID("adaf0300-4669-6c65-5472-616e73666572")

#: The protocol version this server speaks (CircuitPython 9 and 10 serve 4).
PROTOCOL_VERSION = 4

READ = 0x10
READ_DATA = 0x11
READ_PACING = 0x12
WRITE = 0x20
WRITE_PACING = 0x21
WRITE_DATA = 0x22
DELETE = 0x30
DELETE_STATUS = 0x31
MKDIR = 0x40
MKDIR_STATUS = 0x41
LISTDIR = 0x50
LISTDIR_ENTRY = 0x51
MOVE = 0x60
MOVE_STATUS = 0x61

STATUS_OK = 0x01
STATUS_ERROR = 0x02
STATUS_ERROR_NO_FILE = 0x03
STATUS_ERROR_PROTOCOL = 0x04
STATUS_ERROR_READONLY = 0x05
#: bledev only: nothing is served until the password is right.
STATUS_LOCKED = 0x80

FLAG_DIRECTORY = 0x01

# Every header, little-endian and packed. Reserved fields are sent as zero.
_READ = "<BBHII"  # command, 0, path length, offset, chunk size; path follows
_READ_DATA = "<BBHIII"  # command, status, 0, offset, total length, data size; data follows
_READ_PACING = "<BBHII"  # command, status, 0, offset, chunk size
_WRITE = "<BBHIQI"  # command, 0, path length, offset, time (ns), total length; path follows
_WRITE_PACING = "<BBHIQI"  # command, status, 0, offset, time (ns), free space
_WRITE_DATA = "<BBHII"  # command, status, 0, offset, data size; data follows
_PATH = "<BBH"  # DELETE and LISTDIR: command, 0, path length; path follows
_MKDIR = "<BBHIQ"  # command, 0, path length, 0, time (ns); path follows
_MKDIR_STATUS = "<BBHIQ"  # command, status, 0, 0, time (ns)
_ENTRY = "<BBHIIIQI"  # command, status, path length, number, count, flags, time, size; name follows
_MOVE = "<BBHH"  # command, 0, old length, new length; old, one spare byte, new follow
_STATUS = "<BB"  # DELETE_STATUS and MOVE_STATUS

#: The shape of each command's answer, so even a refusal is one a client can parse.
_ANSWER = {
    READ: (READ_DATA, _READ_DATA),
    READ_PACING: (READ_DATA, _READ_DATA),
    WRITE: (WRITE_PACING, _WRITE_PACING),
    WRITE_DATA: (WRITE_PACING, _WRITE_PACING),
    DELETE: (DELETE_STATUS, _STATUS),
    MKDIR: (MKDIR_STATUS, _MKDIR_STATUS),
    LISTDIR: (LISTDIR_ENTRY, _ENTRY),
    MOVE: (MOVE_STATUS, _STATUS),
}

#: How much a writing client may send before the board says "more": the free
#: space in each WRITE_PACING. CircuitPython offers one 512-byte sector at a
#: time; a bigger window means fewer round trips (see docs/bledev-internals.md).
WINDOW = 4096

#: The longest path the board accepts, in bytes (CircuitPython's is about 1 KB).
MAX_PATH = 256


class FileTransferError(BLEError):
    """The board answered with an error status (``.status``)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class AuthError(BLEError):
    """The board refused the password, or wants one and none was given."""


def _answer(command, status, *values):
    code, fmt = _ANSWER[command]
    fields = [code, status] + [0] * (len(struct.unpack(fmt, bytes(struct.calcsize(fmt)))) - 2)
    for i, value in enumerate(values):
        fields[2 + i] = value
    return struct.pack(fmt, *fields)


def _errno(e):
    return e.args[0] if e.args and isinstance(e.args[0], int) else getattr(e, "errno", None)


def _status_for(e):
    return STATUS_ERROR_READONLY if _errno(e) == 30 else STATUS_ERROR  # EROFS


def _epoch_offset():
    # os.stat() times count from the port's epoch, which is 2000 on some
    # MicroPython ports; the protocol counts from 1970.
    try:
        import time

        return -time.mktime((1970, 1, 1, 0, 0, 0, 0, 0))
    except Exception:
        return 0


_EPOCH = None


def _ns(seconds):
    global _EPOCH
    if _EPOCH is None:
        import sys

        _EPOCH = _epoch_offset() if sys.implementation.name == "micropython" else 0
    return (int(seconds) + _EPOCH) * 1000000000


class _Out:
    """One answer waiting to go out: a header, then maybe part of a file."""

    def __init__(self, head, f=None, pos=0, size=0, close=False):
        self.head = head
        self.f = f
        self.pos = pos
        self.size = size
        self.close = close


class FileServer:
    """The protocol, without a radio, so it runs and is tested anywhere.

    ``feed()`` takes what the client wrote to the transfer characteristic, in
    any split; ``packet(n)`` gives the next notification (at most ``n`` bytes,
    never spanning two answers, as CircuitPython's clients expect) and
    ``sent()`` says it went out. ``root`` is prepended to every path (tests
    serve a scratch directory); ``window`` is the free space offered per
    round trip.
    """

    def __init__(self, root="", window=WINDOW):
        self.root = root.rstrip("/")
        self.window = window
        self.authed = False
        self.changed = 0
        self._buf = bytearray()
        self._out = []
        self._pending = None
        self._expect = None
        self._file = None
        self._total = 0
        self._offset = 0
        self._time = 0
        self._path = None

    # -- the radio side

    def reset(self):
        """Forget the transfer in progress and everything queued (the connection
        closed). ``authed`` is the caller's to clear."""
        self._abort()
        for item in self._out:
            if item.close and item.f is not None:
                item.f.close()
        self._out = []
        self._pending = None
        self._buf = bytearray()

    def feed(self, data):
        self._buf.extend(data)
        while self._buf:
            used = self._step(self._buf)
            if not used:
                break
            self._buf = self._buf[used:]

    def has_output(self):
        return self._pending is not None or bool(self._out)

    def packet(self, size):
        """The next notification's payload (``None`` when nothing is waiting).

        The same bytes come back until :meth:`sent` is called, so a send that
        failed for want of buffers is simply retried.
        """
        if self._pending is not None:
            return self._pending
        while self._out:
            item = self._out[0]
            data = bytes(item.head[:size])
            item.head = item.head[len(data) :]
            room = size - len(data)
            if room and item.size:
                n = min(room, item.size)
                item.f.seek(item.pos)
                chunk = item.f.read(n)
                if not chunk:
                    item.size = 0  # the file got shorter; the client will notice
                else:
                    data += chunk
                    item.pos += len(chunk)
                    item.size -= len(chunk)
            if not item.head and not item.size:
                self._out.pop(0)
                if item.close and item.f is not None:
                    item.f.close()
            if data:
                self._pending = data
                return data
        return None

    def sent(self):
        self._pending = None

    # -- the protocol

    def _path_at(self, buf, start, length):
        path = bytes(buf[start : start + length]).decode()
        return self.root + path

    def _send(self, head, f=None, pos=0, size=0, close=False):
        self._out.append(_Out(head, f, pos, size, close))

    def _abort(self):
        f = self._file
        if f is not None:
            # A read's chunk may still be going out; let it close the file.
            for item in self._out:
                if item.f is f:
                    item.close = True
                    break
            else:
                try:
                    f.close()
                except OSError:
                    pass
        self._file = None
        self._expect = None

    def _step(self, buf):
        """Handle the command at the head of ``buf``; return the bytes used, 0 if incomplete."""
        command = buf[0]
        if command not in _ANSWER:
            self._abort()
            return len(buf)  # nothing to resynchronise on; drop what's buffered
        need = self._needed(command, buf)
        if need is None:
            return 0
        if need < 0:
            # A length no answer could fit (over MAX_PATH, or more data than
            # the window offered): refuse it and drop the stream.
            self._send(_answer(command, STATUS_ERROR_PROTOCOL))
            self._abort()
            return len(buf)
        if len(buf) < need:
            return 0
        if not self.authed:
            self._send(_answer(command, STATUS_LOCKED))
            return need
        if command & 0x0F:
            if command != self._expect:
                # A continuation of a transfer that isn't running.
                self._send(_answer(command, STATUS_ERROR_PROTOCOL))
                self._abort()
                return need
        else:
            self._abort()  # a new command abandons a transfer in progress
        getattr(self, "_do_{:02x}".format(command))(buf)
        return need

    def _needed(self, command, buf):
        fixed = {
            READ: 12,
            READ_PACING: 12,
            WRITE: 20,
            WRITE_DATA: 12,
            DELETE: 4,
            MKDIR: 16,
            LISTDIR: 4,
            MOVE: 6,
        }[command]
        if len(buf) < fixed:
            return None
        if command in (READ, WRITE, DELETE, LISTDIR, MKDIR):
            extra = struct.unpack_from("<H", buf, 2)[0]
            limit = MAX_PATH
        elif command == WRITE_DATA:
            extra = struct.unpack_from("<I", buf, 8)[0]
            limit = self.window
        elif command == MOVE:
            old, new = struct.unpack_from("<HH", buf, 2)
            extra = old + 1 + new
            limit = 2 * MAX_PATH + 1
        else:
            return fixed
        return fixed + extra if extra <= limit else -1

    # READ
    def _do_10(self, buf):
        _, _, length, offset, chunk = struct.unpack_from(_READ, buf)
        path = self._path_at(buf, 12, length)
        try:
            import os

            if os.stat(path)[0] & 0x4000:
                raise OSError(21)
            f = open(path, "rb")
            total = os.stat(path)[6]
        except OSError:
            self._send(_answer(READ, STATUS_ERROR))
            return
        self._file = f
        self._total = total
        self._read_chunk(offset, chunk)

    # READ_PACING
    def _do_12(self, buf):
        _, _, _, offset, chunk = struct.unpack_from(_READ_PACING, buf)
        self._read_chunk(offset, chunk)

    def _read_chunk(self, offset, chunk):
        total = self._total
        offset = min(offset, total)
        size = min(chunk, total - offset)
        last = offset + size >= total
        head = struct.pack(_READ_DATA, READ_DATA, STATUS_OK, 0, offset, total, size)
        self._send(head, self._file, offset, size, close=last)
        if last:
            self._file = None
            self._expect = None
        else:
            self._expect = READ_PACING

    # WRITE
    def _do_20(self, buf):
        _, _, length, offset, when, total = struct.unpack_from(_WRITE, buf)
        path = self._path_at(buf, 20, length)
        import os

        try:
            try:
                size = os.stat(path)[6]
            except OSError:
                size = -1
            if offset == 0 or size < 0:
                f = open(path, "wb")
                size = 0
            else:
                f = open(path, "r+b")
            if offset > size:
                f.seek(size)
                gap = offset - size
                while gap:
                    n = min(gap, 512)
                    f.write(bytes(n))
                    gap -= n
        except OSError as e:
            self._send(_answer(WRITE, _status_for(e)))
            return
        self._file = f
        self._path = path
        self._total = total
        self._time = when
        self._offset = offset
        self._expect = WRITE_DATA
        self._pace(offset)

    # WRITE_DATA
    def _do_22(self, buf):
        _, status, _, offset, size = struct.unpack_from(_WRITE_DATA, buf)
        f = self._file
        if status != STATUS_OK or offset != self._offset or size > self.window or offset + size > self._total:
            self._send(_answer(WRITE_DATA, STATUS_ERROR_PROTOCOL if status == STATUS_OK else STATUS_ERROR))
            self._abort()
            return
        try:
            f.seek(offset)
            f.write(memoryview(buf)[12 : 12 + size])
        except OSError as e:
            self._send(_answer(WRITE_DATA, _status_for(e)))
            self._abort()
            return
        self._offset = offset + size
        self._pace(self._offset)

    def _pace(self, offset):
        free = min(self._total - offset, self.window)
        when = self._time
        if not free:
            try:
                self._finish_write()
                when = self._stored_time()
            except OSError as e:
                self._send(_answer(WRITE_DATA, _status_for(e)))
                self._abort()
                return
        self._send(struct.pack(_WRITE_PACING, WRITE_PACING, STATUS_OK, 0, offset, when, free))

    def _finish_write(self):
        import os

        f, self._file, self._expect = self._file, None, None
        f.close()
        self.changed += 1
        if os.stat(self._path)[6] > self._total:
            _truncate(self._path, self._total)

    def _stored_time(self):
        import os

        try:
            return _ns(os.stat(self._path)[8])
        except OSError:
            return self._time

    # DELETE
    def _do_30(self, buf):
        length = struct.unpack_from(_PATH, buf)[2]
        path = self._path_at(buf, 4, length).rstrip("/") or "/"
        try:
            _remove(path)
            status = STATUS_OK
            self.changed += 1
        except OSError as e:
            status = _status_for(e)
        self._send(struct.pack(_STATUS, DELETE_STATUS, status))

    # MKDIR
    def _do_40(self, buf):
        _, _, length, _, when = struct.unpack_from(_MKDIR, buf)
        path = self._path_at(buf, 16, length).rstrip("/")
        import os

        status = STATUS_OK
        try:
            _makedirs(path)
            when = _ns(os.stat(path)[8])
            self.changed += 1
        except OSError as e:
            status = _status_for(e)
        self._send(struct.pack(_MKDIR_STATUS, MKDIR_STATUS, status, 0, 0, when))

    # LISTDIR
    def _do_50(self, buf):
        import os

        length = struct.unpack_from(_PATH, buf)[2]
        path = self._path_at(buf, 4, length).rstrip("/") or "/"
        try:
            if not os.stat(path)[0] & 0x4000:
                raise OSError(20)
            names = sorted(os.listdir(path))
        except OSError:
            self._send(_answer(LISTDIR, STATUS_ERROR_NO_FILE))
            return
        count = len(names)
        prefix = path if path.endswith("/") else path + "/"
        for i, name in enumerate(names):
            try:
                st = os.stat(prefix + name)
            except OSError:
                st = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            directory = bool(st[0] & 0x4000)
            raw = name.encode()
            head = struct.pack(
                _ENTRY,
                LISTDIR_ENTRY,
                STATUS_OK,
                len(raw),
                i,
                count,
                FLAG_DIRECTORY if directory else 0,
                _ns(st[8]),
                0 if directory else st[6],
            )
            # One answer per entry: CircuitPython's own client expects an
            # entry's header to start a notification.
            self._send(head + raw)
        self._send(struct.pack(_ENTRY, LISTDIR_ENTRY, STATUS_OK, 0, count, count, 0, 0, 0))

    # MOVE
    def _do_60(self, buf):
        import os

        _, _, old, new = struct.unpack_from(_MOVE, buf)
        src = self._path_at(buf, 6, old)
        dst = self._path_at(buf, 6 + old + 1, new)
        try:
            os.rename(src, dst)
            status = STATUS_OK
            self.changed += 1
        except OSError as e:
            status = _status_for(e)
        self._send(struct.pack(_STATUS, MOVE_STATUS, status))


def _remove(path):
    import os

    if os.stat(path)[0] & 0x4000:
        prefix = path if path.endswith("/") else path + "/"
        for name in os.listdir(path):
            _remove(prefix + name)
        os.rmdir(path)
    else:
        os.remove(path)


def _makedirs(path):
    import os

    try:
        mode = os.stat(path)[0]
    except OSError:
        parent = path[: path.rfind("/")]
        if parent:
            _makedirs(parent)
        os.mkdir(path)
        return
    if not mode & 0x4000:
        raise OSError(17)  # a file is in the way


def _truncate(path, size):
    # MicroPython's files can't truncate, so copy the part that stays.
    import os

    tmp = path + ".bledev-tmp"
    with open(path, "rb") as src, open(tmp, "wb") as dst:
        left = size
        while left:
            chunk = src.read(min(left, 1024))
            if not chunk:
                break
            dst.write(chunk)
            left -= len(chunk)
    os.remove(path)
    os.rename(tmp, path)


# ---------------------------------------------------------------- the board side


def start(password=None, name="mpy-files", *, console=True, window=WINDOW, **options):
    """Serve files (and, unless ``console=False``, the REPL) over BLE. MicroPython only.

    The radio, the password and the advertising are :mod:`bledev.repl`'s;
    this is ``bledev.repl.start(..., files=True)``. Returns at once;
    :func:`stop` or ``bledev.repl.stop()`` ends it.
    """
    from . import repl

    return repl.start(password, name, files=True, console=console, window=window, **options)


def stop():
    from . import repl

    repl.stop()


# ---------------------------------------------------------------- the client side


class Client:
    """A connection to a board's file service. Made by :func:`connect`.

    Paths are absolute (``/lib/x.py``). Every method raises
    :class:`FileTransferError` when the board answers with an error, and
    :class:`DisconnectedError` if the link drops.
    """

    def __init__(self, connection, transfer, version, *, chunk=WINDOW):
        self.connection = connection
        self.version = version
        self.chunk = chunk
        #: How long to wait for each part of an answer.
        self.timeout_ms = 10000
        self._transfer = transfer
        self._buf = bytearray()
        self._event = asyncio.Event()
        self._closed = False
        self._no_response = bool(transfer.properties & 0x0004) if transfer is not None else True
        self._pump = asyncio.create_task(self._receive()) if transfer is not None else None
        self.bytes_in = 0
        self.bytes_out = 0

    async def _receive(self):
        try:
            while True:
                self._feed(await self._transfer.notified())
        except DisconnectedError:
            pass
        finally:
            self._closed = True
            self._event.set()

    def _feed(self, data):
        self._buf.extend(data)
        self.bytes_in += len(data)
        self._event.set()

    async def _send(self, data):
        size = max(1, self.connection.mtu - 3)
        for i in range(0, len(data), size):
            if not self.connection.is_connected():
                raise DisconnectedError("the board hung up")
            await self._transfer.write(data[i : i + size], response=not self._no_response)
        self.bytes_out += len(data)

    async def _recv(self, n):
        while len(self._buf) < n:
            if self._closed:
                raise DisconnectedError("the board hung up mid-answer")
            self._event.clear()
            await wait_ms(self._event.wait(), self.timeout_ms, "the board's answer")
        data = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return data

    async def _header(self, fmt, code):
        data = await self._recv(struct.calcsize(fmt))
        fields = struct.unpack(fmt, data)
        if fields[0] != code:
            raise FileTransferError(STATUS_ERROR_PROTOCOL, "expected answer 0x{:02x}, got 0x{:02x}".format(code, fields[0]))
        return fields

    @staticmethod
    def _check(status, what):
        if status == STATUS_OK:
            return
        if status == STATUS_LOCKED:
            raise AuthError("{}: the board wants the password first".format(what))
        text = {
            STATUS_ERROR_NO_FILE: "no such file or directory",
            STATUS_ERROR_PROTOCOL: "protocol error",
            STATUS_ERROR_READONLY: "the filesystem is read-only",
        }.get(status, "failed")
        raise FileTransferError(status, "{}: {} (status 0x{:02x})".format(what, text, status))

    async def read(self, path, offset=0):
        """The file's contents from ``offset`` on."""
        raw = path.encode()
        chunk = self.chunk
        await self._send(struct.pack(_READ, READ, 0, len(raw), offset, chunk) + raw)
        out = bytearray()
        while True:
            _, status, _, at, total, size = await self._header(_READ_DATA, READ_DATA)
            self._check(status, "read " + path)
            out.extend(await self._recv(size))
            at += size
            if at >= total or not size:
                return bytes(out)
            await self._send(struct.pack(_READ_PACING, READ_PACING, STATUS_OK, 0, at, min(chunk, total - at)))

    async def write(self, path, data, offset=0, modification_time=None):
        """Write ``data`` at ``offset`` (the file ends after it). Returns the stored time in ns."""
        raw = path.encode()
        data = memoryview(bytes(data))
        total = offset + len(data)
        if modification_time is None:
            modification_time = _now_ns()
        await self._send(struct.pack(_WRITE, WRITE, 0, len(raw), offset, modification_time, total) + raw)
        while True:
            _, status, _, at, when, free = await self._header(_WRITE_PACING, WRITE_PACING)
            self._check(status, "write " + path)
            if at < offset or at > total:
                raise FileTransferError(STATUS_ERROR_PROTOCOL, "write {}: the board asked for offset {}".format(path, at))
            if not free:
                if at != total:
                    raise FileTransferError(STATUS_ERROR_PROTOCOL, "write {}: stopped at {} of {}".format(path, at, total))
                return when
            n = min(free, total - at)
            start = at - offset
            await self._send(struct.pack(_WRITE_DATA, WRITE_DATA, STATUS_OK, 0, at, n) + bytes(data[start : start + n]))

    async def delete(self, path):
        """Delete a file, or a directory and everything in it."""
        raw = path.encode()
        await self._send(struct.pack(_PATH, DELETE, 0, len(raw)) + raw)
        _, status = await self._header(_STATUS, DELETE_STATUS)
        self._check(status, "delete " + path)

    async def mkdir(self, path, modification_time=None):
        """Make a directory and any missing parents. Returns the stored time in ns."""
        raw = path.encode()
        if modification_time is None:
            modification_time = _now_ns()
        await self._send(struct.pack(_MKDIR, MKDIR, 0, len(raw), 0, modification_time) + raw)
        _, status, _, _, when = await self._header(_MKDIR_STATUS, MKDIR_STATUS)
        self._check(status, "mkdir " + path)
        return when

    async def listdir(self, path):
        """``[(name, size, is_directory, modification_time_ns), ...]``."""
        raw = path.encode()
        await self._send(struct.pack(_PATH, LISTDIR, 0, len(raw)) + raw)
        entries = []
        while True:
            _, status, length, number, count, flags, when, size = await self._header(_ENTRY, LISTDIR_ENTRY)
            self._check(status, "listdir " + path)
            if number >= count:
                return entries
            name = (await self._recv(length)).decode()
            entries.append((name, size, bool(flags & FLAG_DIRECTORY), when))

    async def move(self, old, new):
        """Rename or move a file or directory (protocol version 4)."""
        if self.version is not None and self.version < 4:
            raise UnsupportedError("move needs protocol version 4; the board has {}".format(self.version))
        a = old.encode()
        b = new.encode()
        await self._send(struct.pack(_MOVE, MOVE, 0, len(a), len(b)) + a + b" " + b)
        _, status = await self._header(_STATUS, MOVE_STATUS)
        self._check(status, "move {} to {}".format(old, new))

    async def close(self):
        if self.connection is not None and self.connection.is_connected():
            await self.connection.disconnect()
        self._closed = True
        self._event.set()


def _now_ns():
    import time

    try:
        return time.time_ns()
    except AttributeError:
        return _ns(time.time())


async def connect(ble, password=None, name=None, *, device=None, timeout_ms=10000, mtu=247, pair=None, passkey=None, **connect_options):
    """Find a board serving files (by ``name``, or the first advertising the
    service), connect, log in, and return a :class:`Client`.

    ``password`` is needed for a bledev board locked by one, and ignored by
    a CircuitPython board, which uses pairing instead.

    ``pair``: ``True`` pairs first; ``None`` (the default) pairs when the
    board asks for it, which a CircuitPython board always does and a bledev
    board started with ``pairing=`` does; ``False`` never pairs. ``passkey``
    is what the board's display shows, or a callable that asks for it.
    """
    from . import nus

    ble = nus._adapter(ble)
    nus._set_mtu(ble, mtu)

    async def setup(connection):
        try:
            await connection.exchange_mtu(mtu)
        except (UnsupportedError, BLETimeoutError):
            pass
        service = await connection.service(SERVICE)
        if service is None:
            raise BLEError("{!r} has no file transfer service".format(connection.device))
        transfer = await service.characteristic(TRANSFER)
        if transfer is None:
            raise BLEError("{!r}: the file transfer service has no transfer characteristic".format(connection.device))
        version = None
        char = await service.characteristic(VERSION)
        if char is not None:
            try:
                version = struct.unpack("<I", (await char.read())[:4])[0]
            except (BLEError, ValueError):
                pass
        auth = await service.characteristic(AUTH)
        # Does the board want pairing? CircuitPython (no AUTH) always does. A
        # bledev board with pairing on refuses to let AUTH be read.
        locked = None
        wants = auth is None
        if auth is not None:
            try:
                locked = (await auth.read())[:1] != b"\x01"
            except GattError as e:
                if e.status not in NEEDS_PAIRING:
                    raise
                wants = True
        return transfer, version, auth, wants, locked

    connection, (transfer, version, auth, wants, locked) = await connect_and_set_up(
        ble, setup, name=name, service=SERVICE, device=device, timeout_ms=timeout_ms, pair=pair is True, passkey=passkey, **connect_options
    )
    try:
        if wants and pair is None and not connection.encrypted:
            await connection.pair(passkey=passkey)
        try:
            await transfer.subscribe(notify=True)
            if auth is not None and (locked is None or wants):
                locked = (await auth.read())[:1] != b"\x01"
                if locked and password is None and connection.encrypted:
                    # The board unlocks on its own encryption event, which
                    # can land a moment after this side's pair() returned.
                    for _ in range(10):
                        await asyncio.sleep(0.05)
                        locked = (await auth.read())[:1] != b"\x01"
                        if not locked:
                            break
        except GattError as e:
            if e.status not in NEEDS_PAIRING:
                raise
            from .repl import refused

            raise refused(pair is not False, passkey)
    except BaseException:
        if connection.is_connected():
            await connection.disconnect()
        raise
    client = Client(connection, transfer, version)
    if auth is not None and locked:
        try:
            if password is None:
                raise AuthError("the board wants a password")
            secret = password.encode() if isinstance(password, str) else bytes(password)
            await auth.write(secret, response=True)
            if (await auth.read())[:1] != b"\x01":
                raise AuthError("the board refused the password")
        except BaseException:
            await client.close()
            raise
    return client
