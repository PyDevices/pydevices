"""OSC transport: a control app on a phone or a laptop drives the document.

Apps that speak Open Sound Control (TouchOSC, Open Stage Control, the many
free OSC controller apps for phones) send UDP datagrams such as
``/synth/cutoff ,f 0.5``. Add an OSC port to a device and each message
becomes a ``replace`` op on the path it names, applied by the model like
any panel's op::

    from hmilink import osc
    device.add(osc.serve(8000))

An app whose controls have addresses of their own maps them onto the
document with ``routes``; an address with no route is used as the path
as it is::

    device.add(osc.serve(8000, routes={"/1/fader1": "/synth/cutoff"}))

What a message turns into:

- one argument: ``replace`` at the path with that value;
- several arguments: ``replace`` with a list of them (an XY pad's ``x y``);
- an address under ``/cmd/``: the command named by the rest, with
  ``{"args": [...]}`` (``/cmd/save`` runs the model's ``save``);
- no argument at all: ignored, as is anything that doesn't parse.

Back to the app: every op the device accepts goes out as an OSC message,
at the app's own address when a route names one, to every app that has
sent here (so a fader moved on another panel moves on the phone too). The
app whose op it was doesn't get its own echo back, so a fader under a
finger doesn't fight it. Telemetry goes out as ``/tele/<key>`` messages,
numbers, strings and booleans only. Replies go to the address and port a
message came from; an app that listens on a port of its own takes
``reply_port``, and ``peers`` names apps to send to before they've sent
anything.

Bundles are read element by element, with their time tags ignored.
Argument types read are ``i f s S b T F N I h d``; ints, floats, strings,
booleans and ``None`` are written as ``i f s T F N``.

Runs on MicroPython and CPython with ``socket``. On CircuitPython pass
``pool=socketpool.SocketPool(wifi.radio)``. Nothing blocks: ``recv()``
returns ``None`` when no datagram is waiting.
"""

import json
import struct

try:
    import socket as _socket
except ImportError:
    _socket = None

# What a non-blocking socket raises when nothing is waiting (see tcp).
_AGAIN = (11, 115, 35, 10035, 10036)

# MicroPython's struct raises ValueError and has no struct.error.
_StructError = getattr(struct, "error", ValueError)

_MAX_DATAGRAM = 1536
_MAX_PEERS = 4
_CMD = "/cmd/"


# -- the codec ---------------------------------------------------------------


def _pad(n):
    return (n + 4) & ~3


def _read_string(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end].decode(), _pad(end)


def _string(text):
    raw = text.encode() if isinstance(text, str) else bytes(text)
    return raw + b"\x00" * (_pad(len(raw)) - len(raw))


def _unpack(fmt, data, pos, size):
    # MicroPython's struct reads past a short buffer's end without a word.
    if pos + size > len(data):
        raise ValueError("message ends inside an argument")
    return struct.unpack(fmt, data[pos : pos + size])[0]


def decode(data):
    """The messages in one datagram, as ``(address, [args])`` pairs.

    A bundle gives every message in it, nested bundles included. Raises
    ``ValueError`` on anything that isn't OSC.
    """
    out = []
    try:
        _decode(bytes(data), out)
    except (IndexError, _StructError):
        raise ValueError("message ends inside an argument")
    return out


def _decode(data, out):
    if data[:8] == b"#bundle\x00":
        pos = 16  # the tag and the 8-byte time tag
        while pos + 4 <= len(data):
            (size,) = struct.unpack(">i", data[pos : pos + 4])
            pos += 4
            if size < 0 or pos + size > len(data):
                raise ValueError("bad bundle element size")
            _decode(data[pos : pos + size], out)
            pos += size
        return
    try:
        address, pos = _read_string(data, 0)
    except (ValueError, UnicodeError):
        raise ValueError("no address")
    if not address.startswith("/"):
        raise ValueError("not an OSC address: %r" % address)
    args = []
    if pos >= len(data):  # old senders leave the type tags out of an empty message
        out.append((address, args))
        return
    tags, pos = _read_string(data, pos)
    if not tags.startswith(","):
        raise ValueError("no type tags")
    for tag in tags[1:]:
        if tag == "i":
            args.append(_unpack(">i", data, pos, 4))
            pos += 4
        elif tag == "f":
            args.append(_unpack(">f", data, pos, 4))
            pos += 4
        elif tag in "sS":
            value, pos = _read_string(data, pos)
            args.append(value)
        elif tag == "b":
            (size,) = struct.unpack(">i", data[pos : pos + 4])
            args.append(data[pos + 4 : pos + 4 + size])
            pos += 4 + ((size + 3) & ~3)
        elif tag == "h":
            args.append(_unpack(">q", data, pos, 8))
            pos += 8
        elif tag == "d":
            args.append(_unpack(">d", data, pos, 8))
            pos += 8
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag == "N":
            args.append(None)
        elif tag == "I":
            args.append(float("inf"))
        else:
            raise ValueError("OSC type %r isn't read" % tag)
        if pos > len(data):
            raise ValueError("message ends inside an argument")
    out.append((address, args))


def encode(address, args=()):
    """One OSC message: ``address`` and a list of ints, floats, strings, bools or None."""
    tags = ","
    body = b""
    for value in args:
        if value is True:
            tags += "T"
        elif value is False:
            tags += "F"
        elif value is None:
            tags += "N"
        elif isinstance(value, int):
            tags += "i"
            body += struct.pack(">i", value)
        elif isinstance(value, float):
            tags += "f"
            body += struct.pack(">f", value)
        elif isinstance(value, str):
            tags += "s"
            body += _string(value)
        else:
            raise TypeError("OSC can't carry %r" % (value,))
    return _string(address) + _string(tags) + body


def _plain(value):
    """``value`` as a list of OSC arguments, or None when OSC can't carry it."""
    if isinstance(value, (list, tuple)):
        flat = []
        for item in value:
            if isinstance(item, (list, tuple, dict)):
                return None
            flat.append(item)
        return flat
    if value is None or isinstance(value, (bool, int, float, str)):
        return [value]
    return None


# -- the link ----------------------------------------------------------------


class Link:
    """One UDP port, as one link: every app that sends to it shares it."""

    def __init__(self, port, bind="0.0.0.0", routes=None, reply_port=None, peers=(), pool=None):
        mod = pool or _socket
        if mod is None:
            raise ImportError("no socket module; pass pool=socketpool.SocketPool(wifi.radio)")
        self._mod = mod
        s = mod.socket(mod.AF_INET, mod.SOCK_DGRAM)
        try:
            s.setsockopt(mod.SOL_SOCKET, mod.SO_REUSEADDR, 1)
        except (OSError, AttributeError):
            pass
        s.bind(mod.getaddrinfo(bind, port)[0][-1])
        s.setblocking(False)
        self.sock = s
        self.port = port
        self.routes = dict(routes or {})
        self._back = {}
        for app, path in self.routes.items():
            self._back[path] = app
        self.reply_port = reply_port
        self.closed = False
        self.hmi_id = 0
        #: The apps replies go to, newest last, as ``(ip, port)``.
        self.peers = [self._addr(p) for p in peers]
        #: Counters: datagrams in, messages turned into frames, ones that didn't parse.
        self.stats = {"datagrams": 0, "messages": 0, "bad": 0, "sent": 0}
        self._frames = []
        self._origin = {}
        self._buf = bytearray(_MAX_DATAGRAM)
        self._resolved = {}

    def _addr(self, addr):
        if isinstance(addr, (bytes, bytearray)):
            # MicroPython's unix port hands back a raw sockaddr_in.
            ip = "%d.%d.%d.%d" % tuple(addr[4:8])
            port = (addr[2] << 8) | addr[3]
        else:
            ip, port = addr[0], addr[1]
        if self.reply_port is not None:
            port = self.reply_port
        return (ip, port)

    def busy(self):
        return False

    # -- in

    def _datagram(self):
        try:
            if hasattr(self.sock, "recvfrom_into"):
                n, addr = self.sock.recvfrom_into(self._buf)
                data = bytes(self._buf[:n])
            else:
                data, addr = self.sock.recvfrom(_MAX_DATAGRAM)
        except OSError as e:
            if e.args and e.args[0] in _AGAIN:
                return None, None
            raise
        return data, addr

    def recv(self):
        if self._frames:
            return self._frames.pop(0)
        if self.closed:
            return None
        while not self._frames:
            data, addr = self._datagram()
            if data is None:
                return None
            self.stats["datagrams"] += 1
            try:
                messages = decode(data)
            except ValueError:
                self.stats["bad"] += 1
                continue
            peer = self._addr(addr)
            if peer in self.peers:
                self.peers.remove(peer)
            self.peers.append(peer)
            del self.peers[:-_MAX_PEERS]
            for address, args in messages:
                frame = self._frame(address, args, peer)
                if frame is not None:
                    self.stats["messages"] += 1
                    self._frames.append(frame)
        return self._frames.pop(0)

    def _frame(self, address, args, peer):
        if not args:
            return None
        if address.startswith(_CMD):
            msg = {"t": "cmd", "name": address[len(_CMD) :], "args": {"args": args}}
        else:
            path = self.routes.get(address, address)
            value = args[0] if len(args) == 1 else args
            self._origin[path] = peer
            msg = {"t": "op", "op": "replace", "path": path, "value": value}
        return json.dumps(msg).encode()

    # -- out

    def send(self, frame):
        if self.closed or not self.peers:
            return
        try:
            msg = json.loads(frame)
        except ValueError:
            return
        t = msg.get("t")
        if t == "op":
            path = msg.get("path", "")
            skip = None
            if msg.get("from") == self.hmi_id:
                skip = self._origin.pop(path, None)
            if msg.get("op") == "remove":
                return
            args = _plain(msg.get("value"))
            if args is None:
                return
            self._send_all(self._back.get(path, path), args, skip)
        elif t == "tele":
            for key, value in (msg.get("v") or {}).items():
                args = _plain(value)
                if args is not None and len(args) == 1:
                    self._send_all("/tele/" + key, args, None)

    def _send_all(self, address, args, skip):
        try:
            data = encode(address, args)
        except TypeError:
            return
        for peer in self.peers:
            if peer == skip:
                continue
            try:
                self.sock.sendto(data, self._sockaddr(peer))
                self.stats["sent"] += 1
            except OSError:
                pass  # lossy, as OSC over UDP is; a gone app is dropped by age

    def _sockaddr(self, peer):
        addr = self._resolved.get(peer)
        if addr is None:
            addr = self._mod.getaddrinfo(peer[0], peer[1])[0][-1]
            self._resolved[peer] = addr
        return addr

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass


def serve(port, bind="0.0.0.0", routes=None, reply_port=None, peers=(), pool=None):
    """Listen for OSC on UDP ``port``; add the link this returns to a ``Device``.

    ``routes`` maps an app's addresses to document paths. ``reply_port``
    sends replies to that port instead of the one a message came from, and
    ``peers`` is a list of ``(ip, port)`` to send to from the start.
    """
    return Link(port, bind=bind, routes=routes, reply_port=reply_port, peers=peers, pool=pool)
