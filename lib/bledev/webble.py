"""Web Bluetooth backend for browsers. Central only.

    from bledev.webble import WebBLE
    ble = WebBLE()
    link = await nus.connect(ble, name="rack")   # from a click handler

It runs wherever Python can reach the page's JavaScript: PyScript on Pyodide
or MicroPython, and the direct MicroPython WebAssembly build that Workbench
uses. It needs Chrome or Edge (desktop or Android) and a secure context,
``https://`` or ``http://localhost``. Firefox and iOS Safari have no Web
Bluetooth.

A browser differs from a board in three ways, and this backend says so
rather than pretending:

* **You don't scan; the browser's chooser does.** ``find()`` opens the
  device chooser filtered by ``name`` and ``service``, and the person picks.
  The chooser only opens during a click or a tap (transient user
  activation), so call ``find()`` or ``nus.connect()`` from one. ``scan()``
  raises :class:`bledev.UnsupportedError`.
* **Only services you named are reachable.** The browser grants the
  services in the ``find()`` filter and those passed as
  ``WebBLE(services=[...])``, and hides the rest from discovery.
* **The browser never reports the ATT MTU.** It negotiates one on its own,
  and a write longer than that can be cut short without an error, so
  ``connection.mtu`` is 23 (the one value every link has) unless you pass
  ``WebBLE(mtu=...)`` knowing the link negotiated more. The peripheral can
  see the real value.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import json

from . import (
    BLE,
    BLEError,
    BLETimeoutError,
    ClientCharacteristic,
    ClientService,
    Connection,
    DEFAULT_MTU,
    Device,
    DisconnectedError,
    FLAG_INDICATE,
    FLAG_NOTIFY,
    FLAG_READ,
    FLAG_WRITE,
    FLAG_WRITE_NO_RESPONSE,
    GattError,
    MAX_MTU,
    UnsupportedError,
    UUID,
    wait_ms,
)

try:
    import js
except ImportError:  # not in a browser; importing still works for tooling
    js = None


def _find_create_proxy():
    for name in ("pyodide.ffi", "jsffi", "pyscript.ffi"):
        try:
            module = __import__(name, None, None, ["create_proxy"])
            return module.create_proxy
        except (ImportError, AttributeError):
            pass
    return None


create_proxy = _find_create_proxy() if js is not None else None

# Everything that crosses into JavaScript goes through these few helpers, so
# Pyodide and MicroPython see the same thing: strings, numbers, booleans and
# opaque objects. Bytes cross as hex, which both runtimes convert the same way
# and which costs nothing next to a radio.
_HELPERS_JS = """
const hex = (v) => {
  let s = "";
  for (let i = 0; i < v.byteLength; i++) {
    const b = v.getUint8(i);
    s += (b < 16 ? "0" : "") + b.toString(16);
  }
  return s;
};
return {
  available: () => !!(globalThis.navigator && navigator.bluetooth),
  toBytes: (h) => {
    const a = new Uint8Array(h.length >> 1);
    for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16);
    return a;
  },
  hex: hex,
  props: (c) => {
    const p = c.properties;
    return (p.read ? 0x02 : 0) | (p.writeWithoutResponse ? 0x04 : 0) | (p.write ? 0x08 : 0)
         | (p.notify ? 0x10 : 0) | (p.indicate ? 0x20 : 0);
  },
  listen: (target, type, cb) => {
    const f = (e) => cb(type === "characteristicvaluechanged" ? hex(e.target.value) : "");
    target.addEventListener(type, f);
    return f;
  },
  unlisten: (target, type, f) => target.removeEventListener(type, f),
  errorName: (e) => (e && e.name) ? String(e.name) : "",
  errorMessage: (e) => (e && e.message) ? String(e.message) : String(e),
  isNull: (v) => v === null || v === undefined,
  length: (a) => a.length,
  item: (a, i) => a[i],
};
"""

_helpers = None


def _h():
    global _helpers
    if _helpers is None:
        if js is None:
            raise UnsupportedError("bledev.webble needs a browser: PyScript, Pyodide or MicroPython WebAssembly")
        _helpers = js.Function.new(_HELPERS_JS)()
    return _helpers


def available():
    """True when this page can use Web Bluetooth."""
    if js is None:
        return False
    try:
        return bool(_h().available())
    except Exception:
        return False


def _to_js_bytes(data):
    return _h().toBytes(bytes(data).hex())


def _from_hex(text):
    return bytes.fromhex(str(text))


def _items(array):
    h = _h()
    return [h.item(array, i) for i in range(int(h.length(array)))]


def _proxy(fn):
    return create_proxy(fn) if create_proxy is not None else fn


# ---------------------------------------------------------------- errors


def _error_parts(e):
    """(name, message) of a JavaScript error, from either runtime's exception."""
    name = ""
    message = ""
    for holder in (e, getattr(e, "js_error", None)):
        if holder is None:
            continue
        try:
            n = getattr(holder, "name", None)
            if n and isinstance(n, str) and not name:
                name = n
            m = getattr(holder, "message", None)
            if m and isinstance(m, str) and not message:
                message = m
        except Exception:
            pass
    if not name and getattr(e, "args", None):
        # MicroPython: JsException(error, name, message)
        args = e.args
        if len(args) >= 2 and isinstance(args[1], str):
            name = args[1]
        if len(args) >= 3 and isinstance(args[2], str):
            message = args[2]
    text = str(e)
    if not name:
        head = text.split(":", 1)[0].strip()
        if head.endswith("Error") and " " not in head:
            name = head
    return name, message or text


def _is_js_error(e):
    return type(e).__name__ in ("JsException", "JsError") or hasattr(e, "js_error")


def _translate(e, what, connection=None):
    """A bledev error for the JavaScript error ``e``, or ``None`` to re-raise it."""
    if isinstance(e, BLEError):
        return e
    if not _is_js_error(e):
        return None
    name, message = _error_parts(e)
    detail = "{}: {} ({})".format(what, message, name or "Error")
    if connection is not None and not connection.is_connected():
        return DisconnectedError(detail)
    if name == "NetworkError":
        # Chrome's word for a dropped link, and for a GATT request that failed
        # on the air. The disconnect event may lag the rejection by a moment.
        if "disconnect" in message.lower():
            return DisconnectedError(detail)
        return GattError(0, detail)
    if name == "NotSupportedError":
        return UnsupportedError(detail)
    if name == "NotAllowedError" and "gatt" in message.lower():
        return GattError(0, detail)
    return BLEError(detail)


async def _settle(promise):
    # MicroPython's asyncio only wraps coroutines in tasks, and a JS promise
    # isn't one, so wait_for() needs this around it.
    return await promise


async def _await(promise, what, connection=None, timeout_ms=None):
    try:
        if timeout_ms is None:
            return await promise
        return await wait_ms(_settle(promise), timeout_ms, what)
    except BLETimeoutError:
        raise
    except Exception as e:
        err = _translate(e, what, connection)
        if err is None:
            raise
        raise err


# ---------------------------------------------------------------- the adapter


class WebBLE(BLE):
    """The browser's Bluetooth, through ``navigator.bluetooth``. Central only.

    ``services`` lists the service UUIDs your page will use beyond those it
    passes to ``find()``: the browser hides every service it wasn't told
    about. ``mtu`` is the ATT MTU writes are sized to (see the module notes);
    leave it at 23 unless you know the link negotiated more. ``queue_limit``
    bounds each notification queue.
    """

    backend = "webble"

    #: How many times ``connect()`` tries before a failed connection attempt
    #: is raised. ``connect_retries`` counts the extra tries made.
    CONNECT_ATTEMPTS = 3

    def __init__(self, *, services=(), mtu=DEFAULT_MTU, queue_limit=512):
        if not available():
            raise UnsupportedError(
                "this browser has no Web Bluetooth: use Chrome or Edge on desktop or "
                "Android, from https:// or http://localhost"
            )
        self.bluetooth = js.navigator.bluetooth
        self.optional_services = [UUID(s) for s in services]
        self.link_mtu = int(mtu)
        self.queue_limit = queue_limit
        self._requested_mtu = DEFAULT_MTU
        self._gap_name = None
        self._connections = []
        self.connect_retries = 0

    def capabilities(self):
        caps = BLE.capabilities(self)
        caps.update(
            central=True,
            peripheral=False,
            mtu=self.link_mtu,
            max_mtu=MAX_MTU,
            indicate=True,
        )
        return caps

    def config(self, *names, **settings):
        # The browser negotiates the MTU on its own and never says what it
        # got, so an MTU set here is recorded, not used; see WebBLE(mtu=...).
        for key, value in settings.items():
            if key == "mtu":
                self._requested_mtu = int(value)
            else:
                raise UnsupportedError("webble has no setting {!r}".format(key))
        if names:
            if len(names) != 1:
                raise ValueError("read one setting at a time")
            if names[0] == "mtu":
                return self._requested_mtu
            raise UnsupportedError("webble has no setting {!r}".format(names[0]))
        return None

    def close(self):
        for connection in list(self._connections):
            connection._drop()
        self._connections = []

    # -- central

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        raise UnsupportedError(
            "browsers don't scan for pages; find() opens the browser's device chooser instead"
        )

    def _request_options(self, name, service):
        filters = []
        if name is not None or service is not None:
            f = {}
            # Chrome on Android matches a name filter only against the
            # advertisement itself, never the scan response, and a board that
            # advertises a 128-bit service (nus does) has its name pushed into
            # the scan response. So with a service to filter on, filter on that
            # alone; the chooser still shows names, and find() checks the pick.
            if name is not None and service is None:
                f["name"] = name
            if service is not None:
                f["services"] = [str(UUID(service))]
            filters.append(f)
        optional = [str(u) for u in self.optional_services]
        if service is not None and str(UUID(service)) not in optional:
            optional.append(str(UUID(service)))
        options = {"optionalServices": optional}
        if filters:
            options["filters"] = filters
        else:
            options["acceptAllDevices"] = True
        return js.JSON.parse(json.dumps(options))

    async def find(self, name=None, service=None, *, timeout_ms=10000, active=True):
        """Open the browser's device chooser and return the :class:`Device` picked.

        The chooser lists devices matching ``name`` and/or ``service`` (all
        devices if neither), and ``service`` becomes reachable once connected.
        Given both, the chooser filters on ``service`` alone and the pick must
        carry ``name``, because Chrome on Android can't match a name that
        only a scan response carries. A name-only ``find()`` works there only
        if the board's name fits in its advertisement.
        Call it from a click or a tap: the browser refuses otherwise.
        ``timeout_ms`` doesn't apply, because a person is choosing. Closing
        the chooser without choosing raises :class:`BLETimeoutError`, as a
        scan that found nothing does.
        """
        options = self._request_options(name, service)
        try:
            native = await self.bluetooth.requestDevice(options)
        except Exception as e:
            ename, message = _error_parts(e)
            if ename == "NotFoundError":
                raise BLETimeoutError("no device chosen: {}".format(message))
            if ename == "SecurityError":
                raise BLEError(
                    "the browser refused to open its device chooser ({}). Call find() "
                    "from a click or tap handler, on https:// or localhost".format(message)
                )
            err = _translate(e, "requestDevice")
            if err is None:
                raise
            raise err
        dev_name = native.name
        dev_name = None if _h().isNull(dev_name) else str(dev_name)
        if name is not None and service is not None and dev_name != name:
            raise BLEError("the chooser returned {!r}, not {!r}".format(dev_name, name))
        return Device(self, str(native.id), name=dev_name, native=native)

    async def _connect(self, device, timeout_ms, **options):
        native = device.native
        if native is None:
            raise BLEError("a browser can only connect to a device its chooser returned")
        # A first connection attempt often fails at the link layer on Android
        # (status 133, HCI 0x3E "failed to be established"); measured on the
        # P4 through its C6 it was about half of them, and the next attempt
        # usually works. So try again, up to CONNECT_ATTEMPTS in all.
        attempt = 0
        while True:
            attempt += 1
            connection = _WebConnection(self, device, native)
            try:
                await connection._open(timeout_ms)
            except GattError as e:
                if attempt >= self.CONNECT_ATTEMPTS or "Connection attempt failed" not in str(e):
                    raise
                self.connect_retries += 1
                continue
            self._connections.append(connection)
            return connection


class _WebConnection(Connection):
    def __init__(self, ble, device, native):
        Connection.__init__(self, ble, device, "central")
        self._native = native
        self._server = None
        self._down = asyncio.Event()
        self._closed = False
        self._characteristics = []
        self._lock = asyncio.Lock()
        self._mtu = ble.link_mtu
        self._on_disconnect = _proxy(self._disconnected_event)
        self._listener = None

    def _disconnected_event(self, *args):
        self._drop()

    def _drop(self):
        if self._closed:
            return
        self._closed = True
        self._down.set()
        for characteristic in self._characteristics:
            characteristic._wake()
        try:
            _h().unlisten(self._native, "gattserverdisconnected", self._listener)
        except Exception:
            pass
        try:
            self._ble._connections.remove(self)
        except ValueError:
            pass

    async def _open(self, timeout_ms):
        self._listener = _h().listen(self._native, "gattserverdisconnected", self._on_disconnect)
        try:
            self._server = await _await(self._native.gatt.connect(), "connect", None, timeout_ms)
        except BLETimeoutError:
            try:
                self._native.gatt.disconnect()
            except Exception:
                pass
            self._drop()
            raise
        except BaseException:
            self._drop()
            raise

    def is_connected(self):
        if self._closed or self._server is None:
            return False
        try:
            return bool(self._native.gatt.connected)
        except Exception:
            return False

    async def disconnect(self, timeout_ms=2000):
        if not self._closed:
            try:
                self._native.gatt.disconnect()
            except Exception:
                pass
            # Chrome fires gattserverdisconnected for a local disconnect too,
            # but don't depend on it.
            try:
                await wait_ms(self._down.wait(), timeout_ms, "disconnect")
            except BLETimeoutError:
                pass
            self._drop()

    async def disconnected(self, timeout_ms=None):
        if not self._closed:
            await wait_ms(self._down.wait(), timeout_ms, "disconnected")

    def _live(self, what):
        if not self.is_connected():
            raise DisconnectedError("{}: not connected".format(what))

    async def _gatt(self, promise_fn, what, timeout_ms=None):
        # Chrome rejects a second GATT operation while one is in flight
        # ("GATT operation already in progress"), so run them one at a time.
        self._live(what)
        async with self._lock:
            self._live(what)
            return await _await(promise_fn(), what, self, timeout_ms)

    async def _discover_services(self, uuid, timeout_ms):
        server = self._server
        try:
            if uuid is None:
                found = await self._gatt(lambda: server.getPrimaryServices(), "service discovery", timeout_ms)
            else:
                found = await self._gatt(
                    lambda: server.getPrimaryServices(str(uuid)), "service discovery", timeout_ms
                )
        except BLEError as e:
            # Nothing matching, or a service the page didn't ask for: the
            # browser's two ways of saying there is none it will show us.
            if "NotFoundError" in str(e):
                return []
            if "SecurityError" in str(e):
                raise BLEError(
                    "{} (list the service in find()'s filter or WebBLE(services=[...]))".format(e)
                )
            raise
        # Browsers expose no handles. Chrome returns services in discovery
        # order, which is the server's.
        return [_WebClientService(self, s) for s in _items(found)]


class _WebClientService(ClientService):
    def __init__(self, connection, native):
        ClientService.__init__(self, connection, str(native.uuid))
        self._native = native

    async def _discover_characteristics(self, uuid, timeout_ms):
        native = self._native
        try:
            if uuid is None:
                found = await self.connection._gatt(
                    lambda: native.getCharacteristics(), "characteristic discovery", timeout_ms
                )
            else:
                found = await self.connection._gatt(
                    lambda: native.getCharacteristics(str(uuid)), "characteristic discovery", timeout_ms
                )
        except BLEError as e:
            if "NotFoundError" in str(e):
                return []
            raise
        return [_WebClientCharacteristic(self, c) for c in _items(found)]


class _WebClientCharacteristic(ClientCharacteristic):
    def __init__(self, service, native):
        ClientCharacteristic.__init__(self, service, str(native.uuid), int(_h().props(native)))
        self._native = native
        self._notify_queue = []
        self._indicate_queue = []
        self._overrun = 0
        self._event = asyncio.Event()
        self._listener = None
        self._on_value = _proxy(self._value_event)
        self._route_indications = False
        service.connection._characteristics.append(self)

    def _value_event(self, text):
        queue = self._indicate_queue if self._route_indications else self._notify_queue
        if len(queue) >= self.connection._ble.queue_limit:
            self._overrun += 1
        else:
            queue.append(_from_hex(text))
        self._event.set()

    def _wake(self):
        self._event.set()

    async def read(self, timeout_ms=1000):
        self._check(FLAG_READ, "read")
        native = self._native
        view = await self.connection._gatt(lambda: native.readValue(), "read", timeout_ms)
        return _from_hex(_h().hex(view))

    async def write(self, data, response=None, timeout_ms=1000):
        data = bytes(data)
        response = self._want_response(response)
        self.connection._live("write")
        limit = self.connection.mtu - 3
        if len(data) > limit:
            raise BLEError(
                "write of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), limit, self.connection.mtu
                )
            )
        native = self._native
        value = _to_js_bytes(data)
        if response:
            await self.connection._gatt(lambda: native.writeValueWithResponse(value), "write", timeout_ms)
        else:
            await self.connection._gatt(lambda: native.writeValueWithoutResponse(value), "write", timeout_ms)

    async def subscribe(self, notify=True, indicate=False):
        if notify:
            self._check(FLAG_NOTIFY, "notify")
        if indicate:
            self._check(FLAG_INDICATE, "indicate")
        if notify and indicate:
            raise UnsupportedError(
                "a browser subscribes to notifications or indications, not both"
            )
        native = self._native
        if not notify and not indicate:
            await self.connection._gatt(lambda: native.stopNotifications(), "unsubscribe")
            if self._listener is not None:
                _h().unlisten(native, "characteristicvaluechanged", self._listener)
                self._listener = None
            return
        if notify is False and self.properties & FLAG_NOTIFY:
            # startNotifications() picks notifications whenever the
            # characteristic has them, so it can't be asked for indications.
            raise UnsupportedError("a browser can't choose indications on a characteristic that also notifies")
        self._route_indications = not notify
        # Listen first, so nothing that arrives as the subscription lands is lost.
        if self._listener is None:
            self._listener = _h().listen(native, "characteristicvaluechanged", self._on_value)
        await self.connection._gatt(lambda: native.startNotifications(), "subscribe")

    async def _next(self, queue, timeout_ms, what):
        if timeout_ms is None:
            return await self._take(queue, what)
        return await wait_ms(self._take(queue, what), timeout_ms, what)

    async def _take(self, queue, what):
        while True:
            if self._overrun:
                raise BLEError(
                    "{} queue for {} overran: {} dropped because the reader fell {} behind".format(
                        what, self.uuid, self._overrun, self.connection._ble.queue_limit
                    )
                )
            if queue:
                return queue.pop(0)
            if not self.connection.is_connected():
                raise DisconnectedError("{}: disconnected".format(what))
            self._event.clear()
            await self._event.wait()

    async def notified(self, timeout_ms=None):
        self._check(FLAG_NOTIFY, "notify")
        return await self._next(self._notify_queue, timeout_ms, "notified")

    async def indicated(self, timeout_ms=None):
        self._check(FLAG_INDICATE, "indicate")
        return await self._next(self._indicate_queue, timeout_ms, "indicated")
