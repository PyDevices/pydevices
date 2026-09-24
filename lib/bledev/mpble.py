"""MicroPython backend, over aioble. Both roles.

    from bledev.mpble import MPBLE
    ble = MPBLE()                  # or MPBLE(bluetooth.BLE()) from a board config

Needs aioble, which isn't frozen into our firmware: install it with
``mip.install("aioble")``, or install ``bledev`` from the PyDevices index, which
brings aioble with it.

aioble owns the one ``bluetooth.BLE()`` object and its IRQ handler, so don't
set ``ble.irq()`` yourself while this backend is in use.

Where aioble would lose data, this backend doesn't:

* aioble keeps one notification per client characteristic and replaces it
  when the next arrives. Here each gets a queue of ``queue_limit`` entries,
  and an overflow raises from ``notified()``.
* aioble's ``capture=True`` shares a ten-entry queue across every
  characteristic and drops the oldest. Here captured writes are read straight
  from the IRQ into a per-characteristic queue of ``queue_limit``.
* ``notify()`` and ``write()`` refuse a payload over ``mtu - 3`` instead of
  letting NimBLE truncate it.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import bluetooth
import aioble
from aioble import core as _aioble_core
from aioble.device import DeviceConnection as _AioConnection

from . import (
    BLE,
    BLEError,
    BLETimeoutError,
    BusyError,
    ClientCharacteristic,
    ClientService,
    Connection,
    DEFAULT_MTU,
    Device,
    DisconnectedError,
    FLAG_INDICATE,
    FLAG_NOTIFY,
    FLAG_READ,
    GattError,
    ScanResult,
    Scanner,
    UnsupportedError,
    UUID,
    sleep_ms,
)

_IRQ_GATTS_WRITE = 3

# errno values NimBLE uses when its buffers are full (ENOMEM, EAGAIN, EBUSY,
# ENOBUFS). A send that sees one of these waits and tries again.
_BUSY_ERRNOS = (12, 11, 16, 105)

# The largest ATT MTU MicroPython's NimBLE will negotiate.
_MAX_MTU = 512

# Default scan interval and window: listen all the time.
_SCAN_US = 30000

# How long a write without response keeps retrying a full buffer by default.
_WRITE_RETRY_MS = 2000


def _buuid(uuid):
    """bledev UUID -> bluetooth.UUID."""
    uuid = UUID(uuid)
    short = uuid.short
    if short is not None and short <= 0xFFFF:
        return bluetooth.UUID(short)
    return bluetooth.UUID(str(uuid))


def _uuid(buuid):
    """bluetooth.UUID -> bledev UUID."""
    return UUID(bytes(buuid))


def _errno(e):
    return e.args[0] if e.args else None


class _Queue:
    """Stands in for aioble's one-slot deque: same three operations, but it
    keeps ``limit`` entries and turns an overflow into an error."""

    def __init__(self, limit, what):
        self._items = []
        self._limit = limit
        self._what = what
        self.overrun = 0

    def __len__(self):
        return len(self._items)

    def append(self, item):
        if len(self._items) >= self._limit:
            self.overrun += 1
        else:
            self._items.append(item)

    def popleft(self):
        if self.overrun:
            raise BLEError(
                "{} queue overran: {} dropped because the reader fell {} behind".format(
                    self._what, self.overrun, self._limit
                )
            )
        return self._items.pop(0)


class _Translate:
    """Maps aioble's exceptions onto bledev's."""

    def __init__(self, what):
        self._what = what

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            return False
        if exc_type is asyncio.TimeoutError or issubclass(exc_type, asyncio.TimeoutError):
            raise BLETimeoutError("{} timed out".format(self._what))
        if issubclass(exc_type, aioble.DeviceDisconnectedError):
            raise DisconnectedError("{}: disconnected".format(self._what))
        if issubclass(exc_type, aioble.GattError):
            raise GattError(getattr(exc, "_status", 0))
        if exc_type is ValueError and exc.args and exc.args[0] == "Not connected":
            raise DisconnectedError("{}: not connected".format(self._what))
        return False


# Captured characteristics by value handle, for the IRQ handler. Module-level
# because there is one radio however many MPBLE objects wrap it.
_captures = {}
_irq_registered = False
_shared = None


def _irq(event, data):
    # Runs beside aioble's own handlers. A captured write is copied here, in
    # the IRQ, before the next write can overwrite the value buffer, and tied
    # to its connection while that connection still exists.
    if event == _IRQ_GATTS_WRITE:
        conn_handle, value_handle = data
        impl = _captures.get(value_handle)
        if impl is not None:
            impl._captured(
                _AioConnection._connected.get(conn_handle),
                bytes(_aioble_core.ble.gatts_read(value_handle)),
            )
    return None


def get(ble=None):
    """The shared :class:`MPBLE` for this board's radio, made on first use."""
    global _shared
    if _shared is None:
        _shared = MPBLE(ble)
    return _shared


class MPBLE(BLE):
    """The board's radio. ``ble`` may be a ``bluetooth.BLE()``; there is only one.

    ``queue_limit`` bounds each notification and capture queue. Prefer
    :func:`get`, which returns one shared adapter.
    """

    backend = "mpble"

    def __init__(self, ble=None, *, queue_limit=128, mtu=None):
        global _irq_registered
        if ble is not None and ble is not _aioble_core.ble:
            raise BLEError("MicroPython has one bluetooth.BLE(); pass that one or nothing")
        self.raw = _aioble_core.ble
        self.queue_limit = queue_limit
        self._connections = {}
        self._services = ()
        if not _irq_registered:
            _aioble_core.register_irq_handler(_irq, None)
            _irq_registered = True
        if mtu:
            self.config(mtu=mtu)

    def capabilities(self):
        caps = BLE.capabilities(self)
        caps.update(
            central=True,
            peripheral=True,
            mtu=self._config_mtu(),
            max_mtu=_MAX_MTU,
            indicate=True,
            pairing=True,
        )
        return caps

    def _config_mtu(self):
        try:
            return aioble.config("mtu")
        except Exception:
            return DEFAULT_MTU

    def config(self, *names, **settings):
        if settings:
            aioble.config(**settings)
        if names:
            if len(names) != 1:
                raise ValueError("read one setting at a time")
            return aioble.config(names[0])
        return None

    def close(self):
        aioble.stop()
        self._connections = {}

    # -- connections, one wrapper per aioble connection

    def _wrap(self, aconn, role, device=None):
        # Keep recent wrappers after a disconnect: captured writes that raced
        # it still name their connection by this object.
        if len(self._connections) > 8:
            for key in list(self._connections):
                if not key.is_connected():
                    del self._connections[key]
        conn = self._connections.get(aconn)
        if conn is None:
            if device is None:
                device = Device(self, aconn.device.addr, aconn.device.addr_type, native=aconn.device)
            conn = _MPConnection(self, device, role, aconn)
            self._connections[aconn] = conn
        return conn

    def _lookup(self, aconn):
        if aconn is None:
            return None
        return self._connections.get(aconn) or self._wrap(aconn, "peripheral")

    # -- peripheral

    def register_services(self, *services):
        aservices = []
        for service in self._services:
            for characteristic in service.characteristics:
                characteristic._impl = None
        for service in services:
            aservice = aioble.Service(_buuid(service.uuid))
            for c in service.characteristics:
                f = c.flags
                achar = aioble.BufferedCharacteristic(
                    aservice,
                    _buuid(c.uuid),
                    read=bool(f & FLAG_READ),
                    write=bool(f & 0x0008),
                    write_no_response=bool(f & 0x0004),
                    notify=bool(f & FLAG_NOTIFY),
                    indicate=bool(f & FLAG_INDICATE),
                    initial=c._initial,
                    max_len=c.max_len,
                )
                c._impl = _MPServerCharacteristic(self, c, achar)
            aservices.append(aservice)
        aioble.register_services(*aservices)
        self._services = tuple(services)
        _captures.clear()
        for service in services:
            for c in service.characteristics:
                if c.capture:
                    _captures[c._impl._achar._value_handle] = c._impl

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
    ):
        with _Translate("advertise"):
            aconn = await aioble.advertise(
                interval_us,
                name=name.encode() if isinstance(name, str) else name,
                services=[_buuid(s) for s in services] if services else None,
                appearance=appearance,
                manufacturer=manufacturer,
                connectable=connectable,
                timeout_ms=timeout_ms,
            )
        if aconn is None:
            # aioble swallows the cancellation; pass it on.
            raise asyncio.CancelledError()
        return self._wrap(aconn, "peripheral")

    # -- central

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        # aioble's defaults (1.28 s interval, 11.25 ms window) listen less
        # than 1 % of the time, and on the bench found one advertiser in six
        # seconds where a full-duty scan found the board 40 times. Scans here
        # are short and foreground, so listen continuously unless told not to.
        if interval_us is None:
            interval_us = _SCAN_US
        if window_us is None:
            window_us = interval_us
        return _MPScanner(self, duration_ms, active, interval_us, window_us)

    async def _connect(self, device, timeout_ms, **options):
        adevice = device.native
        if adevice is None:
            adevice = aioble.Device(device.addr_type, device.addr or device.address)
        with _Translate("connect"):
            aconn = await adevice.connect(
                timeout_ms=timeout_ms,
                min_conn_interval_us=options.get("min_conn_interval_us"),
                max_conn_interval_us=options.get("max_conn_interval_us"),
            )
        return self._wrap(aconn, "central", device)


class _MPScanner(Scanner):
    async def __aenter__(self):
        self._scan = aioble.scan(
            self.duration_ms,
            interval_us=self.interval_us,
            window_us=self.window_us,
            active=self.active,
        )
        await self._scan.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._scan.__aexit__(exc_type, exc, tb)

    async def cancel(self):
        await self._scan.cancel()

    def __aiter__(self):
        return self

    async def __anext__(self):
        r = await self._scan.__anext__()
        name = r.name()
        adevice = r.device
        device = Device(self._ble, adevice.addr, adevice.addr_type, name=name, native=adevice)
        return ScanResult(
            device,
            rssi=r.rssi,
            name=name,
            services=[_uuid(u) for u in r.services()],
            manufacturer=list(r.manufacturer()),
            connectable=r.connectable,
        )


class _MPConnection(Connection):
    def __init__(self, ble, device, role, aconn):
        Connection.__init__(self, ble, device, role)
        self._aconn = aconn

    @property
    def mtu(self):
        return self._aconn.mtu or DEFAULT_MTU

    def is_connected(self):
        return self._aconn.is_connected()

    async def disconnect(self, timeout_ms=2000):
        with _Translate("disconnect"):
            await self._aconn.disconnect(timeout_ms)

    async def disconnected(self, timeout_ms=None):
        with _Translate("disconnected"):
            await self._aconn.disconnected(timeout_ms)

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        with _Translate("exchange_mtu"):
            return await self._aconn.exchange_mtu(mtu, timeout_ms)

    async def _discover_services(self, uuid, timeout_ms):
        found = []
        with _Translate("service discovery"):
            async for aservice in self._aconn.services(None if uuid is None else _buuid(uuid), timeout_ms):
                found.append(_MPClientService(self, aservice))
        return found


class _MPClientService(ClientService):
    def __init__(self, connection, aservice):
        ClientService.__init__(self, connection, _uuid(aservice.uuid))
        self._aservice = aservice

    async def _discover_characteristics(self, uuid, timeout_ms):
        found = []
        with _Translate("characteristic discovery"):
            async for achar in self._aservice.characteristics(None if uuid is None else _buuid(uuid), timeout_ms):
                found.append(_MPClientCharacteristic(self, achar))
        return found


class _MPClientCharacteristic(ClientCharacteristic):
    def __init__(self, service, achar):
        ClientCharacteristic.__init__(self, service, _uuid(achar.uuid), achar.properties)
        self._achar = achar
        limit = service.connection._ble.queue_limit
        if achar.properties & FLAG_NOTIFY:
            achar._notify_queue = _Queue(limit, "notify {}".format(self.uuid))
        if achar.properties & FLAG_INDICATE:
            achar._indicate_queue = _Queue(limit, "indicate {}".format(self.uuid))
        # Register now, so notifications that arrive before the first
        # notified() are queued rather than ignored.
        achar._register_with_connection()

    async def read(self, timeout_ms=1000):
        self._check(FLAG_READ, "read")
        with _Translate("read"):
            return bytes(await self._achar.read(timeout_ms))

    async def write(self, data, response=None, timeout_ms=1000):
        data = bytes(data)
        response = self._want_response(response)
        if not self.connection.is_connected():
            raise DisconnectedError("write: not connected")
        if len(data) > self.connection.mtu - 3:
            raise BLEError(
                "write of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), self.connection.mtu - 3, self.connection.mtu
                )
            )
        waited = 0
        limit = timeout_ms if timeout_ms is not None else _WRITE_RETRY_MS
        while True:
            try:
                with _Translate("write"):
                    await self._achar.write(data, response, timeout_ms)
                return
            except OSError as e:
                if _errno(e) not in _BUSY_ERRNOS:
                    if not self.connection.is_connected():
                        raise DisconnectedError("write: disconnected")
                    raise
                if not self.connection.is_connected():
                    raise DisconnectedError("write: disconnected")
                if waited >= limit:
                    raise BLETimeoutError("write: buffers stayed full for {} ms".format(waited))
                await sleep_ms(2)
                waited += 2

    async def subscribe(self, notify=True, indicate=False):
        if notify:
            self._check(FLAG_NOTIFY, "notify")
        if indicate:
            self._check(FLAG_INDICATE, "indicate")
        with _Translate("subscribe"):
            try:
                await self._achar.subscribe(notify, indicate)
            except ValueError as e:
                raise UnsupportedError(str(e))

    async def _next(self, queue, event, timeout_ms, what):
        # Not aioble's notified(): it waits only when the queue holds <= 1
        # item and assumes the flag is then set, which holds for its one-slot
        # queue but strands the last item of a longer one. Wait only when the
        # queue is empty; the IRQ sets the flag on every empty -> non-empty.
        aconn = self._achar._connection()
        while True:
            if len(queue):
                return bytes(queue.popleft())
            if not aconn.is_connected():
                raise DisconnectedError("{}: disconnected".format(what))
            with _Translate(what):
                with aconn.timeout(timeout_ms):
                    await event.wait()

    async def notified(self, timeout_ms=None):
        self._check(FLAG_NOTIFY, "notify")
        a = self._achar
        return await self._next(a._notify_queue, a._notify_event, timeout_ms, "notified")

    async def indicated(self, timeout_ms=None):
        self._check(FLAG_INDICATE, "indicate")
        a = self._achar
        return await self._next(a._indicate_queue, a._indicate_event, timeout_ms, "indicated")


class _MPServerCharacteristic:
    """mpble's half of a :class:`bledev.Characteristic`."""

    def __init__(self, ble, characteristic, achar):
        self._ble = ble
        self._char = characteristic
        self._achar = achar
        if characteristic.capture:
            self._queue = []
            self._overrun = 0
            self._flag = asyncio.ThreadSafeFlag()

    def read(self):
        return bytes(self._achar.read())

    def write(self, data, send_update):
        self._achar.write(data, send_update)

    def _aconn(self, connection):
        aconn = getattr(connection, "_aconn", None)
        if aconn is None:
            raise BLEError("{!r} is not an mpble connection".format(connection))
        if not aconn.is_connected():
            raise DisconnectedError("the connection is closed")
        return aconn

    def _check_size(self, connection, data):
        if data is not None and len(data) > connection.mtu - 3:
            raise BLEError(
                "notification of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), connection.mtu - 3, connection.mtu
                )
            )

    def notify(self, connection, data):
        aconn = self._aconn(connection)
        self._check_size(connection, data)
        try:
            self._achar.notify(aconn, data)
        except OSError as e:
            if _errno(e) in _BUSY_ERRNOS:
                raise BusyError("notify: transmit buffers full")
            if not aconn.is_connected():
                raise DisconnectedError("notify: disconnected")
            raise

    async def indicate(self, connection, data, timeout_ms):
        aconn = self._aconn(connection)
        self._check_size(connection, data)
        with _Translate("indicate"):
            await self._achar.indicate(aconn, data, timeout_ms)

    def _captured(self, aconn, data):
        if len(self._queue) >= self._ble.queue_limit:
            self._overrun += 1
        else:
            self._queue.append((aconn, data))
        self._flag.set()

    async def written(self, timeout_ms):
        if not self._char.capture:
            with _Translate("written"):
                aconn = await self._achar.written(timeout_ms)
            return self._ble._lookup(aconn)
        while True:
            if self._overrun:
                raise BLEError(
                    "writes to {} overran: {} dropped because the reader fell {} behind".format(
                        self._char.uuid, self._overrun, self._ble.queue_limit
                    )
                )
            if self._queue:
                aconn, data = self._queue.pop(0)
                return self._ble._lookup(aconn), data
            if timeout_ms is not None and timeout_ms <= 0:
                raise BLETimeoutError("written timed out")
            try:
                if timeout_ms is None:
                    await self._flag.wait()
                else:
                    await asyncio.wait_for_ms(self._flag.wait(), timeout_ms)
            except asyncio.TimeoutError:
                if not self._queue:
                    raise BLETimeoutError("written timed out after {} ms".format(timeout_ms))
