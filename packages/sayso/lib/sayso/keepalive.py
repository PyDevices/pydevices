"""A small HTTP/1.1 client that keeps its TLS connections open.

MicroPython's ``requests`` opens a new TCP connection and does a new TLS
handshake for every request. On an ESP32-S3 that handshake is most of a
second or more of CPU, so every tap in a remote cost one, and the remote felt
stuck. This keeps one connection per host and reuses it until the server
closes it, which is what a browser or a phone app does.

Only what sayso needs: GET/POST/PUT/DELETE with a body, ``Content-Length``
or chunked responses, and one transparent retry when a reused connection turns
out to have been closed by the server while idle.
"""

import json
import socket

try:
    import ssl
except ImportError:
    try:
        import tls as ssl  # MicroPython's built-in; ssl is a micropython-lib wrapper
    except ImportError:  # pragma: no cover
        ssl = None

try:
    import _thread

    def _lock():
        return _thread.allocate_lock()

    _MAIN_THREAD = _thread.get_ident()
except ImportError:
    _thread = None
    _MAIN_THREAD = None

    class _NoLock:
        def acquire(self, *_a):
            return True

        def release(self):
            pass

    def _lock():
        return _NoLock()


TIMEOUT_S = 20


def _let_others_run():
    """On a MicroPython worker thread, hand the GIL over for a moment.

    The VM passes the GIL on only every 32 backward jumps, so a loop of a few
    long C calls (json.loads of one item) would hold it throughout. Sleeping
    releases it; the main (UI) thread never needs to.
    """
    if _thread is not None and _sleep_ms is not None and _thread.get_ident() != _MAIN_THREAD:
        _sleep_ms(1)


try:
    from time import sleep_ms as _sleep_ms
except ImportError:  # CPython: its GIL switches by time, no help needed
    _sleep_ms = None

# Bodies at least this large with an "items" array are parsed an item at a
# time (see _loads_paged). json.loads runs ~11 ms per KB on an ESP32-S3, GIL
# held: a 24 KB playlist page was a 270 ms UI stall at a 32 KB threshold.
SPLIT_BYTES = 8 * 1024
# Largest single read: one read(n) decrypts all n bytes in C, GIL held.
READ_CHUNK = 4096


def _loads_paged(data):
    """json.loads for a large paging object, one item at a time.

    json.loads is one C call, and holds the GIL for all of it: 2.1 s for the
    325 KB of /me/albums?limit=30 (every album carries its track list) on an
    ESP32-S3, with the UI thread frozen that long behind the worker thread.
    Parsed item by item, the interpreter can switch threads between items
    (~70 ms each). The result is the same as json.loads(data); anything that
    does not split cleanly is parsed whole.
    """
    i = data.find(b'"items"')
    j = data.find(b"[", i) if i >= 0 else -1
    close = data.rfind(b"]")
    if j < 0 or close <= j or data[i + 7:j].strip() != b":":
        return json.loads(data)
    k = j + 1
    while k < close and data[k] in b" \t\r\n":
        k += 1
    q = data.find(b'"', k)
    if data[k:k + 1] != b"{" or q < 0 or data[k + 1:q].strip():
        return json.loads(data)
    # Each item starts with the first item's first key.
    needle = data[q:data.find(b'"', q + 1) + 1]
    starts = [k]
    at = data.find(needle, q + len(needle))
    while 0 <= at < close:
        s = data.rfind(b"{", k, at)
        if s > starts[-1] and not data[s + 1:at].strip():
            starts.append(s)
        at = data.find(needle, at + len(needle))
    starts.append(close)
    try:
        items = []
        for n in range(len(starts) - 1):
            part = data[starts[n]:starts[n + 1]].rstrip()
            if part.endswith(b","):
                part = part[:-1]
            items.append(json.loads(part))
            _let_others_run()
        # The array may sit at any depth ({"artists": {"items": [...]}}):
        # parse the rest around a marker, then put the items where it is.
        page = json.loads(data[:j + 1] + _MARK + data[close:])
    except ValueError:
        return json.loads(data)
    if not _put_items(page, items):
        return json.loads(data)
    return page


_MARK_TEXT = "__sayso_items_marker__"
_MARK = b'"' + _MARK_TEXT.encode() + b'"'


def _put_items(node, items):
    """Replace the one-element marker list inside node with items."""
    if isinstance(node, dict):
        children = node.values()
    elif isinstance(node, list):
        if len(node) == 1 and node[0] == _MARK_TEXT:
            node[0:1] = items
            return True
        children = node
    else:
        return False
    for child in children:
        if isinstance(child, (dict, list)) and _put_items(child, items):
            return True
    return False


class Response:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        if len(self.content) >= SPLIT_BYTES:
            return _loads_paged(self.content)
        return json.loads(self.content)

    def close(self):
        pass


class _Conn:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.used = 0

    def open(self):
        ai = socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM)[0]
        s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
        try:
            s.settimeout(TIMEOUT_S)
            s.connect(ai[-1])
            if hasattr(ssl, "SSLContext"):
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.verify_mode = ssl.CERT_NONE
                if hasattr(ctx, "check_hostname"):
                    ctx.check_hostname = False
                s = ctx.wrap_socket(s, server_hostname=self.host)
            else:
                s = ssl.wrap_socket(s, server_hostname=self.host)
        except Exception:
            s.close()
            raise
        self.sock = s
        self.used = 0

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None


def _split_url(url):
    if url.startswith("https://"):
        rest = url[8:]
        port = 443
    else:
        raise ValueError("keepalive handles https:// only: " + url)
    slash = rest.find("/")
    hostport, path = (rest, "/") if slash < 0 else (rest[:slash], rest[slash:])
    if ":" in hostport:
        host, p = hostport.split(":", 1)
        port = int(p)
    else:
        host = hostport
    return host, port, path


class _Reader:
    """Framed reads. MicroPython's stream read(n) waits for all n bytes, so
    headers come a line at a time and bodies by their exact length."""

    def __init__(self, sock):
        self.sock = sock

    def line(self):
        data = self.sock.readline()
        if not data:
            raise OSError("connection closed")
        if data.endswith(b"\r\n"):
            return data[:-2]
        return data.rstrip(b"\n")

    def exact(self, n):
        parts = []
        while n > 0:
            data = self.sock.read(n if n < READ_CHUNK else READ_CHUNK)
            if not data:
                raise OSError("connection closed")
            parts.append(data)
            n -= len(data)
            if n > 0:
                _let_others_run()
        return b"".join(parts)

    def rest(self):
        parts = []
        while True:
            try:
                d = self.sock.read(4096)
            except OSError:
                break
            if not d:
                break
            parts.append(d)
        return b"".join(parts)


class Session:
    def __init__(self):
        self._conns = {}
        self._lock = _lock()

    def _conn(self, host, port):
        key = (host, port)
        c = self._conns.get(key)
        if c is None:
            c = _Conn(host, port)
            self._conns[key] = c
        return c

    def close(self):
        for c in self._conns.values():
            c.close()
        self._conns = {}

    def request(self, method, url, data=None, headers=None):
        host, port, path = _split_url(url)
        if isinstance(data, str):
            data = data.encode("utf-8")
        head = ["%s %s HTTP/1.1" % (method, path), "Host: " + host,
                "Connection: keep-alive"]
        if headers:
            for k, v in headers.items():
                if k.lower() in ("host", "connection", "content-length"):
                    continue
                head.append("%s: %s" % (k, v))
        if data is not None or method in ("POST", "PUT", "PATCH", "DELETE"):
            head.append("Content-Length: %d" % (len(data) if data else 0))
        req = ("\r\n".join(head) + "\r\n\r\n").encode("utf-8")
        self._lock.acquire()
        try:
            c = self._conn(host, port)
            for attempt in (0, 1):
                reused = c.sock is not None
                if not reused:
                    c.open()
                got_any = [False]
                try:
                    return self._exchange(c, req, data, got_any)
                except OSError:
                    c.close()
                    # A reused connection the server had already closed fails
                    # before any byte of a response: that request was never
                    # seen, so ask once more on a fresh connection.
                    if attempt == 0 and reused and not got_any[0]:
                        continue
                    raise
        finally:
            self._lock.release()

    def _exchange(self, c, req, data, got_any):
        s = c.sock
        s.write(req) if hasattr(s, "write") else s.sendall(req)
        if data:
            s.write(data) if hasattr(s, "write") else s.sendall(data)
        r = _Reader(s)
        status_line = r.line()
        got_any[0] = True
        parts = status_line.split(None, 2)
        status = int(parts[1])
        headers = {}
        while True:
            line = r.line()
            if not line:
                break
            k, _, v = line.partition(b":")
            headers[k.strip().lower().decode()] = v.strip().decode()
        if status in (204, 304) or 100 <= status < 200:
            body = b""
        elif headers.get("transfer-encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size = int(r.line().split(b";")[0], 16)
                if size == 0:
                    while r.line():
                        pass
                    break
                chunks.append(r.exact(size))
                r.line()
            body = b"".join(chunks)
        elif "content-length" in headers:
            body = r.exact(int(headers["content-length"]))
        else:
            # No length: the body runs to the end of the connection.
            body = r.rest()
            headers["connection"] = "close"
        c.used += 1
        if headers.get("connection", "").lower() == "close":
            c.close()
        return Response(status, headers, body)

    def get(self, url, headers=None):
        return self.request("GET", url, None, headers)

    def post(self, url, data=None, headers=None):
        return self.request("POST", url, data, headers)

    def put(self, url, data=None, headers=None):
        return self.request("PUT", url, data, headers)

    def delete(self, url, data=None, headers=None):
        return self.request("DELETE", url, data, headers)
