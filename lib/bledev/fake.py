"""In-process loopback backend: two adapters, one pretend radio, no hardware.

Every :class:`FakeBLE` built on the same :class:`Air` can see and connect to
the others, so a test runs a peripheral and a central in one event loop::

    from bledev.fake import Air, FakeBLE

    air = Air()
    board = FakeBLE(air=air)                    # either role, like a board
    laptop = FakeBLE(air=air, peripheral=False)  # central only, like bleak

It runs on CPython and MicroPython, and it is stricter than a real radio on
purpose. Where real hardware would quietly truncate or drop data, the fake
raises, so a bug shows up in a test rather than as corruption on a board:

* A notification or write longer than ``mtu - 3`` raises :class:`BLEError`
  (NimBLE truncates it).
* A write longer than the characteristic's ``max_len`` raises (MicroPython
  truncates to the buffer, 20 bytes by default).
* Notifications reach a client only after it calls ``subscribe()``.
* Only ``notify_buffers`` notifications can be in flight per connection;
  one more raises :class:`BusyError` until the event loop runs, the way a real
  controller runs out of buffers. Send loops must await between bursts.
* A receive queue that fills up (``queue_limit``) makes the next
  ``notified()`` or ``written()`` raise instead of dropping data silently.
* The name only reaches a *passive* scan when it fits in the 31-byte
  advertisement; otherwise it is in the scan response, as on real hardware.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

from . import (
    BLE,
    BLEError,
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
    FLAG_WRITE,
    FLAG_WRITE_NO_RESPONSE,
    MAX_MTU,
    ScanResult,
    Scanner,
    UnsupportedError,
    decode_advertisement,
    pack_advertisement,
    sleep_ms,
    wait_ms,
)

#: How often a fake scan looks at the air, in milliseconds.
SCAN_TICK_MS = 5


class Air:
    """The medium the fake adapters share. Make one per test."""

    def __init__(self):
        self.adverts = []
        self._next = 1

    def _allocate(self):
        n = self._next
        self._next += 1
        return "fa:ce:00:00:{:02x}:{:02x}".format((n >> 8) & 0xFF, n & 0xFF)


_default_air = Air()


def default_air():
    """The :class:`Air` used when an adapter isn't given one."""
    return _default_air


class _Advert:
    def __init__(self, ble, adv_data, resp_data, connectable):
        self.ble = ble
        self.adv_data = adv_data
        self.resp_data = resp_data
        self.connectable = connectable
        self.event = asyncio.Event()
        self.connection = None
        self.closed = False


class _Inbox:
    """An ordered queue that refuses to lose data quietly."""

    def __init__(self, limit, what):
        self.items = []
        self.event = asyncio.Event()
        self.limit = limit
        self.what = what
        self.overrun = 0
        self.closed = False

    def put(self, item):
        if len(self.items) >= self.limit:
            self.overrun += 1
        else:
            self.items.append(item)
        self.event.set()

    def close(self):
        self.closed = True
        self.event.set()

    async def get(self, timeout_ms):
        while True:
            if self.overrun:
                raise BLEError(
                    "{} queue overran: {} item(s) dropped because the reader fell "
                    "{} behind".format(self.what, self.overrun, self.limit)
                )
            if self.items:
                return self.items.pop(0)
            if self.closed:
                raise DisconnectedError("{}: disconnected".format(self.what))
            self.event.clear()
            await wait_ms(self.event.wait(), timeout_ms, self.what)


class FakeBLE(BLE):
    """A pretend radio. ``central`` and ``peripheral`` pick the roles it may take.

    ``mtu`` is the ATT MTU it asks for in ``exchange_mtu()``.
    ``notify_buffers`` and ``queue_limit`` size the flow control described in
    the module docstring.
    """

    backend = "fake"

    def __init__(
        self,
        *,
        air=None,
        central=True,
        peripheral=True,
        mtu=DEFAULT_MTU,
        address=None,
        rssi=-50,
        notify_buffers=8,
        queue_limit=128,
        gap_name="fake",
    ):
        self._air = air if air is not None else _default_air
        self._central = central
        self._peripheral = peripheral
        self._mtu = mtu
        self.address = address or self._air._allocate()
        self.rssi = rssi
        self.notify_buffers = notify_buffers
        self.queue_limit = queue_limit
        self._gap_name = gap_name
        self._services = ()
        self._adverts = []
        self._links = []

    def capabilities(self):
        caps = BLE.capabilities(self)
        caps.update(
            central=self._central,
            peripheral=self._peripheral,
            mtu=self._mtu,
            max_mtu=MAX_MTU,
            indicate=True,
        )
        return caps

    def config(self, *names, **settings):
        for key, value in settings.items():
            if key == "mtu":
                if not 23 <= value <= MAX_MTU:
                    raise ValueError("mtu must be 23..{}".format(MAX_MTU))
                self._mtu = value
            elif key == "gap_name":
                self._gap_name = value
            else:
                raise UnsupportedError("fake has no setting {!r}".format(key))
        if names:
            if len(names) != 1:
                raise ValueError("read one setting at a time")
            if names[0] == "mtu":
                return self._mtu
            if names[0] == "gap_name":
                return self._gap_name
            raise UnsupportedError("fake has no setting {!r}".format(names[0]))
        return None

    def close(self):
        for advert in list(self._adverts):
            advert.closed = True
            advert.event.set()
        for link in list(self._links):
            link.drop()

    # -- peripheral

    def register_services(self, *services):
        if not self._peripheral:
            raise UnsupportedError("this fake adapter is central only")
        for service in self._services:
            for characteristic in service.characteristics:
                characteristic._impl = None
        self._services = tuple(services)
        for service in services:
            for characteristic in service.characteristics:
                characteristic._impl = _ServerCharacteristic(self, characteristic)

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
        if not self._peripheral:
            raise UnsupportedError("this fake adapter is central only; it cannot advertise")
        adv_data, resp_data = pack_advertisement(name, services, appearance, manufacturer)
        advert = _Advert(self, adv_data, resp_data, connectable)
        self._air.adverts.append(advert)
        self._adverts.append(advert)
        try:
            await wait_ms(advert.event.wait(), timeout_ms, "advertise")
        finally:
            if advert in self._air.adverts:
                self._air.adverts.remove(advert)
            self._adverts.remove(advert)
        if advert.closed:
            raise BLEError("adapter closed while advertising")
        return advert.connection

    # -- central

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        if not self._central:
            raise UnsupportedError("this fake adapter is peripheral only; it cannot scan")
        return _FakeScanner(self, duration_ms, active, interval_us, window_us)

    async def _connect(self, device, timeout_ms, **options):
        if not self._central:
            raise UnsupportedError("this fake adapter is peripheral only; it cannot connect")

        async def attempt():
            while True:
                for advert in self._air.adverts:
                    if advert.ble.address == device.address and advert.connectable:
                        return advert
                await sleep_ms(SCAN_TICK_MS)

        advert = await wait_ms(attempt(), timeout_ms, "connect to {}".format(device.address))
        link = _Link(self, advert.ble, device)
        advert.connection = link.peripheral
        self._air.adverts.remove(advert)
        advert.event.set()
        return link.central


class _FakeScanner(Scanner):
    async def _start(self):
        self._task = asyncio.create_task(self._run())

    async def _stop(self):
        task = getattr(self, "_task", None)
        if task is not None:
            task.cancel()
            self._task = None

    async def _run(self):
        seen = {}
        elapsed = 0
        try:
            while elapsed < self.duration_ms:
                for advert in list(self._ble._air.adverts):
                    if advert.ble is self._ble:
                        continue
                    payloads = (advert.adv_data, advert.resp_data) if self.active else (advert.adv_data,)
                    key = advert.ble.address
                    if seen.get(key) == payloads:
                        continue
                    seen[key] = payloads
                    name, services, appearance, manufacturer = decode_advertisement(*payloads)
                    device = Device(self._ble, advert.ble.address, name=name)
                    self._push(
                        ScanResult(
                            device,
                            rssi=advert.ble.rssi,
                            name=name,
                            services=services,
                            appearance=appearance,
                            manufacturer=manufacturer,
                            connectable=advert.connectable,
                        )
                    )
                await sleep_ms(SCAN_TICK_MS)
                elapsed += SCAN_TICK_MS
        finally:
            self._task = None
            self._finish()


class _Link:
    """Both ends of one fake connection, and what travels between them."""

    def __init__(self, central_ble, peripheral_ble, device):
        self.connected = True
        self.central_ble = central_ble
        self.peripheral_ble = peripheral_ble
        self.dropped = asyncio.Event()
        self.central = _FakeConnection(central_ble, device, "central", self)
        self.peripheral = _FakeConnection(
            peripheral_ble, Device(peripheral_ble, central_ble.address), "peripheral", self
        )
        # Keyed by (server characteristic, "notify" | "indicate").
        self.inboxes = {}
        self.subscribed = {}
        self.in_flight = []
        self._drain_task = None
        central_ble._links.append(self)
        peripheral_ble._links.append(self)

    def set_mtu(self, mtu):
        self.central._mtu = mtu
        self.peripheral._mtu = mtu

    def check(self):
        if not self.connected:
            raise DisconnectedError("the connection is closed")

    def inbox(self, server_char, kind, limit):
        key = (id(server_char), kind)
        box = self.inboxes.get(key)
        if box is None:
            box = _Inbox(limit, "{} {}".format(kind, server_char.uuid))
            if not self.connected:
                box.close()
            self.inboxes[key] = box
        return box

    def deliver(self, server_char, kind, data, busy_check):
        self.check()
        if busy_check and len(self.in_flight) >= self.peripheral_ble.notify_buffers:
            raise BusyError("{} notifications already in flight".format(len(self.in_flight)))
        self.in_flight.append((server_char, kind, data))
        if self._drain_task is None:
            # Held so CPython can't collect the task mid-flight.
            self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self):
        # One event-loop turn of "air time", then everything buffered arrives.
        await asyncio.sleep(0)
        self._drain_task = None
        pending, self.in_flight = self.in_flight, []
        if not self.connected:
            return
        for server_char, kind, data in pending:
            notify, indicate = self.subscribed.get(id(server_char), (False, False))
            if (kind == "notify" and notify) or (kind == "indicate" and indicate):
                self.inbox(server_char, kind, self.central_ble.queue_limit).put(data)

    def drop(self):
        if not self.connected:
            return
        self.connected = False
        for box in self.inboxes.values():
            box.close()
        for ble in (self.central_ble, self.peripheral_ble):
            if self in ble._links:
                ble._links.remove(self)
        self.dropped.set()


class _FakeConnection(Connection):
    def __init__(self, ble, device, role, link):
        Connection.__init__(self, ble, device, role)
        self._link = link

    def is_connected(self):
        return self._link.connected

    async def disconnect(self, timeout_ms=2000):
        self._link.drop()
        await asyncio.sleep(0)

    async def disconnected(self, timeout_ms=None):
        if self._link.connected:
            await wait_ms(self._link.dropped.wait(), timeout_ms, "disconnected")

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        self._link.check()
        if mtu:
            self._ble.config(mtu=mtu)
        link = self._link
        agreed = max(DEFAULT_MTU, min(link.central_ble._mtu, link.peripheral_ble._mtu))
        await asyncio.sleep(0)
        link.set_mtu(agreed)
        return agreed

    def _peer(self):
        link = self._link
        return link.peripheral_ble if self.role == "central" else link.central_ble

    async def _discover_services(self, uuid, timeout_ms):
        self._link.check()
        await asyncio.sleep(0)
        return [
            _FakeClientService(self, service)
            for service in self._peer()._services
            if uuid is None or service.uuid == uuid
        ]


class _FakeClientService(ClientService):
    def __init__(self, connection, server_service):
        ClientService.__init__(self, connection, server_service.uuid)
        self._server = server_service

    async def _discover_characteristics(self, uuid, timeout_ms):
        self.connection._link.check()
        await asyncio.sleep(0)
        return [
            _FakeClientCharacteristic(self, characteristic)
            for characteristic in self._server.characteristics
            if uuid is None or characteristic.uuid == uuid
        ]


class _FakeClientCharacteristic(ClientCharacteristic):
    def __init__(self, service, server_char):
        ClientCharacteristic.__init__(self, service, server_char.uuid, server_char.flags)
        self._server = server_char

    def _link(self):
        link = self.connection._link
        link.check()
        return link

    async def read(self, timeout_ms=1000):
        self._check(FLAG_READ, "read")
        self._link()
        await asyncio.sleep(0)
        self._link()
        return self._server.read()

    async def write(self, data, response=None, timeout_ms=1000):
        data = bytes(data)
        response = self._want_response(response)
        link = self._link()
        if len(data) > self.connection.mtu - 3:
            raise BLEError(
                "write of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), self.connection.mtu - 3, self.connection.mtu
                )
            )
        server = self._server
        if len(data) > server.max_len:
            raise BLEError(
                "write of {} bytes exceeds {!r} max_len={}; real firmware would "
                "truncate it".format(len(data), server, server.max_len)
            )
        server._impl._remote_write(link.peripheral, data)
        await asyncio.sleep(0)

    async def subscribe(self, notify=True, indicate=False):
        if notify:
            self._check(FLAG_NOTIFY, "notify")
        if indicate:
            self._check(FLAG_INDICATE, "indicate")
        link = self._link()
        link.subscribed[id(self._server)] = (bool(notify), bool(indicate))
        await asyncio.sleep(0)

    async def notified(self, timeout_ms=None):
        self._check(FLAG_NOTIFY, "notify")
        link = self.connection._link
        return await link.inbox(self._server, "notify", link.central_ble.queue_limit).get(timeout_ms)

    async def indicated(self, timeout_ms=None):
        self._check(FLAG_INDICATE, "indicate")
        link = self.connection._link
        return await link.inbox(self._server, "indicate", link.central_ble.queue_limit).get(timeout_ms)


class _ServerCharacteristic:
    """The fake's half of a :class:`bledev.Characteristic`."""

    def __init__(self, ble, characteristic):
        self._ble = ble
        self._char = characteristic
        self._value = characteristic._initial or b""
        self._writes = _Inbox(ble.queue_limit, "writes to {}".format(characteristic.uuid))
        self._last_writer = None
        self._written = asyncio.Event()

    def read(self):
        return self._value

    def write(self, data, send_update):
        self._value = data
        if send_update:
            for link in list(self._ble._links):
                if link.peripheral_ble is not self._ble or not link.connected:
                    continue
                if self._char.flags & FLAG_NOTIFY:
                    link.deliver(self._char, "notify", data, False)
                if self._char.flags & FLAG_INDICATE:
                    link.deliver(self._char, "indicate", data, False)

    def _link_for(self, connection):
        link = getattr(connection, "_link", None)
        if link is None or link.peripheral is not connection:
            raise BLEError("{!r} is not a peripheral-side connection of this adapter".format(connection))
        return link

    def _check_size(self, connection, data):
        if len(data) > connection.mtu - 3:
            raise BLEError(
                "notification of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(
                    len(data), connection.mtu - 3, connection.mtu
                )
            )

    def notify(self, connection, data):
        link = self._link_for(connection)
        data = self._value if data is None else data
        self._check_size(connection, data)
        link.deliver(self._char, "notify", data, True)

    async def indicate(self, connection, data, timeout_ms):
        link = self._link_for(connection)
        data = self._value if data is None else data
        self._check_size(connection, data)
        link.deliver(self._char, "indicate", data, False)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        link.check()

    def _remote_write(self, connection, data):
        self._value = data
        if self._char.capture:
            self._writes.put((connection, data))
        else:
            self._last_writer = connection
            self._written.set()

    async def written(self, timeout_ms):
        if self._char.capture:
            return await self._writes.get(timeout_ms)
        if not self._written.is_set():
            await wait_ms(self._written.wait(), timeout_ms, "written")
        self._written.clear()
        return self._last_writer
