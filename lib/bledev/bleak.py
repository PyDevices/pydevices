"""CPython backend over bleak: Windows, Linux and macOS. Central only.

    from bledev.bleak import BleakBLE
    ble = BleakBLE()

Needs bleak (``pip install "pydevices[ble]"``). A laptop can scan and connect
but can't advertise, so ``advertise()`` and ``register_services()`` raise
:class:`bledev.UnsupportedError`; ``capabilities()`` says so up front.

Where bleak and the operating system differ from the contract, this backend
translates:

* bleak hands every notification to a callback. Here each subscribed
  characteristic gets a queue of ``queue_limit`` entries, and an overflow
  raises from the next ``notified()`` rather than dropping data.
* The OS negotiates the MTU on its own. ``exchange_mtu()`` waits briefly for
  that negotiation to finish and returns the result; it can't ask for a
  particular value. BlueZ always reports 23 through bleak, so on Linux the MTU
  comes from the characteristics' write-without-response size instead.
* A write longer than ``mtu - 3`` raises :class:`bledev.BLEError` before it
  reaches the OS, as on every backend, even though a write with response
  could go out as a long write.
* bleak can't tell a notification from an indication. Data goes to
  ``indicated()`` when you subscribed with ``indicate=True`` alone, and to
  ``notified()`` otherwise.
* On Windows, ``connect(priority="throughput")`` (or asking for a connection
  interval of 15 ms or less, as ``nus.connect()`` does on a board) asks WinRT
  for its throughput-optimized parameters, which roughly quarters the time a
  GATT round trip takes. Other hosts ignore it.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

try:
    from bleak.exc import BleakGATTProtocolError
except ImportError:  # bleak < 3
    BleakGATTProtocolError = None

from . import (
    ClientDescriptor,
    BLE,
    BLEError,
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
    ScanResult,
    Scanner,
    UnsupportedError,
    UUID,
    wait_ms,
)

_PROPERTIES = {
    "read": FLAG_READ,
    "write-without-response": FLAG_WRITE_NO_RESPONSE,
    "write": FLAG_WRITE,
    "notify": FLAG_NOTIFY,
    "indicate": FLAG_INDICATE,
}

# How long exchange_mtu() waits for the OS to finish its own negotiation.
_MTU_SETTLE_MS = 1000


def _flags(properties):
    flags = 0
    for name in properties:
        flags |= _PROPERTIES.get(name, 0)
    return flags


class _Inbox:
    """An ordered queue that raises instead of dropping data."""

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


class BleakBLE(BLE):
    """The host's Bluetooth adapter, through bleak. Central only.

    ``queue_limit`` bounds each notification queue. ``mtu`` is recorded for
    ``config("mtu")``; the OS picks the real value. Extra keyword arguments in
    ``scanner_args`` and ``client_args`` go to ``BleakScanner`` and
    ``BleakClient`` (for example ``{"bluez": {"adapter": "hci1"}}``).
    """

    backend = "bleak"

    def __init__(self, *, queue_limit=1024, mtu=MAX_MTU, scanner_args=None, client_args=None):
        self.queue_limit = queue_limit
        self._mtu = mtu
        self._scanner_args = dict(scanner_args or {})
        self._client_args = dict(client_args or {})
        self._connections = []

    def capabilities(self):
        caps = BLE.capabilities(self)
        caps.update(central=True, peripheral=False, mtu=self._mtu, max_mtu=MAX_MTU, indicate=True)
        return caps

    def config(self, *names, **settings):
        for key, value in settings.items():
            if key == "mtu":
                if not DEFAULT_MTU <= value <= MAX_MTU:
                    raise ValueError("mtu must be {}..{}".format(DEFAULT_MTU, MAX_MTU))
                self._mtu = value
            else:
                raise UnsupportedError("bleak has no setting {!r}".format(key))
        if names:
            if len(names) != 1:
                raise ValueError("read one setting at a time")
            if names[0] == "mtu":
                return self._mtu
            raise UnsupportedError("bleak has no setting {!r}".format(names[0]))
        return None

    def close(self):
        """Drop every connection. The OS disconnects in the background; ``aclose()`` waits for it."""
        for connection in list(self._connections):
            connection._drop()
            try:
                asyncio.get_running_loop().create_task(connection._client.disconnect())
            except RuntimeError:
                pass
        self._connections = []

    async def aclose(self):
        """``close()``, waiting until the OS has let go of every connection."""
        connections = list(self._connections)
        self.close()
        for connection in connections:
            try:
                await connection._client.disconnect()
            except Exception:
                pass

    # -- central

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        return _BleakScanner(self, duration_ms, active, interval_us, window_us)

    async def _connect(self, device, timeout_ms, **options):
        target = device.native if device.native is not None else device.address
        connection = None

        def on_disconnect(client):
            if connection is not None:
                connection._drop()

        args = dict(self._client_args)
        if timeout_ms is not None:
            args.setdefault("timeout", timeout_ms / 1000)
        client = BleakClient(target, disconnected_callback=on_disconnect, **args)
        try:
            await wait_ms(client.connect(), timeout_ms, "connect to {}".format(device.address))
        except BleakError as e:
            raise BLEError("connect to {}: {}".format(device.address, e))
        connection = _BleakConnection(self, device, client)
        self._connections.append(connection)
        if _wants_throughput(options):
            connection.request_throughput()
        return connection


def _wants_throughput(options):
    if options.get("priority") == "throughput":
        return True
    interval = options.get("max_conn_interval_us") or options.get("min_conn_interval_us")
    return interval is not None and interval <= 15000


class _BleakScanner(Scanner):
    async def _start(self):
        mode = "active" if self.active or sys.platform == "darwin" else "passive"
        self._scanner = BleakScanner(self._detected, scanning_mode=mode, **self._ble._scanner_args)
        try:
            await self._scanner.start()
        except BleakError as e:
            raise BLEError("scan: {}".format(e))
        self._timer = asyncio.get_running_loop().create_task(self._run_out())

    async def _run_out(self):
        await asyncio.sleep(self.duration_ms / 1000)
        self._timer = None
        await self.cancel()

    async def _stop(self):
        timer = getattr(self, "_timer", None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        self._timer = None
        scanner = getattr(self, "_scanner", None)
        if scanner is not None:
            self._scanner = None
            try:
                await scanner.stop()
            except BleakError:
                pass

    def _detected(self, native, adv):
        if self._done:
            return
        name = adv.local_name or None
        self._push(
            ScanResult(
                Device(self._ble, native.address, name=name or native.name, native=native),
                rssi=adv.rssi,
                name=name,
                services=[UUID(u) for u in adv.service_uuids],
                manufacturer=[(k, bytes(v)) for k, v in adv.manufacturer_data.items()],
                service_data=[(UUID(k), bytes(v)) for k, v in adv.service_data.items()],
            )
        )


def _translate(e, connection, what):
    """A bleak or OS exception, as the bledev error it means."""
    if isinstance(e, BLEError):
        return e
    if BleakGATTProtocolError is not None and isinstance(e, BleakGATTProtocolError):
        return GattError(int(e.args[0]), "{}: {}".format(what, e))
    if not connection.is_connected():
        return DisconnectedError("{}: disconnected".format(what))
    return BLEError("{}: {}".format(what, e))


class _BleakConnection(Connection):
    def __init__(self, ble, device, client):
        Connection.__init__(self, ble, device, "central")
        self._client = client
        self._dropped = asyncio.Event()
        self._inboxes = []
        self._wwr = 0  # the largest write-without-response size seen in discovery
        self._paired = False

    def _drop(self):
        if self._dropped.is_set():
            return
        self._dropped.set()
        for inbox in self._inboxes:
            inbox.close()
        if self in self._ble._connections:
            self._ble._connections.remove(self)

    @property
    def mtu(self):
        mtu = DEFAULT_MTU
        try:
            mtu = max(mtu, int(self._client.mtu_size))
        except Exception:
            pass
        if self._wwr:
            mtu = max(mtu, self._wwr + 3)
        return mtu

    def is_connected(self):
        if self._dropped.is_set():
            return False
        try:
            return bool(self._client.is_connected)
        except Exception:
            return False

    async def disconnect(self, timeout_ms=2000):
        try:
            await wait_ms(self._client.disconnect(), timeout_ms, "disconnect")
        except BleakError:
            pass
        finally:
            self._drop()

    async def disconnected(self, timeout_ms=None):
        if self.is_connected():
            await wait_ms(self._dropped.wait(), timeout_ms, "disconnected")

    @property
    def encrypted(self):
        return self._paired

    async def pair(self, bond=True, timeout_ms=20000):
        """Pair through the OS. On Windows that makes a bond the OS keeps (and,
        for a HID device, a keyboard it uses), so the tests here never call it."""
        self._live("pair")
        try:
            await wait_ms(self._client.pair(), timeout_ms, "pair")
        except (BleakError, OSError) as e:
            raise _translate(e, self, "pair")
        self._paired = True

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        """The OS negotiates on its own; wait briefly for it and return the result."""
        self._live("exchange_mtu")
        if mtu:
            self._ble.config(mtu=mtu)
        waited = 0
        limit = min(timeout_ms if timeout_ms is not None else _MTU_SETTLE_MS, _MTU_SETTLE_MS)
        while self.mtu == DEFAULT_MTU and waited < limit and self.is_connected():
            await asyncio.sleep(0.02)
            waited += 20
        return self.mtu

    def request_throughput(self):
        """Ask the OS for a short connection interval. Windows 11 only; returns whether it asked."""
        requester = getattr(getattr(self._client, "_backend", None), "_requester", None)
        if requester is None:
            return False
        try:
            from winrt.windows.devices.bluetooth import BluetoothLEPreferredConnectionParameters

            requester.request_preferred_connection_parameters(
                BluetoothLEPreferredConnectionParameters.throughput_optimized
            )
            return True
        except Exception:
            return False

    def _live(self, what):
        if not self.is_connected():
            raise DisconnectedError("{}: not connected".format(what))

    async def _discover_services(self, uuid, timeout_ms):
        self._live("service discovery")
        found = []
        for service in sorted(self._client.services, key=lambda s: s.handle):
            wrapped = _BleakClientService(self, service)
            if uuid is None or wrapped.uuid == uuid:
                found.append(wrapped)
        return found


class _BleakClientService(ClientService):
    def __init__(self, connection, native):
        ClientService.__init__(self, connection, native.uuid)
        self._native = native

    async def _discover_characteristics(self, uuid, timeout_ms):
        self.connection._live("characteristic discovery")
        found = []
        for native in sorted(self._native.characteristics, key=lambda c: c.handle):
            try:
                wwr = native.max_write_without_response_size
            except Exception:
                wwr = 0
            if wwr > self.connection._wwr:
                self.connection._wwr = wwr
            wrapped = _BleakClientCharacteristic(self, native)
            if uuid is None or wrapped.uuid == uuid:
                found.append(wrapped)
        return found


class _BleakClientCharacteristic(ClientCharacteristic):
    def __init__(self, service, native):
        ClientCharacteristic.__init__(self, service, native.uuid, _flags(native.properties))
        self._native = native
        self._client = service.connection._client
        limit = service.connection._ble.queue_limit
        self._notify_inbox = _Inbox(limit, "notify {}".format(self.uuid))
        self._indicate_inbox = _Inbox(limit, "indicate {}".format(self.uuid))
        service.connection._inboxes.extend((self._notify_inbox, self._indicate_inbox))
        self._route = None
        self._subscribed = False

    def _live(self, what):
        self.connection._live(what)

    async def read(self, timeout_ms=1000):
        self._check(FLAG_READ, "read")
        self._live("read")
        try:
            return bytes(await wait_ms(self._client.read_gatt_char(self._native), timeout_ms, "read"))
        except (BleakError, OSError) as e:
            raise _translate(e, self.connection, "read")

    async def _discover_descriptors(self, uuid, timeout_ms):
        self._live("descriptor discovery")
        found = []
        for native in sorted(self._native.descriptors, key=lambda d: d.handle):
            d = _BleakClientDescriptor(self, native)
            if uuid is None or d.uuid == uuid:
                found.append(d)
        return found

    async def write(self, data, response=None, timeout_ms=1000):
        data = bytes(data)
        response = self._want_response(response)
        self._live("write")
        mtu = self.connection.mtu
        if len(data) > mtu - 3:
            raise BLEError(
                "write of {} bytes exceeds the ATT payload of {} (mtu {} - 3)".format(len(data), mtu - 3, mtu)
            )
        try:
            await wait_ms(self._client.write_gatt_char(self._native, data, response=response), timeout_ms, "write")
        except (BleakError, OSError) as e:
            raise _translate(e, self.connection, "write")

    def _received(self, sender, data):
        inbox = self._indicate_inbox if self._route == "indicate" else self._notify_inbox
        inbox.put(bytes(data))

    async def subscribe(self, notify=True, indicate=False):
        if notify:
            self._check(FLAG_NOTIFY, "notify")
        if indicate:
            self._check(FLAG_INDICATE, "indicate")
        self._live("subscribe")
        try:
            if self._subscribed:
                await self._client.stop_notify(self._native)
                self._subscribed = False
            if not notify and not indicate:
                return
            self._route = "indicate" if indicate and not notify else "notify"
            kwargs = {}
            if self._route == "indicate" and sys.platform == "win32":
                kwargs["force_indicate"] = True
            await self._client.start_notify(self._native, self._received, **kwargs)
            self._subscribed = True
        except (BleakError, OSError) as e:
            raise _translate(e, self.connection, "subscribe")

    async def notified(self, timeout_ms=None):
        self._check(FLAG_NOTIFY, "notify")
        return await self._notify_inbox.get(timeout_ms)

    async def indicated(self, timeout_ms=None):
        self._check(FLAG_INDICATE, "indicate")
        return await self._indicate_inbox.get(timeout_ms)


class _BleakClientDescriptor(ClientDescriptor):
    def __init__(self, characteristic, native):
        ClientDescriptor.__init__(self, characteristic, native.uuid)
        self._native = native

    async def read(self, timeout_ms=1000):
        client = self.connection._client
        self.connection._live("descriptor read")
        try:
            return bytes(await wait_ms(client.read_gatt_descriptor(self._native.handle), timeout_ms, "descriptor read"))
        except (BleakError, OSError) as e:
            raise _translate(e, self.connection, "descriptor read")
