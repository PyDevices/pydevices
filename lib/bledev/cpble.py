"""CircuitPython backend, over ``_bleio``. Both roles.

    import bledev.cpble
    ble = bledev.cpble.get()       # the board's one radio, shared

Needs CircuitPython with ``_bleio`` (every nRF52, and every ESP32 with BLE
except the S2), and the ``asyncio`` library from the Adafruit bundle
(``circup install asyncio``, which brings ``adafruit_ticks``).

``_bleio`` is the model furthest from aioble's. aioble hands you events;
``_bleio`` hands you objects you poll: a connection's ``connected`` flag,
a buffer a characteristic's writes land in, a scan's iterator. So this backend
turns each wait into a short poll of those objects (every
:data:`POLL_MS`), and a few things work differently from the other backends:

* **Some calls block the event loop.** ``_bleio`` has no async API. Connecting,
  service discovery, a read, a write with response and a subscription each
  wait inside ``_bleio`` until the radio answers, usually one or two
  connection intervals, and nothing else in asyncio runs meanwhile. A scan
  runs in slices of :data:`SCAN_SLICE_MS` for the same reason.
* **Writes land in ring buffers** that CircuitPython fills from the radio's
  task. A characteristic you can notify on gets a ``PacketBuffer``, which
  keeps each write whole but only takes writes from the central that
  subscribed, after it subscribed. Any other writable characteristic gets a
  ``CharacteristicBuffer``, a byte stream: with ``capture=True`` each
  ``written()`` returns whatever bytes arrived since the last, not one write.
  Both drop the oldest data when full and don't say so, so read them promptly;
  the stream buffer's fill is checked and a full one raises.
* **One notification in flight per characteristic.** ``notify()`` raises
  :class:`BusyError` while the previous one is still waiting for the radio;
  every async sender (nus, midi) waits and tries again. That's how this backend
  steps around a stall in CircuitPython 10.3's ``PacketBuffer`` (see
  :meth:`_CPServerCharacteristic._send`), and it also keeps each notification
  whole, where ``PacketBuffer`` would otherwise merge two into one.
* **Setting a value notifies.** ``Characteristic.write(data)`` on a
  characteristic with notify or indicate sends it to every subscribed central,
  whatever ``send_update`` says, because that's what ``_bleio`` does.
* **Indications** go out, but ``indicate()`` returns once they're queued:
  ``_bleio`` doesn't report the acknowledgement. A central here can't receive
  indications at all (CircuitPython's ESP32 port ignores them), so
  ``capabilities()["indicate"]`` is False.
* **Pairing is "just works" only.** CircuitPython's ESP32 port has no passkey
  or numeric comparison (``authenticated=True`` raises
  :class:`UnsupportedError`), and it always bonds. Its MTU is fixed at build
  time (256 on the ESP32 port), so ``config(mtu=...)`` is unsupported; both
  sides exchange at connect.
* **A peripheral doesn't learn the central's address.** ``_bleio`` doesn't
  expose it, so ``connection.device.address`` is ``"central"``.
* **The GATT server allows ten characteristics per service and two
  descriptors per characteristic**, on the ESP32 port.

The ``_bleio`` objects are there when you need them: ``ble.raw`` is
``_bleio.adapter`` and ``connection.native`` a ``_bleio.Connection``.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import _bleio

from . import (
    BLE,
    BLEError,
    BLETimeoutError,
    BusyError,
    ClientCharacteristic,
    ClientDescriptor,
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
    INSUFFICIENT_AUTHENTICATION,
    INSUFFICIENT_ENCRYPTION,
    PairingError,
    ScanResult,
    Scanner,
    UnsupportedError,
    UUID,
    decode_advertisement,
    decode_service_data,
    pack_advertisement,
    sleep_ms,
)

#: How often a wait looks at ``_bleio``'s objects, in milliseconds.
POLL_MS = 5

#: How long, in milliseconds, a characteristic keeps retrying its last
#: notification after sending it. See :meth:`_CPServerCharacteristic._send`.
RETRY_MS = 5000

#: How long one slice of a scan blocks the event loop, in milliseconds.
SCAN_SLICE_MS = 100

#: The largest attribute value ``_bleio`` holds (``BLE_ATT_ATTR_MAX_LEN``).
_MAX_VALUE = 512

#: The largest ATT payload a peer can send here: CircuitPython's ESP32 port
#: asks for an MTU of 256.
_MAX_PAYLOAD = 253

#: The MTU this backend reports, and sends by: 247, one link-layer packet,
#: even when the link agreed 256. A 253-byte notification is split into two
#: packets below NimBLE's ATT layer, which needs buffers the pool may not
#: have, and when NimBLE refuses a notification, CircuitPython 10.3's
#: PacketBuffer switches to a second outgoing buffer it never allocated for
#: notifications, and the next write faults the board (seen: a hard fault in
#: the nus gate, the board restarting in safe mode).
_MAX_MTU = 247

# How long a write without response keeps retrying a full buffer by default.
_WRITE_RETRY_MS = 2000

try:
    from supervisor import ticks_ms as _ticks_ms
except ImportError:  # pragma: no cover - CPython tests with a stub _bleio
    import time as _time

    def _ticks_ms():
        return int(_time.monotonic() * 1000) & _TICKS_MASK


# supervisor.ticks_ms() wraps at 2**29.
_TICKS_MASK = (1 << 29) - 1


def _elapsed(since):
    return (_ticks_ms() - since) & _TICKS_MASK


def _cuuid(uuid):
    """bledev UUID -> _bleio.UUID."""
    uuid = UUID(uuid)
    short = uuid.short
    if short is not None and short <= 0xFFFF:
        return _bleio.UUID(short)
    return _bleio.UUID(str(uuid))


def _uuid(cuuid):
    """_bleio.UUID -> bledev UUID."""
    if cuuid.size == 16:
        return UUID(cuuid.uuid16)
    return UUID(bytes(cuuid.uuid128))


# _bleio's property bits are the Bluetooth spec's, as bledev's are; map them
# by name anyway, so a port that numbers them differently still works.
_PROPS = (
    (FLAG_READ, "READ"),
    (FLAG_WRITE, "WRITE"),
    (FLAG_WRITE_NO_RESPONSE, "WRITE_NO_RESPONSE"),
    (FLAG_NOTIFY, "NOTIFY"),
    (FLAG_INDICATE, "INDICATE"),
)


def _to_cprops(flags):
    props = 0
    for flag, name in _PROPS:
        if flags & flag:
            props |= getattr(_bleio.Characteristic, name)
    return props


def _from_cprops(props):
    flags = 0
    for flag, name in _PROPS:
        if props & getattr(_bleio.Characteristic, name):
            flags |= flag
    return flags


def _translate(e, what):
    """A bledev error for an exception ``_bleio`` raised, or ``None``."""
    if isinstance(e, BLEError):
        return e
    if isinstance(e, ConnectionError):
        return DisconnectedError("{}: not connected".format(what))
    if isinstance(e, TimeoutError):
        return BLETimeoutError("{} timed out".format(what))
    if isinstance(e, MemoryError):
        return BusyError("{}: the radio's buffers are full".format(what))
    security = getattr(_bleio, "SecurityError", None)
    if security is not None and isinstance(e, security):
        text = str(e).lower()
        status = INSUFFICIENT_AUTHENTICATION if "authentication" in text else INSUFFICIENT_ENCRYPTION
        return GattError(status, "{}: {}".format(what, e))
    if isinstance(e, _bleio.BluetoothError):
        # A read or write that the peer refused comes back as NimBLE's
        # "Unknown system firmware error: 261", 0x100 plus the ATT code,
        # because _bleio checks that status as a NimBLE error.
        text = str(e)
        tail = text.rsplit(" ", 1)[-1]
        try:
            code = int(tail)
        except ValueError:
            code = None
        if code is not None and 0x100 <= code < 0x200:
            return GattError(code - 0x100, "{}: ATT error 0x{:02x}".format(what, code - 0x100))
        return BLEError("{}: {}".format(what, text))
    return None


class _Call:
    """``with _Call("read"):`` turns ``_bleio``'s exceptions into bledev's."""

    def __init__(self, what):
        self._what = what

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            return False
        error = _translate(exc, self._what)
        if error is not None and error is not exc:
            raise error
        return False


_shared = None


def get(adapter=None):
    """The shared :class:`CPBLE` for this board's radio, made on first use."""
    global _shared
    if _shared is None:
        _shared = CPBLE(adapter)
    return _shared


class CPBLE(BLE):
    """The board's radio, ``_bleio.adapter`` unless you pass another.

    ``queue_limit`` bounds each notification and capture queue, and sizes the
    packet buffers ``_bleio`` fills. ``stream_buffer`` is the byte size of the
    buffer behind a write-only characteristic with ``capture=True`` (nus's RX):
    what arrives while your code doesn't read. Prefer :func:`get`.
    """

    backend = "cpble"

    def __init__(self, adapter=None, *, queue_limit=64, stream_buffer=32768):
        self.raw = adapter if adapter is not None else _bleio.adapter
        if self.raw is None:
            raise UnsupportedError("this board has no BLE adapter (_bleio.adapter is None)")
        if not self.raw.enabled:
            self.raw.enabled = True
        self.queue_limit = queue_limit
        self.stream_buffer = stream_buffer
        self._services = ()
        self._native_services = []
        # _bleio.Connection -> _CPConnection. _bleio hands out one object per
        # link, so identity is enough.
        self._connections = {}

    def capabilities(self):
        caps = BLE.capabilities(self)
        caps.update(
            central=True,
            peripheral=True,
            mtu=_MAX_MTU,
            max_mtu=_MAX_MTU,
            indicate=False,
            pairing=True,
            long_read=False,
        )
        return caps

    def config(self, *names, **settings):
        for key, value in settings.items():
            if key == "gap_name":
                self.raw.name = value
            elif key == "mtu":
                if value != _MAX_MTU:
                    raise UnsupportedError(
                        "CircuitPython's MTU is fixed when it's built ({} here)".format(_MAX_MTU)
                    )
            else:
                raise UnsupportedError("cpble has no setting {!r}".format(key))
        if names:
            if len(names) != 1:
                raise ValueError("read one setting at a time")
            name = names[0]
            if name == "mtu":
                return _MAX_MTU
            if name == "gap_name":
                return self.raw.name
            raise UnsupportedError("cpble has no setting {!r}".format(name))
        return None

    def close(self):
        try:
            self.raw.stop_advertising()
        except Exception:
            pass
        try:
            self.raw.stop_scan()
        except Exception:
            pass
        for native in tuple(self.raw.connections):
            try:
                native.disconnect()
            except Exception:
                pass
        self._connections = {}

    def enable_bonding(self, store=None):
        """CircuitPython always bonds and keeps the keys itself (in NVS on an
        ESP32), so this only accepts the call. ``forget_bonds()`` erases them."""

    def forget_bonds(self):
        """Erase every bond this board holds (``_bleio.adapter.erase_bonding()``)."""
        self.raw.erase_bonding()

    # -- connections

    def _wrap(self, native, role, device=None):
        conn = self._connections.get(native)
        if conn is None:
            if len(self._connections) > 8:
                for key in list(self._connections):
                    if not self._connections[key].is_connected():
                        del self._connections[key]
            if device is None:
                device = Device(self, "central")
            conn = _CPConnection(self, device, role, native)
            self._connections[native] = conn
        return conn

    def _current(self):
        """The live peripheral-side connection a write most likely came from.

        ``_bleio`` doesn't say which central wrote, so with more than one this
        is the most recent one still connected."""
        found = None
        for native in self.raw.connections:
            conn = self._connections.get(native)
            if conn is not None and conn.role == "peripheral" and conn.is_connected():
                found = conn
        if found is None:
            for native in self.raw.connections:
                found = self._connections.get(native) or found
        return found

    # -- peripheral

    def register_services(self, *services):
        for service in self._services:
            for characteristic in service.characteristics:
                if characteristic._impl is not None:
                    characteristic._impl._release()
                characteristic._impl = None
        for native in self._native_services:
            try:
                native.deinit()
            except Exception:
                pass
        self._native_services = []
        open_ = _bleio.Attribute.OPEN
        for service in services:
            if len(service.characteristics) > 10:
                raise UnsupportedError("CircuitPython serves at most 10 characteristics per service")
            nservice = _bleio.Service(_cuuid(service.uuid))
            self._native_services.append(nservice)
            for c in service.characteristics:
                if c.authenticated:
                    raise UnsupportedError("CircuitPython can't require a passkey (authenticated=True)")
                perm = _bleio.Attribute.ENCRYPT_NO_MITM if c.encrypted else open_
                if len(c.descriptors) > 2:
                    raise UnsupportedError("CircuitPython allows two descriptors per characteristic")
                # Every value gets the largest buffer: max_len is kept here,
                # in Python, as the other backends keep it (a longer write
                # keeps its first max_len bytes). _bleio would refuse the
                # write instead, and a notification can't exceed the value's
                # buffer.
                nchar = _bleio.Characteristic.add_to_service(
                    nservice,
                    _cuuid(c.uuid),
                    properties=_to_cprops(c.flags),
                    read_perm=perm if c.flags & FLAG_READ or c.flags & (FLAG_NOTIFY | FLAG_INDICATE) else open_,
                    write_perm=perm if c.flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE) else _bleio.Attribute.NO_ACCESS,
                    max_length=_MAX_VALUE,
                    fixed_length=False,
                    initial_value=c._initial or b"",
                )
                for d in c.descriptors:
                    _bleio.Descriptor.add_to_characteristic(
                        nchar,
                        _cuuid(d.uuid),
                        read_perm=perm,
                        write_perm=_bleio.Attribute.NO_ACCESS,
                        max_length=max(1, len(d.value)),
                        fixed_length=True,
                        initial_value=d.value or b"\x00",
                    )
                c._impl = _CPServerCharacteristic(self, c, nchar)
        self._services = tuple(services)

    async def advertise(
        self,
        interval_us=100000,
        *,
        name=None,
        services=None,
        appearance=0,
        manufacturer=None,
        connectable=True,
        timeout_ms=None,
        service_data=None,
    ):
        adv_data, resp_data = pack_advertisement(name, services, appearance, manufacturer, service_data)
        if name:
            # The GAP name, which a paired computer lists, is the advertised one.
            self.raw.name = name
        interval = min(10.24, max(0.02, interval_us / 1000000))
        known = set(self.raw.connections)
        if not known:
            # Fresh packet buffers for the next link (see _renew), made
            # before a central can connect and subscribe.
            for service in self._services:
                for c in service.characteristics:
                    if c._impl is not None and c._impl._packets is not None:
                        c._impl._renew()
        try:
            self.raw.stop_advertising()
        except Exception:
            pass
        with _Call("advertise"):
            self.raw.start_advertising(
                adv_data,
                scan_response=resp_data or None,
                connectable=connectable,
                interval=interval,
            )
        start = _ticks_ms()
        try:
            while True:
                for native in self.raw.connections:
                    if native not in known and native.connected:
                        # A connect stops advertising.
                        return self._wrap(native, "peripheral")
                if timeout_ms is not None and _elapsed(start) >= timeout_ms:
                    raise BLETimeoutError("advertise: nobody connected in {} ms".format(timeout_ms))
                await sleep_ms(POLL_MS * 4)
        finally:
            if self.raw.advertising:
                try:
                    self.raw.stop_advertising()
                except Exception:
                    pass

    # -- central

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        return _CPScanner(self, duration_ms, active, interval_us, window_us)

    async def _connect(self, device, timeout_ms, **options):
        address = device.native
        if not isinstance(address, _bleio.Address):
            if device.addr is None:
                raise BLEError("cpble connects by address; {!r} has none".format(device))
            address = _bleio.Address(bytes(reversed(device.addr)), device.addr_type)
        try:
            self.raw.stop_scan()
        except Exception:
            pass
        await sleep_ms(0)
        with _Call("connect"):
            native = self.raw.connect(address, timeout=(timeout_ms or 10000) / 1000)
        if native is None or not native.connected:
            raise BLETimeoutError("connect timed out")
        conn = self._wrap(native, "central", device)
        interval_us = options.get("max_conn_interval_us") or options.get("min_conn_interval_us")
        if interval_us:
            try:
                native.connection_interval = interval_us / 1000
            except Exception:
                pass  # the peripheral may refuse; the link keeps its interval
        return conn


class _CPScanner(Scanner):
    """Runs ``_bleio``'s scan in slices, so the event loop gets a turn between them."""

    def __init__(self, ble, duration_ms, active, interval_us, window_us):
        Scanner.__init__(self, ble, duration_ms, active, interval_us, window_us)
        self._seen = {}
        self._started = None

    async def _start(self):
        self._started = _ticks_ms()

    async def _stop(self):
        try:
            self._ble.raw.stop_scan()
        except Exception:
            pass

    def _slice(self):
        interval = (self.interval_us or 30000) / 1000000
        window = (self.window_us or self.interval_us or 30000) / 1000000
        left = self.duration_ms - _elapsed(self._started)
        if left <= 0:
            self._finish()
            return
        length = min(SCAN_SLICE_MS, left) / 1000
        with _Call("scan"):
            results = self._ble.raw.start_scan(
                timeout=length,
                interval=interval,
                window=min(window, interval),
                active=self.active,
                minimum_rssi=-127,
                buffer_size=2048,
            )
        try:
            for entry in results:
                self._entry(entry)
        finally:
            try:
                self._ble.raw.stop_scan()
            except Exception:
                pass

    def _entry(self, entry):
        raw = bytes(entry.advertisement_bytes)
        key = bytes(entry.address.address_bytes)
        seen = self._seen.get(key)
        if seen is None:
            seen = self._seen[key] = [b"", b"", True]
        if entry.scan_response:
            seen[1] = raw
        else:
            seen[0] = raw
            seen[2] = entry.connectable
        name, services, appearance, manufacturer = decode_advertisement(seen[0], seen[1])
        device = Device(
            self._ble, bytes(reversed(key)), entry.address.type, name=name, native=entry.address
        )
        self._push(
            ScanResult(
                device,
                rssi=entry.rssi,
                name=name,
                services=services,
                appearance=appearance,
                manufacturer=manufacturer,
                connectable=seen[2],
                service_data=decode_service_data(seen[0], seen[1]),
            )
        )

    async def __anext__(self):
        while True:
            if self._queue:
                return self._queue.pop(0)
            if self._done:
                raise StopAsyncIteration
            self._slice()
            await sleep_ms(0)


class _CPConnection(Connection):
    def __init__(self, ble, device, role, native):
        Connection.__init__(self, ble, device, role)
        #: The ``_bleio.Connection``.
        self.native = native
        self._remote = None
        self._last_mtu = DEFAULT_MTU

    @property
    def mtu(self):
        try:
            self._last_mtu = min(self.native.max_packet_length + 3, _MAX_MTU)
        except Exception:
            pass  # disconnected: keep the last value
        return self._last_mtu

    def is_connected(self):
        try:
            return bool(self.native.connected)
        except Exception:
            return False

    async def disconnect(self, timeout_ms=2000):
        if self.is_connected():
            try:
                self.native.disconnect()
            except Exception:
                pass
        await self.disconnected(timeout_ms)

    async def disconnected(self, timeout_ms=None):
        start = _ticks_ms()
        while self.is_connected():
            if timeout_ms is not None and _elapsed(start) >= timeout_ms:
                raise BLETimeoutError("disconnected timed out after {} ms".format(timeout_ms))
            await sleep_ms(POLL_MS * 4)

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        # CircuitPython exchanges at every connect, from either side; wait for
        # the result rather than asking again.
        start = _ticks_ms()
        while self.is_connected() and self.mtu <= DEFAULT_MTU and _elapsed(start) < (timeout_ms or 0):
            await sleep_ms(POLL_MS * 4)
        if not self.is_connected():
            raise DisconnectedError("exchange_mtu: disconnected")
        return self.mtu

    @property
    def encrypted(self):
        try:
            return bool(self.native.paired)
        except Exception:
            return False

    async def pair(self, bond=True, timeout_ms=30000, passkey=None):
        if passkey is not None:
            raise UnsupportedError("CircuitPython pairs only 'just works': no passkey")
        if not bond:
            raise UnsupportedError("CircuitPython always bonds")
        if not self.is_connected():
            raise DisconnectedError("pair: not connected")
        # _bleio's pair() blocks until the link is encrypted; a refusal leaves
        # it waiting, which only a disconnect or Ctrl-C ends.
        with _Call("pair"):
            self.native.pair(bond=True)
        if not self.encrypted:
            if not self.is_connected():
                raise PairingError("pair: the peer hung up")
            raise PairingError("pair: refused")

    async def unpair(self):
        raise UnsupportedError("CircuitPython forgets one peer only by erasing every bond: ble.forget_bonds()")

    def _discover(self):
        if self._remote is None:
            if not self.is_connected():
                raise DisconnectedError("service discovery: not connected")
            with _Call("service discovery"):
                self._remote = [_CPClientService(self, s) for s in self.native.discover_remote_services()]
        return self._remote

    async def _discover_services(self, uuid, timeout_ms):
        await sleep_ms(0)
        return [s for s in self._discover() if uuid is None or s.uuid == uuid]


class _CPClientService(ClientService):
    def __init__(self, connection, native):
        ClientService.__init__(self, connection, _uuid(native.uuid))
        self.native = native
        self._characteristics = None

    async def _discover_characteristics(self, uuid, timeout_ms):
        if self._characteristics is None:
            self._characteristics = [_CPClientCharacteristic(self, c) for c in self.native.characteristics]
        return [c for c in self._characteristics if uuid is None or c.uuid == uuid]


class _CPClientCharacteristic(ClientCharacteristic):
    def __init__(self, service, native):
        ClientCharacteristic.__init__(self, service, _uuid(native.uuid), _from_cprops(native.properties))
        self.native = native
        self._buffer = None
        self._packet = bytearray(_MAX_VALUE)
        self._queue = []
        self._overrun = 0

    def _live(self, what):
        if not self.connection.is_connected():
            raise DisconnectedError("{}: not connected".format(what))

    async def read(self, timeout_ms=1000):
        self._check(FLAG_READ, "read")
        self._live("read")
        await sleep_ms(0)
        with _Call("read"):
            value = self.native.value
        self._live("read")
        return bytes(value)

    async def _discover_descriptors(self, uuid, timeout_ms):
        self._live("descriptor discovery")
        found = [_CPClientDescriptor(self, d) for d in self.native.descriptors]
        return [d for d in found if uuid is None or d.uuid == uuid]

    async def write(self, data, response=None, timeout_ms=1000):
        data = bytes(data)
        response = self._want_response(response)
        if response and self.properties & FLAG_WRITE_NO_RESPONSE:
            # _bleio picks the write type from the properties, and a
            # characteristic that allows both always gets one without.
            raise UnsupportedError(
                "CircuitPython writes {!r} without response; it can't ask for one".format(self)
            )
        self._live("write")
        if len(data) > self.connection.mtu - 3:
            raise BLEError(
                "write of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), self.connection.mtu - 3, self.connection.mtu
                )
            )
        start = _ticks_ms()
        limit = timeout_ms if timeout_ms is not None else _WRITE_RETRY_MS
        while True:
            try:
                with _Call("write"):
                    self.native.value = data
                return
            except BusyError:
                self._live("write")
                if _elapsed(start) >= limit:
                    raise BLETimeoutError("write: buffers stayed full for {} ms".format(limit))
                await sleep_ms(2)
            except BLEError:
                self._live("write")
                raise

    async def subscribe(self, notify=True, indicate=False):
        if indicate:
            raise UnsupportedError("CircuitPython can't receive indications")
        if notify:
            self._check(FLAG_NOTIFY, "notify")
        self._live("subscribe")
        await sleep_ms(0)
        if notify and self._buffer is None:
            # Making the buffer writes the CCCD.
            with _Call("subscribe"):
                self._buffer = _bleio.PacketBuffer(
                    self.native, buffer_size=self.connection._ble.queue_limit, max_packet_size=_MAX_PAYLOAD
                )
        elif not notify and self._buffer is not None:
            self._buffer.deinit()
            self._buffer = None
            with _Call("unsubscribe"):
                self.native.set_cccd(notify=False, indicate=False)

    def _drain(self):
        buffer = self._buffer
        if buffer is None:
            return
        limit = self.connection._ble.queue_limit
        while True:
            try:
                n = buffer.readinto(self._packet)
            except Exception:
                return
            if n <= 0:
                return
            if len(self._queue) >= limit:
                self._overrun += 1
            else:
                self._queue.append(bytes(self._packet[:n]))

    async def notified(self, timeout_ms=None):
        self._check(FLAG_NOTIFY, "notify")
        start = _ticks_ms()
        while True:
            self._drain()
            if self._overrun:
                raise BLEError(
                    "notify {} queue overran: {} dropped because the reader fell behind".format(
                        self.uuid, self._overrun
                    )
                )
            if self._queue:
                return self._queue.pop(0)
            if not self.connection.is_connected():
                raise DisconnectedError("notified: disconnected")
            if timeout_ms is not None and _elapsed(start) >= timeout_ms:
                raise BLETimeoutError("notified timed out after {} ms".format(timeout_ms))
            await sleep_ms(POLL_MS)

    async def indicated(self, timeout_ms=None):
        raise UnsupportedError("CircuitPython can't receive indications")


class _CPClientDescriptor(ClientDescriptor):
    def __init__(self, characteristic, native):
        ClientDescriptor.__init__(self, characteristic, _uuid(native.uuid))
        self.native = native

    async def read(self, timeout_ms=1000):
        if not self.connection.is_connected():
            raise DisconnectedError("read: not connected")
        await sleep_ms(0)
        with _Call("descriptor read"):
            return bytes(self.native.value)


_retrying = []
_retry_task = None


def _retry(impl):
    """Retry ``impl``'s last notification every :data:`POLL_MS` for
    :data:`RETRY_MS`, in case the radio couldn't take it yet."""
    global _retry_task
    impl._sent_at = _ticks_ms()
    if impl not in _retrying:
        _retrying.append(impl)
    if _retry_task is None:
        _retry_task = asyncio.create_task(_retry_loop())


async def _retry_loop():
    global _retry_task
    try:
        while _retrying:
            await sleep_ms(POLL_MS)
            for impl in list(_retrying):
                packets = impl._packets
                if packets is None or _elapsed(impl._sent_at) >= RETRY_MS:
                    _retrying.remove(impl)
                    continue
                try:
                    packets.write(b"")
                except Exception:
                    _retrying.remove(impl)
    finally:
        _retry_task = None


class _CPServerCharacteristic:
    """cpble's half of a :class:`bledev.Characteristic`."""

    def __init__(self, ble, characteristic, native):
        self._ble = ble
        self._char = characteristic
        self.native = native
        self._packets = None  # a PacketBuffer: notifications out, writes in
        self._stream = None  # a CharacteristicBuffer: writes in, as bytes
        self._stream_size = 0
        self._queue = []
        self._overrun = 0
        self._scratch = None
        self._sent_at = 0
        flags = characteristic.flags
        writable = flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE)
        if flags & (FLAG_NOTIFY | FLAG_INDICATE):
            self._renew()
            self._scratch = bytearray(_MAX_PAYLOAD)
        elif writable:
            self._stream_size = ble.stream_buffer if characteristic.capture else 1024
            self._stream = _bleio.CharacteristicBuffer(native, timeout=0, buffer_size=self._stream_size)

    def _renew(self):
        """A fresh PacketBuffer, for each new connection. One that saw NimBLE
        refuse a notification is left pointing at a buffer it never
        allocated (see _MAX_MTU), so none is kept past its link."""
        if self._packets is not None:
            try:
                self._packets.deinit()
            except Exception:
                pass
        writable = self._char.flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE)
        self._packets = _bleio.PacketBuffer(
            self.native, buffer_size=self._ble.queue_limit if writable else 1, max_packet_size=_MAX_PAYLOAD
        )
        self._queue = []
        self._overrun = 0

    def _release(self):
        for buffer in (self._packets, self._stream):
            if buffer is not None:
                try:
                    buffer.deinit()
                except Exception:
                    pass
        self._packets = self._stream = None

    def read(self):
        value = bytes(self.native.value)
        if self._char.flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE):
            return value[: self._char.max_len]
        return value

    def write(self, data, send_update):
        # Setting the value notifies subscribers whatever send_update says.
        self.native.value = data

    def _check_size(self, connection, data):
        if len(data) > connection.mtu - 3:
            raise BLEError(
                "notification of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), connection.mtu - 3, connection.mtu
                )
            )

    def _send(self, connection, data, what):
        if not connection.is_connected():
            raise DisconnectedError("{}: disconnected".format(what))
        if data is None:
            data = bytes(self.native.value)
        self._check_size(connection, data)
        # CircuitPython 10.3's PacketBuffer.write() keeps a packet it couldn't
        # hand to NimBLE (the buffer pool was dry) and retries it only on the
        # next "sent" event, which then never comes; the write after that
        # waits for it forever inside _bleio. Ten notifications back to back
        # were enough. So the packet goes in as the header of an empty write:
        # _bleio copies a header only into an empty packet, and an empty
        # write never waits, but it does retry what's left. 0 back means the
        # previous packet is still there: busy, and it was just retried.
        if self._packets.outgoing_packet_length < 0:
            return  # the central hasn't subscribed: as on every backend, it gets nothing
        with _Call(what):
            n = self._packets.write(b"", header=data)
        if n == 0 and data:
            if not connection.is_connected():
                raise DisconnectedError("{}: disconnected".format(what))
            raise BusyError("{}: the previous packet is still waiting for the radio".format(what))
        if n > 0:
            # It may be the one left waiting; keep retrying it for a while.
            _retry(self)
        if n < 0 and not connection.is_connected():
            raise DisconnectedError("{}: disconnected".format(what))
        # n < 0 on a live link: the central hasn't subscribed, so, as on
        # every backend, it gets nothing.

    def notify(self, connection, data):
        self._send(connection, data, "notify")

    async def indicate(self, connection, data, timeout_ms):
        if not self._char.flags & FLAG_INDICATE:
            raise UnsupportedError("{!r} was not created with indicate=True".format(self._char))
        self._send(connection, data, "indicate")
        await sleep_ms(0)

    def _drain(self):
        """Move what ``_bleio`` buffered into the queue. True if anything came."""
        got = False
        limit = self._ble.queue_limit
        max_len = self._char.max_len
        if self._packets is not None:
            while True:
                try:
                    n = self._packets.readinto(self._scratch)
                except Exception:
                    break
                if n <= 0:
                    break
                got = True
                if len(self._queue) >= limit:
                    self._overrun += 1
                else:
                    self._queue.append(bytes(self._scratch[: min(n, max_len)]))
        elif self._stream is not None:
            waiting = self._stream.in_waiting
            if waiting:
                if waiting >= self._stream_size - 1:
                    # A full ring drops what doesn't fit, silently. Say so.
                    self._overrun += 1
                data = self._stream.read(waiting)
                if data:
                    got = True
                    if len(self._queue) >= limit:
                        self._overrun += 1
                    else:
                        self._queue.append(bytes(data))
        return got

    async def written(self, timeout_ms):
        start = _ticks_ms()
        while True:
            self._drain()
            if self._overrun:
                raise BLEError(
                    "writes to {} overran: {} lost because the reader fell behind".format(
                        self._char.uuid, self._overrun
                    )
                )
            if self._queue:
                data = self._queue.pop(0)
                connection = self._ble._current()
                if self._char.capture:
                    return connection, data
                self._queue = []
                return connection
            if timeout_ms is not None and _elapsed(start) >= timeout_ms:
                raise BLETimeoutError("written timed out after {} ms".format(timeout_ms))
            await sleep_ms(POLL_MS)
