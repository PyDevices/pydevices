"""hmilink's checks, runnable on MicroPython, CircuitPython and CPython.

    python hmilink/tests/run.py           # from the repo root, or
    micropython hmilink/tests/run.py

pytest collects ``test_all`` from here too.
"""

import binascii
import os
import sys

sys.path.insert(0, os.getcwd() + "/hmilink")
try:
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
except (NameError, IndexError):
    pass

import hmilink  # noqa: E402
from hmilink import local, stream  # noqa: E402

try:
    from hmilink import tcp
except ImportError:
    tcp = None

try:
    from hmilink import osc
except ImportError:
    osc = None

# Windows refuses some ports with 10013 and the set moves (Hyper-V and WSL
# reserve ranges as they go; 19411 and later 8765 were refused here on
# 2026-10-21 with nothing listening), so the checks take the first that binds.
PORTS = (8765, 8766, 9765, 9876, 18765, 28765)
PORT = None


def pick_port():
    global PORT
    if PORT is not None:
        return PORT
    for port in PORTS:
        try:
            tcp.serve(port, bind="127.0.0.1").close()
        except OSError:
            continue
        PORT = port
        return port
    raise OSError("no port in %r would bind" % (PORTS,))


def check(cond, what):
    if not cond:
        raise AssertionError(what)


# -- the document --


def test_ops():
    doc = {"a": {"b": [1, 2, 3]}, "k/ey": 1}
    hmilink.apply_op(doc, {"op": "replace", "path": "/a/b/1", "value": 9})
    check(doc["a"]["b"] == [1, 9, 3], "replace in a list")
    hmilink.apply_op(doc, {"op": "add", "path": "/a/b/-", "value": 4})
    check(doc["a"]["b"] == [1, 9, 3, 4], "append")
    hmilink.apply_op(doc, {"op": "add", "path": "/a/b/0", "value": 0})
    check(doc["a"]["b"] == [0, 1, 9, 3, 4], "insert")
    hmilink.apply_op(doc, {"op": "remove", "path": "/a/b/0"})
    check(doc["a"]["b"] == [1, 9, 3, 4], "remove from a list")
    hmilink.apply_op(doc, {"op": "add", "path": "/a/c", "value": {"x": 1}})
    check(doc["a"]["c"] == {"x": 1}, "add a key")
    hmilink.apply_op(doc, {"op": "add", "path": "/a/c", "value": 2})
    check(doc["a"]["c"] == 2, "add on an existing key replaces")
    hmilink.apply_op(doc, {"op": "replace", "path": "/k~1ey", "value": 5})
    check(doc["k/ey"] == 5, "pointer escaping")
    try:
        hmilink.apply_op(doc, {"op": "replace", "path": "/nope", "value": 1})
        check(False, "replace of a missing key must raise")
    except KeyError:
        pass
    check(hmilink.get_path(doc, "/a/b/1") == 9, "get_path")
    check(hmilink.get_path(doc, "/a/zz", "d") == "d", "get_path default")
    hmilink.apply_op(doc, {"op": "replace", "path": "", "value": {"fresh": 1}})
    check(doc == {"fresh": 1}, "replace the whole document")


# -- a model that refuses and clips --


class Knobs(hmilink.Model):
    def __init__(self):
        super().__init__({"knobs": {"a": 0.5, "b": 0.5}})
        self.level = 0.0
        self.saved = None

    def describe(self):
        return {"kind": "knobs", "range": [0.0, 1.0]}

    def apply(self, op):
        keys = hmilink.split_pointer(op["path"])
        if op["op"] != "replace" or len(keys) != 2 or keys[0] != "knobs":
            raise ValueError("only knobs move")
        v = max(0.0, min(1.0, float(op["value"])))
        self.doc["knobs"][keys[1]] = v
        return {"op": "replace", "path": op["path"], "value": v}

    def telemetry(self):
        self.level += 0.25
        return {"level": self.level}

    def command(self, name, args):
        if name == "save":
            self.saved = args.get("path")
            return {"name": "saved", "path": self.saved}
        raise ValueError("no such command")


def pump(device, panels, rounds=8):
    import time

    for _ in range(rounds):
        device.poll()
        for p in panels:
            p.poll()
        time.sleep(0.002)  # loopback delivery is slower than a spinning loop


def exercise(device, p1, p2, telemetry=True):
    """What every transport must carry; the device and panels are already linked."""
    pump(device, (p1, p2))
    check(p1.ready and p2.ready, "both panels got the document")
    check(p1.desc.get("kind") == "knobs", "the description came with it")
    check(p1.me != p2.me and p1.me is not None, "each panel knows its own number")

    seen = []
    p2.on_op = seen.append
    echoed = []
    p1.on_op = echoed.append
    p1.set("/knobs/a", 0.9)
    check(p1.doc["knobs"]["a"] == 0.9, "optimistic local apply")
    pump(device, (p1, p2))
    check(p2.doc["knobs"]["a"] == 0.9, "the other panel followed")
    check(seen and seen[0]["seq"] == 1 and seen[0]["from"] == p1.me, "numbered, attributed")
    check(echoed and echoed[0]["id"] == 1, "the sender got its echo with its id")
    check(device.model.doc["knobs"]["a"] == 0.9, "the model applied it")

    p1.set("/knobs/b", 7.0)
    pump(device, (p1, p2))
    check(p1.doc["knobs"]["b"] == 1.0 and p2.doc["knobs"]["b"] == 1.0, "clipped value won")

    errs = []
    p2.on_error = errs.append
    p2.send("remove", "/knobs/a")
    pump(device, (p1, p2))
    check(errs and "only knobs" in errs[0]["msg"], "a refused op comes back as err")
    check(device.model.doc["knobs"]["a"] == 0.9, "and changed nothing")
    check(p1.doc["knobs"]["a"] == 0.9, "nor on the other panel")

    evs = []
    p1.on_event = evs.append
    p2.command("save", path="x.json")
    pump(device, (p1, p2))
    check(evs and evs[0]["name"] == "saved" and device.model.saved == "x.json", "command, event")

    if telemetry:
        tele = []
        p2.on_tele = tele.append
        device._tele_at -= 10000
        pump(device, (p1, p2))
        check(tele and "level" in tele[0], "telemetry arrived")

    pongs = []
    p1.on_pong = pongs.append
    p1.ping()
    pump(device, (p1, p2))
    check(pongs, "ping answered")

    # a newer op of my own on the same path is in flight: the older echo is skipped
    p1.set("/knobs/a", 0.1)
    p1.set("/knobs/a", 0.2)
    before = p1.stats["echo_skipped"]
    pump(device, (p1, p2))
    check(p1.stats["echo_skipped"] == before + 1, "stale echo skipped")
    check(p1.doc["knobs"]["a"] == 0.2 and p2.doc["knobs"]["a"] == 0.2, "both at the newest")

    # an append applied when sent must not be applied again by its own echo
    device.model.apply = lambda op: (hmilink.apply_op(device.model.doc, op), op)[1]
    device.model.doc["list"] = []
    p1.doc["list"] = []
    p2.doc["list"] = []
    p1.send("add", "/list/-", 1)
    p1.send("add", "/list/-", 2)
    pump(device, (p1, p2))
    check(p1.doc["list"] == [1, 2], "the sender has each append once: %r" % p1.doc["list"])
    check(p2.doc["list"] == [1, 2], "the other panel too: %r" % p2.doc["list"])
    p2.remove("/list/0")
    pump(device, (p1, p2))
    check(p1.doc["list"] == [2] and p2.doc["list"] == [2], "a list remove lands once")
    return True


def test_local():
    model = Knobs()
    device = hmilink.Device(model)
    lst = device.add(local.serve())
    p1 = hmilink.Panel(local.connect(lst))
    p2 = hmilink.Panel(local.connect(lst))
    exercise(device, p1, p2)
    p1.close()
    pump(device, (p2,))
    check(len(device.links) == 1, "a closed link is dropped")
    device.close()


# -- order --


class Swapper:
    """A device-side link that sends two op frames in the wrong order once:
    the fault a panel's order check must catch."""

    def __init__(self, link):
        self.link = link
        self.held = None
        self.armed = True

    def __getattr__(self, name):
        return getattr(self.link, name)

    def send(self, frame):
        if self.armed and b'"t": "op"' in frame:
            if self.held is None:
                self.held = frame
                return
            self.armed = False
            self.link.send(frame)
            frame, self.held = self.held, None
        self.link.send(frame)


def test_order():
    model = hmilink.Model({"list": [], "k": 0})
    device = hmilink.Device(model, telemetry_hz=0)
    lst = device.add(local.serve())
    p1 = hmilink.Panel(local.connect(lst))
    p2 = hmilink.Panel(local.connect(lst))
    pump(device, (p1, p2))

    # Two panels append to one list at once: the device's order wins on both.
    p1.send("add", "/list/-", "a")
    p2.send("add", "/list/-", "b")
    p1.send("add", "/list/-", "c")
    pump(device, (p1, p2))
    check(p1.doc == model.doc and p2.doc == model.doc,
          "crossed appends agree: %r %r %r" % (model.doc, p1.doc, p2.doc))
    check(p1.stats["resyncs"] + p2.stats["resyncs"] >= 1, "a crossed list was taken again from the device")

    # An index edit after the crossing lands on the same item everywhere.
    p2.send("replace", "/list/0", "z")
    pump(device, (p1, p2))
    check(p1.doc == model.doc == p2.doc, "index edits agree: %r %r" % (p1.doc, p2.doc))

    # An edit inside an item while another panel removes one before it: the
    # index names a different item on the device, so the copy is taken again.
    model.doc["rows"] = [{"v": 0}, {"v": 1}, {"v": 2}]
    device.reset_doc()
    pump(device, (p1, p2))
    p2.send("remove", "/rows/0")
    device.poll()  # the device has the remove; p1 hasn't heard yet
    p1.send("replace", "/rows/1/v", 10)
    pump(device, (p1, p2))
    check(p1.doc == model.doc == p2.doc, "an item edit crossing a remove agrees: %r %r %r"
          % (model.doc["rows"], p1.doc["rows"], p2.doc["rows"]))

    # local=False: the caller changed doc itself; nothing is applied twice.
    p1.doc["list"].append("x")
    p1.send("add", "/list/-", "x", local=False)
    pump(device, (p1, p2))
    check(p1.doc == model.doc == p2.doc and model.doc["list"][-1] == "x" and model.doc["list"].count("x") == 1,
          "local=False sends without applying: %r" % p1.doc)

    # Plant the fault: two ops reach p2 swapped. It must notice, not apply
    # them, and take the document again.
    errs = []
    p2.on_error = errs.append
    i = [j for j, link in enumerate(device.links) if link.hmi_id == p2.me][0]
    device.links[i] = Swapper(device.links[i])
    p1.set("/k", 1)
    p1.set("/k", 2)
    pump(device, (p1, p2))
    check(p2.stats["out_of_order"] == 1, "the swapped op was caught: %r" % p2.stats)
    check(errs and errs[0]["t"] == "order", "and reported")
    check(p2.doc == model.doc and p2.doc["k"] == 2, "and the panel is back in step: %r" % p2.doc)
    p1.set("/k", 3)
    pump(device, (p1, p2))
    check(p2.doc["k"] == 3 and p2.stats["out_of_order"] == 1, "and stays in step")
    device.close()


class FakeStream:
    """Two ends; what one writes the other reads, a few bytes at a time."""

    def __init__(self):
        self.buf = b""
        self.peer = None

    def write(self, data):
        n = min(len(data), 7)  # short writes, on purpose
        self.peer.buf += data[:n]
        return n

    def any(self):
        return len(self.buf)

    def read(self, n):
        data, self.buf = self.buf[:n], self.buf[n:]
        return data


def test_stream():
    a, b = FakeStream(), FakeStream()
    a.peer, b.peer = b, a
    c, d = FakeStream(), FakeStream()
    c.peer, d.peer = d, c
    device = hmilink.Device(Knobs())
    device.add(stream.link(a))
    device.add(stream.link(c))
    p1 = hmilink.Panel(stream.link(b))
    p2 = hmilink.Panel(stream.link(d))
    exercise(device, p1, p2, telemetry=False)


class WSClient:
    """Enough of a browser to prove the port speaks WebSocket."""

    def __init__(self, host, port, device):
        import socket

        self.s = socket.socket()
        self.s.connect(socket.getaddrinfo(host, port)[0][-1])
        self.s.send(
            b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.s.setblocking(False)
        head = b""
        for _ in range(200):
            device.poll()  # the device answers only when polled, as it would between blocks
            try:
                head += self.s.recv(256)
            except OSError:
                pass
            if b"\r\n\r\n" in head:
                break
        check(b"101" in head.split(b"\r\n")[0], "101 Switching Protocols")
        check(b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in head, "RFC 6455's example accept key")
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.closed = False
        self.hmi_id = 0

    def busy(self):
        return False

    def send(self, frame):
        n = len(frame)
        mask = b"\x12\x34\x56\x78"
        head = bytes((0x81, 0x80 | n)) if n < 126 else bytes((0x81, 0x80 | 126, n >> 8, n & 0xFF))
        body = bytes(frame[i] ^ mask[i & 3] for i in range(n))
        self.s.send(head + mask + body)

    def recv(self):
        try:
            self.buf += self.s.recv(4096)
        except OSError:
            pass
        if len(self.buf) < 2:
            return None
        n = self.buf[1] & 0x7F
        pos = 2
        if n == 126:
            n = (self.buf[2] << 8) | self.buf[3]
            pos = 4
        elif n == 127:
            n = int.from_bytes(self.buf[2:10], "big")
            pos = 10
        if len(self.buf) < pos + n:
            return None
        frame = self.buf[pos : pos + n]
        self.buf = self.buf[pos + n :]
        return frame

    def close(self):
        self.s.close()
        self.closed = True


def test_tcp():
    import socket

    pick_port()
    device = hmilink.Device(Knobs())
    device.add(tcp.serve(PORT, bind="127.0.0.1", page=b"<html>hi</html>"))
    p1 = hmilink.Panel(tcp.connect("127.0.0.1", PORT))
    p2 = hmilink.Panel(WSClient("127.0.0.1", PORT, device))
    exercise(device, p1, p2)

    # a frame longer than 125 bytes takes the 2-byte length form both ways
    p2.set("/knobs/a", 0.123456789)
    pump(device, (p1, p2))
    check(p1.doc["knobs"]["a"] == 0.123456789, "a WebSocket op reached the line client")

    s = socket.socket()
    s.connect(socket.getaddrinfo("127.0.0.1", PORT)[0][-1])
    s.send(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    got = b""
    import time

    for _ in range(100):
        device.poll()
        try:
            s.setblocking(False)
            got += s.recv(1024)
        except OSError:
            pass
        if b"</html>" in got:
            break
        time.sleep(0.002)
    check(b"200 OK" in got and got.endswith(b"<html>hi</html>"), "the page is served")
    s.close()
    p1.close()
    p2.close()
    device.close()


class NoRecv:
    """A socket as CircuitPython's socketpool makes them: recv_into, no recv."""

    def __init__(self, s):
        self.s = s

    def __getattr__(self, name):
        if name == "recv":
            raise AttributeError(name)
        return getattr(self.s, name)

    def recv_into(self, buf):
        data = self.s.recv(len(buf))
        buf[: len(data)] = data
        return len(data)

    def accept(self):
        client, addr = self.s.accept()
        return NoRecv(client), addr


class Pool:
    """A stand-in for socketpool.SocketPool(wifi.radio)."""

    def __init__(self):
        import socket

        self.mod = socket
        self.SOL_SOCKET = socket.SOL_SOCKET
        self.SO_REUSEADDR = socket.SO_REUSEADDR

    def socket(self):
        return NoRecv(self.mod.socket())

    def getaddrinfo(self, host, port):
        return self.mod.getaddrinfo(host, port)


def test_tcp_pool():
    """tcp over sockets that read only with recv_into, as CircuitPython's do."""
    pool = Pool()
    pick_port()
    device = hmilink.Device(Knobs())
    device.add(tcp.serve(PORT, bind="127.0.0.1", pool=pool))
    p1 = hmilink.Panel(tcp.connect("127.0.0.1", PORT, pool=pool))
    p2 = hmilink.Panel(tcp.connect("127.0.0.1", PORT, pool=pool))
    exercise(device, p1, p2)
    p1.close()
    p2.close()
    device.close()


def test_pty():
    """The stream transport over real ttys: two pty pairs, raw mode, non-blocking reads."""
    import fcntl
    import tty

    class Tty:
        def __init__(self, fd):
            self.fd = fd
            fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

        def read(self, n):
            try:
                return os.read(self.fd, n)
            except BlockingIOError:
                return None

        def write(self, data):
            return os.write(self.fd, data)

    m1, s1 = os.openpty()
    m2, s2 = os.openpty()
    for fd in (m1, s1, m2, s2):
        tty.setraw(fd)
    device = hmilink.Device(Knobs())
    device.add(stream.link(Tty(m1)))
    device.add(stream.link(Tty(m2)))
    p1 = hmilink.Panel(stream.link(Tty(s1)))
    p2 = hmilink.Panel(stream.link(Tty(s2)))
    exercise(device, p1, p2)
    for fd in (m1, s1, m2, s2):
        os.close(fd)


def test_osc_codec():
    """OSC messages and bundles, read and written, against bytes worked out by hand."""
    # "/a" ,f 0.5 : address padded to 4, tags ",f" padded to 4, a big-endian float.
    msg = b"/a\x00\x00,f\x00\x00\x3f\x00\x00\x00"
    check(osc.encode("/a", [0.5]) == msg, "encode a float")
    check(osc.decode(msg) == [("/a", [0.5])], "decode a float")
    data = osc.encode("/xy", [1, "hi", True, False, None])
    check(osc.decode(data) == [("/xy", [1, "hi", True, False, None])], "round trip")
    check(osc.decode(b"/n\x00\x00") == [("/n", [])], "no type tags")
    bundle = b"#bundle\x00" + b"\x00" * 7 + b"\x01"
    for part in (msg, data):
        bundle += len(part).to_bytes(4, "big") + part
    check([m[0] for m in osc.decode(bundle)] == ["/a", "/xy"], "a bundle")
    for bad in (b"", b"nope\x00\x00\x00\x00", b"/a\x00\x00,f\x00\x00\x3f"):
        try:
            osc.decode(bad)
        except (ValueError, IndexError):
            continue
        raise AssertionError("decoded %r" % bad)


def _udp(port):
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(socket.getaddrinfo("127.0.0.1", 0)[0][-1])
    s.settimeout(1.0)
    return s


def _osc_recv(s):
    try:
        data, _ = s.recvfrom(1536)
    except OSError:
        return None
    return osc.decode(data)


def test_osc():
    """Two apps over UDP: ops, routes, echoes, commands, telemetry and a refusal."""
    import socket

    model = Knobs()
    device = hmilink.Device(model, telemetry_hz=0)
    port = None
    for p in PORTS:
        try:
            link = osc.serve(p, bind="127.0.0.1", routes={"/1/fader1": "/knobs/b"})
        except OSError:
            continue
        port = p
        break
    check(port is not None, "an OSC port binds")
    device.add(link)
    to = socket.getaddrinfo("127.0.0.1", port)[0][-1]
    app1 = _udp(port)
    app2 = _udp(port)

    def settle():
        import time

        for _ in range(20):
            device.poll()
            time.sleep(0.005)  # loopback datagrams take a moment to land

    # app2 says hello so the device knows it; a message with no argument is ignored.
    app2.sendto(osc.encode("/hello"), to)
    settle()
    check(model.doc["knobs"] == {"a": 0.5, "b": 0.5}, "no-argument message ignored")
    # app1 moves a knob by its document path: the model applies it (clipped),
    # app2 hears it, app1 doesn't hear its own echo.
    app1.sendto(osc.encode("/knobs/a", [1.5]), to)
    settle()
    check(model.doc["knobs"]["a"] == 1.0, "op applied and clipped")
    check(_osc_recv(app2) == [("/knobs/a", [1.0])], "the other app hears the op")
    app1.settimeout(0.2)
    check(_osc_recv(app1) is None, "the sender gets no echo")
    # A routed address: app2's fader is the document's /knobs/b, and app1 hears it
    # at the fader's address.
    app2.sendto(osc.encode("/1/fader1", [0.25]), to)
    settle()
    check(model.doc["knobs"]["b"] == 0.25, "routed op applied")
    app1.settimeout(1.0)
    check(_osc_recv(app1) == [("/1/fader1", [0.25])], "echo at the app's own address")
    # A command, then an op the model refuses: nothing moves and nothing breaks.
    commands = []
    model.command = lambda name, args: commands.append((name, args))
    app1.sendto(osc.encode("/cmd/save", ["x.json"]), to)
    app1.sendto(osc.encode("/other", [1]), to)
    app1.sendto(b"garbage", to)
    settle()
    check(commands == [("save", {"args": ["x.json"]})], "a command with its arguments")
    check(device.stats["refused"] == 1, "an op the model refuses")
    check(link.stats["bad"] == 1, "garbage counted")
    # Telemetry goes out as /tele/<key>.
    device._telemetry()
    check(_osc_recv(app2) == [("/tele/level", [0.25])], "telemetry to the apps")
    app1.close()
    app2.close()
    device.close()


def test_all():
    test_ops()
    print("ops ok")
    test_local()
    print("local ok")
    test_order()
    print("order ok (crossed lists, a swapped op caught)")
    test_stream()
    print("stream ok")
    try:
        import fcntl  # noqa: F401
        import tty  # noqa: F401

        has_pty = hasattr(os, "openpty")
    except ImportError:
        has_pty = False
    if has_pty:
        test_pty()
        print("stream over ptys ok")
    if tcp is not None and getattr(tcp, "_socket", None) is not None:
        test_tcp()
        print("tcp ok (lines, WebSocket, page)")
        test_tcp_pool()
        print("tcp ok over recv_into sockets (CircuitPython's)")
    else:
        print("tcp skipped: no socket module")
    if osc is not None and getattr(osc, "_socket", None) is not None:
        test_osc_codec()
        test_osc()
        print("osc ok (codec, UDP, routes, echoes)")
    else:
        print("osc skipped: no socket module")
    print("hmilink ok on", sys.implementation.name, binascii.hexlify(b"\x01").decode())


if __name__ == "__main__":
    test_all()
