"""TCP transport: one frame per line, and a browser on the same port.

A device::

    from hmilink import tcp
    device.add(tcp.serve(9000, page="index.html"))

A panel in Python::

    panel = hmilink.Panel(tcp.connect("192.168.1.42", 9000))

A panel in a browser opens ``http://192.168.1.42:9000/`` and gets the page,
and the page opens ``ws://192.168.1.42:9000/ws``. The port decides per
connection from its first bytes: a line that starts with ``GET`` is HTTP,
upgraded to WebSocket when it asks (one text frame per message); anything
else is newline-delimited frames. Neither the device nor the panel knows
which it got.

Frames are bytes with no newline in them, which JSON never has.

Nothing blocks: a listener's ``accept()`` and a link's ``recv()`` return
``None`` when nothing is waiting, and ``send()`` queues what the socket
won't take yet, to go out on the next ``flush()`` or ``poll()``.

Runs on MicroPython and CPython with ``socket``. On CircuitPython pass
``pool=socketpool.SocketPool(wifi.radio)`` (untested: the desktop build has
no sockets).
"""

import binascii
import hashlib

try:
    import socket as _socket
except ImportError:
    _socket = None

# What a non-blocking socket raises when nothing is waiting: EAGAIN,
# EINPROGRESS, BSD's EWOULDBLOCK, Windows' WSAEWOULDBLOCK and WSAEINPROGRESS.
_AGAIN = (11, 115, 35, 10035, 10036)

_WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_RECV = 1024
_MAX_HEADER = 4096


def _again(e):
    return bool(e.args) and e.args[0] in _AGAIN


def _sha1(data):
    try:
        return hashlib.sha1(data).digest()
    except AttributeError:
        return hashlib.new("sha1", data).digest()


def ws_frame(payload, opcode=1):
    """A server-to-client WebSocket frame (unmasked) around ``payload``."""
    n = len(payload)
    if n < 126:
        head = bytes((0x80 | opcode, n))
    elif n < 65536:
        head = bytes((0x80 | opcode, 126, n >> 8, n & 0xFF))
    else:
        head = bytes((0x80 | opcode, 127)) + n.to_bytes(8, "big")
    return head + payload


class Link:
    """One connection. Made by a listener's ``accept()`` or by ``connect()``."""

    def __init__(self, sock, page=None):
        sock.setblocking(False)
        try:
            # Every frame is small and wanted now: no Nagle. IPPROTO_TCP is 6
            # and TCP_NODELAY is 1 on Linux, Windows, lwIP and macOS.
            sock.setsockopt(6, 1, 1)
        except (OSError, AttributeError):
            pass
        self.sock = sock
        self.page = page
        self.closed = False
        self.hmi_id = 0
        self._in = b""
        self._out = b""
        self.ws = None  # None until the first line says; then False (lines) or True
        self._held = []  # frames to send once the first line has said which framing
        self._close_after_flush = False

    # -- out --

    def busy(self):
        """True while something is still queued to send."""
        return len(self._out) > 0 or len(self._held) > 0

    def send(self, frame):
        """Queue one frame and try to send it now."""
        if self.closed:
            return
        if self.ws is None:
            self._held.append(frame)
            return
        if self.ws:
            self._out += ws_frame(frame)
        else:
            self._out += frame + b"\n"
        self.flush()

    def _decided(self, ws):
        self.ws = ws
        held, self._held = self._held, []
        for frame in held:
            self.send(frame)

    def flush(self):
        """Send what the socket will take. Call it from the poll loop."""
        while self._out and not self.closed:
            try:
                n = self.sock.send(self._out)
            except OSError as e:
                if _again(e):
                    return
                self.close()
                return
            if not n:
                return
            self._out = self._out[n:]
        if self._close_after_flush and not self._out:
            self.close()

    # -- in --

    def _fill(self):
        try:
            data = self.sock.recv(_RECV)
        except OSError as e:
            if _again(e):
                return False
            self.close()
            return False
        if not data:
            self.close()
            return False
        self._in += data
        return True

    def recv(self):
        """One frame, or None when none is complete yet."""
        while not self.closed:
            frame = self._parse()
            if frame is not None:
                if frame == b"":
                    continue
                return frame
            if not self._fill():
                return None
        return None

    def _parse(self):
        buf = self._in
        if self.ws is None:
            i = buf.find(b"\n")
            if i < 0:
                if len(buf) > _MAX_HEADER:
                    self.close()
                return None
            if buf[:4] == b"GET ":
                return self._http()
            self._decided(False)
        if self.ws is False:
            i = buf.find(b"\n")
            if i < 0:
                return None
            frame = buf[:i]
            self._in = buf[i + 1 :]
            if frame.endswith(b"\r"):
                frame = frame[:-1]
            return frame
        return self._ws_parse()

    # -- HTTP and WebSocket --

    def _http(self):
        buf = self._in
        end = buf.find(b"\r\n\r\n")
        if end < 0:
            if len(buf) > _MAX_HEADER:
                self.close()
            return None
        head = buf[:end].decode()
        self._in = buf[end + 4 :]
        lines = head.split("\r\n")
        target = lines[0].split(" ")[1] if " " in lines[0] else "/"
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key")
        if key and "websocket" in headers.get("upgrade", "").lower():
            accept = binascii.b2a_base64(_sha1(key.encode() + _WS_GUID)).strip()
            self._out += (
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
            )
            self._decided(True)
            self.flush()
            return b""
        body = self._page_bytes() if target.split("?")[0] in ("/", "/index.html") else None
        if body is None:
            self._out += b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        else:
            self._out += (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                b"Cache-Control: no-cache\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
        self._close_after_flush = True
        self.flush()
        return None

    def _page_bytes(self):
        page = self.page
        if page is None:
            return None
        if callable(page):
            page = page()
        if isinstance(page, str):
            with open(page, "rb") as f:
                return f.read()
        return page

    def _ws_parse(self):
        buf = self._in
        if len(buf) < 2:
            return None
        opcode = buf[0] & 0x0F
        masked = buf[1] & 0x80
        n = buf[1] & 0x7F
        pos = 2
        if n == 126:
            if len(buf) < 4:
                return None
            n = (buf[2] << 8) | buf[3]
            pos = 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n = int.from_bytes(buf[2:10], "big")
            pos = 10
        if masked:
            if len(buf) < pos + 4:
                return None
            mask = buf[pos : pos + 4]
            pos += 4
        if len(buf) < pos + n:
            return None
        payload = bytearray(buf[pos : pos + n])
        self._in = buf[pos + n :]
        if masked:
            for i in range(n):
                payload[i] ^= mask[i & 3]
        if opcode in (1, 2):
            return bytes(payload)
        if opcode == 8:
            self._out += ws_frame(b"", 8)
            self._close_after_flush = True
            self.flush()
            return None
        if opcode == 9:
            self._out += ws_frame(bytes(payload), 10)
            self.flush()
        return b""

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass


class Listener:
    """A listening port. ``accept()`` returns a Link or None, never blocks."""

    def __init__(self, port, bind="0.0.0.0", page=None, backlog=4, pool=None):
        self.page = page
        mod = pool or _socket
        if mod is None:
            raise ImportError("no socket module; pass pool=socketpool.SocketPool(wifi.radio)")
        s = mod.socket()
        try:
            s.setsockopt(mod.SOL_SOCKET, mod.SO_REUSEADDR, 1)
        except (OSError, AttributeError):
            pass
        s.bind(mod.getaddrinfo(bind, port)[0][-1])
        s.listen(backlog)
        s.setblocking(False)
        self.sock = s
        self.port = port

    def accept(self):
        try:
            client, _addr = self.sock.accept()
        except OSError as e:
            if _again(e):
                return None
            raise
        return Link(client, page=self.page)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def serve(port, bind="0.0.0.0", page=None, pool=None):
    """Listen on ``port``. ``page`` (bytes, a path or a callable) answers ``GET /``."""
    return Listener(port, bind=bind, page=page, pool=pool)


def connect(host, port, pool=None):
    """A link to a device, as a panel. Blocks while connecting."""
    mod = pool or _socket
    if mod is None:
        raise ImportError("no socket module; pass pool=socketpool.SocketPool(wifi.radio)")
    s = mod.socket()
    s.connect(mod.getaddrinfo(host, port)[0][-1])
    link = Link(s)
    link._decided(False)  # a panel's own link speaks lines from the start
    return link
