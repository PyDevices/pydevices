"""hmilink: any screen as a device's front panel.

A device holds the true state of something (a synth rack, a song) as one
JSON document. Any number of front panels show and change it: the device's
own screen, a phone's browser, a control app. They all speak this one small
contract, so no two screens disagree with the sound, and a new panel never
means touching the device's code.

The contract
------------
Every message is a JSON object with a ``t`` (type). What a panel sends:

``{"t": "op", "op": "replace", "path": "/modules/vco1/params/range", "value": 1.0, "id": 7}``
    A JSON Patch op (``add``, ``replace`` or ``remove``) with a JSON Pointer
    path. ``id`` is the panel's own number for it, handed back in the echo.
``{"t": "cmd", "name": "save", "args": {"path": "patch.json"}}``
    A command. What the model does with it is the model's business.
``{"t": "ping", "at": 12345}``
    Answered with ``pong`` carrying the same ``at``, for round-trip timing.

What the device sends:

``{"t": "doc", "seq": 41, "doc": {...}, "desc": {...}}``
    The whole document and the model's self-description, on connect and
    whenever the model replaces its document (a patch load).
``{"t": "op", "seq": 42, "op": ..., "path": ..., "value": ..., "id": 7, "from": 2}``
    Every op the model accepted, numbered, to every panel. The sender sees
    its own op come back with its ``id``; ``from`` is the device's number
    for the link it came from. ``value`` is what the model applied, which
    may differ from what was asked (a knob is clipped to its range).
``{"t": "err", "id": 7, "msg": "..."}``
    An op or command the model refused, to the panel that sent it.
``{"t": "tele", "v": {...}}``
    Telemetry: LEDs, levels, a playhead. Latest wins. It is sent to a link
    only when nothing is queued on it, so it never delays an op and never
    piles up behind a slow link.
``{"t": "ev", "name": "...", ...}``
    An event from the model, to every panel.

Ops and the document are plain JSON, so the whole state crosses any link
as text and any language can read it. The self-description says what the
document holds (for a rack: module types, each parameter's range, each
jack), never how to lay it out: whoever draws a panel decides that.

The pieces
----------
A **model** is what the device is about. It keeps ``doc`` current and
answers four calls; :class:`Model` is a base whose defaults make a plain
document editable with no model code at all::

    class RackModel(hmilink.Model):
        def describe(self): ...        # what the document offers
        def apply(self, op): ...       # apply an op to the real thing and to doc; return it
        def telemetry(self): ...       # a dict, or None
        def command(self, name, args): ...

A **transport** moves frames (one message's bytes) and knows nothing about
what is in them, so neither the device nor the panel knows which one
carries it. One module per transport, as in ``midiports``: :mod:`hmilink.tcp`
(TCP with newline framing; the same port also serves a page and speaks
WebSocket to a browser), :mod:`hmilink.local` (in-process, for the
device's own screen and for tests) and :mod:`hmilink.stream` (anything with
``read``/``write``: a UART or USB CDC). A transport gives you a *link*
(``send(frame)``, ``recv()`` returning one frame or ``None``, ``close()``,
``closed``) or a *listener* (``accept()`` returning a link or ``None``).

The **device** side::

    device = hmilink.Device(model)
    device.add(tcp.serve(9000, page="index.html"))
    while True:
        rack.step(); pcm.write(block)
        device.poll()                  # between blocks: so every edit lands on a block boundary

The **panel** side::

    panel = hmilink.Panel(tcp.connect("192.168.1.42", 9000))
    panel.on_op = redraw_one; panel.on_tele = light_leds
    while True:
        panel.poll()                   # from the UI loop
        ...
        panel.send("replace", "/modules/vco1/params/range", 0.5)

Nothing here needs threads or asyncio, so it runs the same on MicroPython,
CircuitPython and CPython, and ``poll()`` is cheap enough to call every
audio block.
"""

import json
import time

__version__ = "0.0.1"

try:
    from time import ticks_diff, ticks_ms
except ImportError:  # CPython

    def ticks_ms():
        return int(time.monotonic() * 1000.0)

    def ticks_diff(a, b):
        return a - b


# -- the document ----------------------------------------------------------


def split_pointer(path):
    """The keys of a JSON Pointer: ``"/a/b~1c"`` is ``["a", "b/c"]``."""
    if not path:
        return []
    if path[0] != "/":
        raise ValueError("path must start with '/': %r" % path)
    return [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]


def join_pointer(keys):
    return "".join("/" + str(k).replace("~", "~0").replace("/", "~1") for k in keys)


def _step(node, key):
    return node[int(key)] if isinstance(node, list) else node[key]


def apply_op(doc, op):
    """Apply one JSON Patch op to ``doc`` in place.

    ``op`` is a dict with ``op`` (``add``, ``replace`` or ``remove``),
    ``path`` and, for the first two, ``value``. ``add`` on a dict key that
    exists replaces it, as RFC 6902 says; on a list index it inserts, and
    ``-`` appends. An empty path replaces the whole document's contents.
    Returns the parent container the op touched.
    """
    kind = op["op"]
    keys = split_pointer(op["path"])
    if not keys:
        if kind == "remove":
            doc.clear()
        else:
            doc.clear()
            doc.update(op["value"])
        return doc
    node = doc
    for key in keys[:-1]:
        node = _step(node, key)
    key = keys[-1]
    if isinstance(node, list):
        if kind == "add":
            if key == "-":
                node.append(op["value"])
            else:
                node.insert(int(key), op["value"])
        elif kind == "replace":
            node[int(key)] = op["value"]
        elif kind == "remove":
            del node[int(key)]
        else:
            raise ValueError("unknown op %r" % kind)
    elif kind in ("add", "replace"):
        if kind == "replace" and key not in node:
            raise KeyError(op["path"])
        node[key] = op["value"]
    elif kind == "remove":
        del node[key]
    else:
        raise ValueError("unknown op %r" % kind)
    return node


def _list_path(path):
    """True when a path ends in a list index or ``-``: its add and remove aren't idempotent."""
    keys = split_pointer(path)
    return bool(keys) and (keys[-1] == "-" or keys[-1].isdigit())


def get_path(doc, path, default=None):
    """The value at a JSON Pointer path, or ``default``."""
    node = doc
    try:
        for key in split_pointer(path):
            node = _step(node, key)
    except (KeyError, IndexError, ValueError, TypeError):
        return default
    return node


# -- the codec ---------------------------------------------------------------


class JSONCodec:
    """Messages as JSON text, one frame each."""

    def encode(self, msg):
        return json.dumps(msg).encode()

    def decode(self, frame):
        return json.loads(frame)


# -- the model ---------------------------------------------------------------


class Model:
    """What a device is about. Subclass it, or use it as is for a plain document.

    ``doc`` is the document the device sends on connect and keeps in step
    with the ops it accepts. The default ``apply`` edits ``doc`` and nothing
    else, so a device with a bare ``Model`` is a shared JSON document.
    """

    def __init__(self, doc=None):
        self.doc = doc if doc is not None else {}

    def describe(self):
        """What the document offers, for a panel to draw from. No layout."""
        return {}

    def apply(self, op):
        """Apply an op to the real thing and to ``doc``; return the op as applied.

        Raise to refuse it. The op returned is what every panel sees, so
        put the value that was really applied in it.
        """
        apply_op(self.doc, op)
        return op

    def telemetry(self):
        """A dict of lossy values (LEDs, levels), or None for nothing new."""
        return None

    def command(self, name, args):
        """Do a command; return an event dict to broadcast, or None."""
        raise ValueError("unknown command %r" % name)


# -- the device ------------------------------------------------------------------


class Device:
    """The side that holds the document. Poll it between audio blocks."""

    def __init__(self, model, codec=None, telemetry_hz=20):
        self.model = model
        # So a model can broadcast an event or announce a replaced document.
        model.device = self
        self.codec = codec or JSONCodec()
        self.seq = 0
        self.listeners = []
        self.links = []
        self._next_link = 1
        self._tele_ms = int(1000 / telemetry_hz) if telemetry_hz else 0
        self._tele_at = ticks_ms()
        #: Counters a test or a status line can read.
        self.stats = {"ops": 0, "refused": 0, "tele": 0, "tele_dropped": 0, "frames": 0}

    # -- endpoints --

    def add(self, endpoint):
        """Add a listener (anything with ``accept()``) or a link."""
        if hasattr(endpoint, "accept"):
            self.listeners.append(endpoint)
        else:
            self._attach(endpoint)
        return endpoint

    def _attach(self, link):
        link.hmi_id = self._next_link
        self._next_link += 1
        self.links.append(link)
        self._send(link, self._snapshot(link))
        return link

    def _snapshot(self, link):
        return {
            "t": "doc",
            "seq": self.seq,
            "doc": self.model.doc,
            "desc": self.model.describe(),
            "you": link.hmi_id,
        }

    def reset_doc(self):
        """Tell every panel the document was replaced (after a load)."""
        self.seq += 1
        for link in self.links:
            self._send(link, self._snapshot(link))

    def close(self):
        for link in self.links:
            link.close()
        for lst in self.listeners:
            lst.close()
        self.links = []
        self.listeners = []

    # -- sending --

    def _send(self, link, msg):
        try:
            link.send(self.codec.encode(msg))
        except OSError:
            link.close()

    def broadcast(self, msg):
        frame = self.codec.encode(msg)
        for link in self.links:
            try:
                link.send(frame)
            except OSError:
                link.close()

    def event(self, name, **data):
        """Broadcast an event from the model."""
        data["t"] = "ev"
        data["name"] = name
        self.broadcast(data)

    # -- polling --

    def poll(self):
        """Accept, read, apply, answer, and send telemetry when due. Never blocks."""
        for lst in self.listeners:
            while True:
                link = lst.accept()
                if link is None:
                    break
                self._attach(link)
        for link in self.links:
            while True:
                frame = link.recv()
                if frame is None:
                    break
                self.stats["frames"] += 1
                try:
                    msg = self.codec.decode(frame)
                except ValueError:
                    continue
                self._handle(link, msg)
        if self._tele_ms:
            now = ticks_ms()
            if ticks_diff(now, self._tele_at) >= self._tele_ms:
                self._tele_at = now
                self._telemetry()
        for link in self.links:
            if hasattr(link, "flush"):
                link.flush()
        if any(link.closed for link in self.links):
            self.links = [link for link in self.links if not link.closed]

    def _telemetry(self):
        if not self.links:
            return
        values = self.model.telemetry()
        if not values:
            return
        frame = None
        for link in self.links:
            if link.busy():
                self.stats["tele_dropped"] += 1
                continue
            if frame is None:
                frame = self.codec.encode({"t": "tele", "v": values})
                self.stats["tele"] += 1
            try:
                link.send(frame)
            except OSError:
                link.close()

    def _handle(self, link, msg):
        t = msg.get("t")
        if t == "op":
            try:
                op = self.model.apply(
                    {"op": msg["op"], "path": msg["path"], "value": msg.get("value")}
                )
            except Exception as e:  # noqa: BLE001 - whatever the model refuses with
                self.stats["refused"] += 1
                # Say what is there now, so the panel can undo what it applied early.
                err = {"t": "err", "id": msg.get("id"), "msg": str(e), "path": msg.get("path")}
                now = get_path(self.model.doc, msg.get("path", ""), _MISSING)
                if now is not _MISSING:
                    err["value"] = now
                self._send(link, err)
                return
            self.seq += 1
            self.stats["ops"] += 1
            out = {"t": "op", "seq": self.seq, "op": op["op"], "path": op["path"]}
            if op["op"] != "remove":
                out["value"] = op.get("value")
            out["id"] = msg.get("id")
            out["from"] = link.hmi_id
            self.broadcast(out)
        elif t == "cmd":
            try:
                ev = self.model.command(msg.get("name"), msg.get("args") or {})
            except Exception as e:  # noqa: BLE001
                self.stats["refused"] += 1
                self._send(link, {"t": "err", "id": msg.get("id"), "msg": str(e)})
                return
            if ev:
                ev["t"] = "ev"
                self.broadcast(ev)
        elif t == "ping":
            self._send(link, {"t": "pong", "at": msg.get("at")})


# -- the panel ---------------------------------------------------------------


class Panel:
    """The side that shows and changes the document. Poll it from the UI loop.

    Set the callbacks you want: ``on_doc(doc, desc)`` when the whole
    document arrives, ``on_op(op)`` after each op is applied to ``doc``,
    ``on_tele(values)``, ``on_event(msg)``, ``on_error(msg)``,
    ``on_pong(ms)`` with the round trip of a ``ping()``.

    ``send()`` applies the op to the local copy at once and sends it, so a
    knob never lags its own finger; the device's echo is applied when it
    comes back, unless a newer op of this panel's on the same path is still
    in flight.
    """

    def __init__(self, link, codec=None):
        self.link = link
        self.codec = codec or JSONCodec()
        self.doc = None
        self.desc = None
        self.seq = 0
        #: The device's number for this link, from the ``doc`` message.
        self.me = None
        self.on_doc = None
        self.on_op = None
        self.on_tele = None
        self.on_event = None
        self.on_error = None
        self.on_pong = None
        self._next_id = 1
        self._pending = {}
        self._pings = {}
        self.stats = {"ops_in": 0, "ops_out": 0, "tele": 0, "echo_skipped": 0}
        # Say hello, so a transport that learns its framing from the first
        # line (tcp) can send the document even to a panel that only listens.
        self._send({"t": "hello", "v": 1})

    @property
    def ready(self):
        return self.doc is not None

    @property
    def closed(self):
        return self.link.closed

    def close(self):
        self.link.close()

    # -- sending --

    def _send(self, msg):
        self.link.send(self.codec.encode(msg))

    def send(self, op, path, value=None):
        """Apply an op locally and send it. Returns its id."""
        msg = {"t": "op", "op": op, "path": path, "id": self._next_id}
        if op != "remove":
            msg["value"] = value
        self._next_id += 1
        if self.doc is not None:
            try:
                apply_op(self.doc, msg)
            except (KeyError, IndexError, ValueError, TypeError):
                pass
        self._pending[path] = msg["id"]
        self.stats["ops_out"] += 1
        self._send(msg)
        return msg["id"]

    def set(self, path, value):
        """``replace`` at a path; ``add`` when the path isn't there yet."""
        op = "replace" if get_path(self.doc, path, _MISSING) is not _MISSING else "add"
        return self.send(op, path, value)

    def remove(self, path):
        return self.send("remove", path)

    def command(self, name, **args):
        self._send({"t": "cmd", "name": name, "args": args})

    def ping(self):
        at = ticks_ms()
        self._pings[at] = True
        self._send({"t": "ping", "at": at})

    # -- receiving --

    def poll(self):
        """Read everything waiting and dispatch it. Returns how many messages came."""
        n = 0
        while True:
            frame = self.link.recv()
            if frame is None:
                break
            try:
                msg = self.codec.decode(frame)
            except ValueError:
                continue
            n += 1
            self._handle(msg)
        if hasattr(self.link, "flush"):
            self.link.flush()
        return n

    def _handle(self, msg):
        t = msg.get("t")
        if t == "op":
            self.seq = msg.get("seq", self.seq)
            self.stats["ops_in"] += 1
            path = msg["path"]
            mine = self.me is not None and msg.get("from") == self.me
            if mine and path in self._pending:
                if msg.get("id") == self._pending[path]:
                    del self._pending[path]
                    if _list_path(path):
                        # Already applied when sent, and an append or a list
                        # remove is not idempotent: don't apply the echo.
                        if self.on_op:
                            self.on_op(msg)
                        return
                else:
                    self.stats["echo_skipped"] += 1
                    return
            if self.doc is not None:
                try:
                    apply_op(self.doc, msg)
                except (KeyError, IndexError, ValueError, TypeError):
                    return
            if self.on_op:
                self.on_op(msg)
        elif t == "tele":
            self.stats["tele"] += 1
            if self.on_tele:
                self.on_tele(msg.get("v") or {})
        elif t == "doc":
            self.doc = msg.get("doc")
            self.desc = msg.get("desc") or {}
            self.seq = msg.get("seq", 0)
            self.me = msg.get("you", self.me)
            self._pending = {}
            if self.on_doc:
                self.on_doc(self.doc, self.desc)
        elif t == "ev":
            if self.on_event:
                self.on_event(msg)
        elif t == "err":
            path = msg.get("path")
            if path is not None and self.doc is not None:
                # Undo the op applied early: put back what the device has.
                if "value" in msg:
                    undo = {"op": "add", "path": path, "value": msg["value"]}
                else:
                    undo = {"op": "remove", "path": path}
                self._pending.pop(path, None)
                try:
                    apply_op(self.doc, undo)
                except (KeyError, IndexError, ValueError, TypeError):
                    pass
                if self.on_op:
                    undo["restored"] = True
                    self.on_op(undo)
            if self.on_error:
                self.on_error(msg)
        elif t == "pong":
            at = msg.get("at")
            if at in self._pings:
                del self._pings[at]
                if self.on_pong:
                    self.on_pong(ticks_diff(ticks_ms(), at))


_MISSING = object()
