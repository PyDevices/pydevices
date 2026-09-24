"""Portable Bluetooth Low Energy: the contract every bledev backend implements.

You write a BLE program once against this module, and it runs on a board
(:mod:`bledev.mpble`), on a laptop (``bledev.bleak``), in a browser
(``bledev.webble``), or against the in-process loopback in tests
(:mod:`bledev.fake`). The guide is ``docs/bledev.md``.

The shape is aioble's, and it is async throughout. The pieces:

* :class:`UUID`, the errors, and the ``FLAG_*`` property bits.
* :class:`BLE`, the adapter. A backend subclasses it. ``capabilities()`` says
  which roles it can take, because roles aren't symmetric: bleak and Web
  Bluetooth are central only, and a board can be either.
* The peripheral side: :class:`Service` and :class:`Characteristic` describe a
  GATT server, ``ble.register_services()`` installs it, and
  ``await ble.advertise()`` returns a :class:`Connection` when a central
  connects.
* The central side: ``ble.scan()`` yields :class:`ScanResult`, ``ble.find()``
  returns a :class:`Device`, and ``await device.connect()`` returns a
  :class:`Connection`, whose services and characteristics you discover as
  :class:`ClientService` and :class:`ClientCharacteristic`.

Nothing here imports a backend, and nothing here imports :mod:`bledev.auto`.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover - very old MicroPython
    import uasyncio as asyncio

import struct

__version__ = "0.1.0"

# GATT characteristic property bits. The values are the Bluetooth spec's, and
# the same ones MicroPython's bluetooth module and aioble use.
FLAG_READ = 0x0002
FLAG_WRITE_NO_RESPONSE = 0x0004
FLAG_WRITE = 0x0008
FLAG_NOTIFY = 0x0010
FLAG_INDICATE = 0x0020

#: Every connection starts at this ATT MTU. One ATT packet carries ``mtu - 3``
#: bytes of value.
DEFAULT_MTU = 23
MAX_MTU = 517

ADDR_PUBLIC = 0
ADDR_RANDOM = 1


# ---------------------------------------------------------------- errors


class BLEError(Exception):
    """Base of every error bledev raises."""


class UnsupportedError(BLEError):
    """This backend cannot do that: a role it can't take, or a missing feature."""


class DisconnectedError(BLEError):
    """The connection dropped, or was already closed, before the operation finished."""


class BLETimeoutError(BLEError):
    """An operation given ``timeout_ms`` did not finish in time."""


class BusyError(BLEError):
    """The controller's transmit buffers are full. Wait a moment and send again.

    Only :meth:`Characteristic.notify` raises it, because it is synchronous;
    every async send waits for room instead.
    """


#: ATT error codes a :class:`GattError` can carry that apps act on.
INSUFFICIENT_AUTHENTICATION = 0x05
INSUFFICIENT_ENCRYPTION = 0x0F


class PairingError(BLEError):
    """Pairing failed: a wrong passkey, a refusal, or a peer that lost its keys."""


#: What to tell someone whose host kept a bond the board no longer has.
STALE_BOND = (
    "the board refused this host's keys: it has probably lost its bond (a chip "
    "erase, or bledev.security.forget()). Unpair it on this host "
    "(bledev.bleak.unpair(address), or Settings > Bluetooth > Remove device) "
    "and pair again"
)

#: The GATT statuses that mean "pair first".
NEEDS_PAIRING = (INSUFFICIENT_AUTHENTICATION, INSUFFICIENT_ENCRYPTION)


class GattError(BLEError):
    """The peer answered a GATT request with an error ``status``."""

    def __init__(self, status, message=None):
        super().__init__(message or "GATT error 0x{:02x}".format(status))
        self.status = status


async def sleep_ms(ms):
    """``asyncio.sleep_ms`` on every interpreter."""
    await asyncio.sleep(ms / 1000)


async def wait_ms(awaitable, timeout_ms, what="operation"):
    """Await ``awaitable``, raising :class:`BLETimeoutError` after ``timeout_ms``.

    ``timeout_ms=None`` waits forever. Backends use this so every timeout in
    bledev is the same exception.
    """
    if timeout_ms is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout_ms / 1000)
    except asyncio.TimeoutError:
        raise BLETimeoutError("{} timed out after {} ms".format(what, timeout_ms))


# ---------------------------------------------------------------- UUID

_BASE_TAIL = bytes((0x00, 0x00, 0x10, 0x00, 0x80, 0x00, 0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB))
_HEX = "0123456789abcdef"


def _hex(data):
    return "".join(_HEX[b >> 4] + _HEX[b & 15] for b in data)


def _unhex(text):
    if len(text) % 2:
        raise ValueError("odd-length hex")
    return bytes(int(text[i : i + 2], 16) for i in range(0, len(text), 2))


class UUID:
    """A Bluetooth UUID, the same value on every host.

    Accepts a 16- or 32-bit ``int`` (``UUID(0x180F)``), a string in any of the
    usual spellings (``"180f"``, ``"0x180F"``,
    ``"6e400001-b5a3-f393-e0a9-e50e24dcca9e"``), another UUID, MicroPython's
    ``bluetooth.UUID``, or 2, 4 or 16 bytes in Bluetooth's little-endian wire
    order. A short UUID equals its 128-bit expansion.

    ``str()`` is always the 128-bit lowercase form, which is what bleak and Web
    Bluetooth use. ``short`` is the 16/32-bit value, or ``None``.
    ``to_bytes()`` is the wire form, shortest first.
    """

    def __init__(self, value):
        if isinstance(value, UUID):
            self._be = value._be
            return
        if isinstance(value, int):
            self._be = self._from_short(value)
            return
        if isinstance(value, str):
            text = value.strip().lower()
            if text.startswith("0x"):
                self._be = self._from_short(int(text[2:], 16))
                return
            text = text.replace("-", "")
            if len(text) in (4, 8):
                self._be = self._from_short(int(text, 16))
                return
            if len(text) != 32:
                raise ValueError("not a UUID: {!r}".format(value))
            self._be = _unhex(text)
            return
        try:
            raw = bytes(value)
        except TypeError:
            raise ValueError("not a UUID: {!r}".format(value))
        if len(raw) in (2, 4):
            self._be = self._from_short(int.from_bytes(raw, "little"))
        elif len(raw) == 16:
            self._be = bytes(reversed(raw))
        else:
            raise ValueError("a UUID is 2, 4 or 16 bytes, not {}".format(len(raw)))

    @staticmethod
    def _from_short(value):
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("short UUID out of range: {}".format(value))
        return value.to_bytes(4, "big") + _BASE_TAIL

    @property
    def short(self):
        """The 16- or 32-bit value when this is a Bluetooth-base UUID, else ``None``."""
        if self._be[4:] == _BASE_TAIL:
            return int.from_bytes(self._be[:4], "big")
        return None

    def to_bytes(self):
        """Little-endian wire bytes: 2 for a 16-bit UUID, 4 for 32-bit, else 16."""
        short = self.short
        if short is not None:
            return short.to_bytes(2 if short <= 0xFFFF else 4, "little")
        return bytes(reversed(self._be))

    def __bytes__(self):
        return self.to_bytes()

    def __str__(self):
        h = _hex(self._be)
        return "-".join((h[:8], h[8:12], h[12:16], h[16:20], h[20:]))

    def __repr__(self):
        short = self.short
        if short is not None:
            return "UUID(0x{:04x})".format(short)
        return "UUID('{}')".format(self)

    def __eq__(self, other):
        if not isinstance(other, UUID):
            try:
                other = UUID(other)
            except (ValueError, TypeError):
                return False
        return self._be == other._be

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._be)


# ---------------------------------------------------------------- advertising payloads

ADV_TYPE_FLAGS = 0x01
ADV_TYPE_UUID16_INCOMPLETE = 0x02
ADV_TYPE_UUID16_COMPLETE = 0x03
ADV_TYPE_UUID32_INCOMPLETE = 0x04
ADV_TYPE_UUID32_COMPLETE = 0x05
ADV_TYPE_UUID128_INCOMPLETE = 0x06
ADV_TYPE_UUID128_COMPLETE = 0x07
ADV_TYPE_SHORT_NAME = 0x08
ADV_TYPE_NAME = 0x09
ADV_TYPE_SERVICE_DATA16 = 0x16
ADV_TYPE_APPEARANCE = 0x19
ADV_TYPE_SERVICE_DATA32 = 0x20
ADV_TYPE_SERVICE_DATA128 = 0x21
ADV_TYPE_MANUFACTURER = 0xFF

ADV_PAYLOAD_MAX = 31


def pack_advertisement(name=None, services=None, appearance=0, manufacturer=None, service_data=None):
    """Build ``(adv_data, resp_data)``, in aioble's field order.

    Fields go into the 31-byte advertisement in this order (flags, services,
    service data, name, appearance, manufacturer) and overflow into the scan
    response, which only an *active* scan sees. That is why a long name can be
    invisible to a passive scan. The fake backend and mpble both advertise
    what this returns, so tests see what a board sends.
    ``manufacturer`` is ``(company_id, data)``; ``service_data`` is a list of
    ``(uuid, data)``.
    """
    adv = bytearray()
    resp = bytearray()

    def append(adv_type, value):
        field = bytes((len(value) + 1, adv_type)) + bytes(value)
        if len(adv) + len(field) <= ADV_PAYLOAD_MAX:
            adv.extend(field)
        elif len(resp) + len(field) <= ADV_PAYLOAD_MAX:
            resp.extend(field)
        else:
            raise ValueError("advertising payload too long")

    append(ADV_TYPE_FLAGS, b"\x06")
    if services:
        uuids = [UUID(s).to_bytes() for s in services]
        for size, code in ((2, ADV_TYPE_UUID16_COMPLETE), (4, ADV_TYPE_UUID32_COMPLETE), (16, ADV_TYPE_UUID128_COMPLETE)):
            group = b"".join(u for u in uuids if len(u) == size)
            if group:
                append(code, group)
    if service_data:
        codes = {2: ADV_TYPE_SERVICE_DATA16, 4: ADV_TYPE_SERVICE_DATA32, 16: ADV_TYPE_SERVICE_DATA128}
        for uuid, data in service_data:
            raw = UUID(uuid).to_bytes()
            append(codes[len(raw)], raw + bytes(data))
    if name:
        append(ADV_TYPE_NAME, name.encode() if isinstance(name, str) else name)
    if appearance:
        append(ADV_TYPE_APPEARANCE, struct.pack("<H", appearance))
    if manufacturer:
        append(ADV_TYPE_MANUFACTURER, struct.pack("<H", manufacturer[0]) + bytes(manufacturer[1]))
    return bytes(adv), bytes(resp)


def decode_fields(*payloads):
    """Yield ``(adv_type, value)`` for every field in the given payloads."""
    for payload in payloads:
        if not payload:
            continue
        i = 0
        while i + 1 < len(payload):
            length = payload[i]
            if length == 0:
                break
            yield payload[i + 1], bytes(payload[i + 2 : i + length + 1])
            i += 1 + length


def decode_advertisement(*payloads):
    """``(name, services, appearance, manufacturer)`` from raw payloads.

    ``manufacturer`` is a list of ``(company_id, data)``.
    """
    name = None
    services = []
    appearance = 0
    manufacturer = []
    sizes = {
        ADV_TYPE_UUID16_INCOMPLETE: 2,
        ADV_TYPE_UUID16_COMPLETE: 2,
        ADV_TYPE_UUID32_INCOMPLETE: 4,
        ADV_TYPE_UUID32_COMPLETE: 4,
        ADV_TYPE_UUID128_INCOMPLETE: 16,
        ADV_TYPE_UUID128_COMPLETE: 16,
    }
    for adv_type, value in decode_fields(*payloads):
        if adv_type in (ADV_TYPE_NAME, ADV_TYPE_SHORT_NAME):
            if name is None or adv_type == ADV_TYPE_NAME:
                name = value.decode()
        elif adv_type in sizes:
            size = sizes[adv_type]
            for i in range(0, len(value) - size + 1, size):
                services.append(UUID(value[i : i + size]))
        elif adv_type == ADV_TYPE_APPEARANCE and len(value) >= 2:
            appearance = struct.unpack("<H", value[:2])[0]
        elif adv_type == ADV_TYPE_MANUFACTURER and len(value) >= 2:
            manufacturer.append((struct.unpack("<H", value[:2])[0], value[2:]))
    return name, services, appearance, manufacturer


def decode_service_data(*payloads):
    """``[(UUID, data), ...]`` from the service-data fields of raw payloads."""
    sizes = {ADV_TYPE_SERVICE_DATA16: 2, ADV_TYPE_SERVICE_DATA32: 4, ADV_TYPE_SERVICE_DATA128: 16}
    found = []
    for adv_type, value in decode_fields(*payloads):
        size = sizes.get(adv_type)
        if size and len(value) >= size:
            found.append((UUID(value[:size]), value[size:]))
    return found


# ---------------------------------------------------------------- the adapter


class BLE:
    """One radio. Backends subclass this; apps receive one from a board config.

    Methods a backend can't support raise :class:`UnsupportedError`, so a
    central-only host fails loudly at ``advertise()`` rather than doing
    nothing. Check ``capabilities()`` first when your app can take either role.
    """

    backend = "base"

    # -- what this host can do

    def capabilities(self):
        """A dict describing this backend. Keys every backend provides:

        ``backend`` (its module name), ``central`` and ``peripheral`` (which
        roles it can take), ``mtu`` (the ATT MTU it asks for), ``max_mtu``,
        ``indicate``, ``pairing`` and ``l2cap`` (bools), and ``long_read``:
        whether a read returns values longer than one packet (``mtu - 1``).
        """
        return {
            "backend": self.backend,
            "central": False,
            "peripheral": False,
            "mtu": DEFAULT_MTU,
            "max_mtu": DEFAULT_MTU,
            "indicate": False,
            "pairing": False,
            "l2cap": False,
            "long_read": True,
        }

    def config(self, *names, **settings):
        """Read or set adapter settings, like ``bluetooth.BLE.config``.

        ``config(mtu=247)`` sets the ATT MTU this side asks for;
        ``config("mtu")`` reads it. ``gap_name`` is the device name in the GAP
        service. A setting the backend doesn't have raises
        :class:`UnsupportedError`.
        """
        raise UnsupportedError("{} has no settings".format(self.backend))

    def close(self):
        """Stop advertising and scanning, drop connections, and turn the radio off."""

    # -- peripheral role

    def register_services(self, *services):
        """Install the GATT server. Replaces whatever was registered before.

        Call it before ``advertise()``. Each :class:`Characteristic` is bound
        to this adapter from here on.
        """
        raise UnsupportedError("{} cannot be a peripheral".format(self.backend))

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
        """Advertise until a central connects, and return that :class:`Connection`.

        ``service_data`` is a list of ``(uuid, data)`` (Improv uses it).
        Raises :class:`BLETimeoutError` if nobody connects within
        ``timeout_ms``. Cancelling the task stops advertising. Advertising
        stops when a central connects; call again to accept another.
        """
        raise UnsupportedError("{} cannot advertise".format(self.backend))

    # -- central role

    def scan(self, duration_ms, *, active=False, interval_us=None, window_us=None):
        """Scan for ``duration_ms``. Use as::

            async with ble.scan(5000, active=True) as scanner:
                async for result in scanner:
                    ...

        A device can be yielded more than once as its data arrives. An
        *active* scan also asks for scan responses, which is where a long name
        ends up.
        """
        raise UnsupportedError("{} cannot scan".format(self.backend))

    async def find(self, name=None, service=None, *, timeout_ms=10000, active=True):
        """Scan until a device matching ``name`` and/or ``service`` appears.

        Returns its :class:`Device`, or raises :class:`BLETimeoutError`.
        """
        if service is not None:
            service = UUID(service)
        async with self.scan(timeout_ms, active=active) as scanner:
            async for result in scanner:
                if name is not None and result.name() != name:
                    continue
                if service is not None and service not in result.services():
                    continue
                return result.device
        raise BLETimeoutError(
            "no device matching name={!r} service={} in {} ms".format(name, service, timeout_ms)
        )

    async def _connect(self, device, timeout_ms, **options):
        raise UnsupportedError("{} cannot connect".format(self.backend))


# ---------------------------------------------------------------- peripheral side


class Service:
    """A GATT service you serve. Add characteristics by constructing them with it."""

    def __init__(self, uuid):
        self.uuid = UUID(uuid)
        self.characteristics = []

    def __repr__(self):
        return "Service({!r})".format(self.uuid)


class Characteristic:
    """A characteristic in a :class:`Service` you serve.

    The flags are aioble's. ``max_len`` is the largest value a central may
    write; MicroPython's default buffer is 20 bytes, so raise it for anything
    that takes whole MTU-sized writes. With ``capture=True``, ``written()``
    returns every write as ``(connection, data)``, in order, instead of just
    the last writer. ``encrypted=True`` refuses a central that hasn't paired
    (``GattError`` with status ``INSUFFICIENT_ENCRYPTION``) until it does;
    ``authenticated=True`` also refuses one that paired without a passkey
    (``INSUFFICIENT_AUTHENTICATION``).
    """

    def __init__(
        self,
        service,
        uuid,
        read=False,
        write=False,
        write_no_response=False,
        notify=False,
        indicate=False,
        initial=None,
        capture=False,
        max_len=20,
        encrypted=False,
        authenticated=False,
    ):
        service.characteristics.append(self)
        self.service = service
        self.uuid = UUID(uuid)
        flags = 0
        if read:
            flags |= FLAG_READ
        if write:
            flags |= FLAG_WRITE
        if write_no_response:
            flags |= FLAG_WRITE_NO_RESPONSE
        if notify:
            flags |= FLAG_NOTIFY
        if indicate:
            flags |= FLAG_INDICATE
        self.flags = flags
        self.capture = bool(capture) and bool(flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE))
        self.max_len = max(max_len, len(initial) if initial else 0)
        self._initial = bytes(initial) if initial is not None else None
        #: True when a central must pair (an encrypted link) before it may
        #: read, write or subscribe. HID keyboards serve their reports this way.
        self.encrypted = bool(encrypted) or bool(authenticated)
        #: True when only a link paired with a passkey (or numeric
        #: comparison) may use it: "just works" isn't enough.
        self.authenticated = bool(authenticated)
        #: :class:`Descriptor` objects, in the order they were made.
        self.descriptors = []
        # Set by the backend's register_services(); it does the real work.
        self._impl = None

    def __repr__(self):
        return "Characteristic({!r}, flags=0x{:02x})".format(self.uuid, self.flags)

    def _bound(self):
        if self._impl is None:
            raise BLEError("{!r} is not registered; call ble.register_services() first".format(self))
        return self._impl

    def read(self):
        """The local value, as bytes."""
        if self._impl is None:
            return self._initial or b""
        return self._impl.read()

    def write(self, data, send_update=False):
        """Set the local value. ``send_update`` also notifies or indicates subscribers."""
        if self._impl is None:
            self._initial = bytes(data)
            return
        self._impl.write(bytes(data), send_update)

    def notify(self, connection, data=None):
        """Send ``data`` (or the current value) to ``connection`` as a notification.

        Synchronous, like aioble. ``data`` must fit in ``connection.mtu - 3``
        bytes. Raises :class:`BusyError` when the transmit buffers are full;
        await a moment and send again (``bledev.nus`` shows the loop).
        """
        if not self.flags & FLAG_NOTIFY:
            raise UnsupportedError("{!r} was not created with notify=True".format(self))
        return self._bound().notify(connection, None if data is None else bytes(data))

    async def indicate(self, connection, data=None, timeout_ms=1000):
        """Send an indication and wait for the central to acknowledge it."""
        if not self.flags & FLAG_INDICATE:
            raise UnsupportedError("{!r} was not created with indicate=True".format(self))
        return await self._bound().indicate(connection, None if data is None else bytes(data), timeout_ms)

    async def written(self, timeout_ms=None):
        """Wait for a central to write this characteristic.

        Returns the writer's :class:`Connection`, or ``(connection, data)``
        with ``capture=True``. It serves every connection, so it does not end
        when one disconnects; pass ``timeout_ms`` or cancel the task.
        """
        if not self.flags & (FLAG_WRITE | FLAG_WRITE_NO_RESPONSE):
            raise UnsupportedError("{!r} is not writable".format(self))
        return await self._bound().written(timeout_ms)


class Descriptor:
    """A read-only descriptor on a :class:`Characteristic` you serve.

    HID uses these: each Report characteristic carries a Report Reference
    (0x2908) saying which report it is. The value is fixed once registered.
    Don't make a CCCD (0x2902); every backend adds that itself for a
    characteristic with ``notify`` or ``indicate``.
    """

    def __init__(self, characteristic, uuid, initial=b""):
        characteristic.descriptors.append(self)
        self.characteristic = characteristic
        self.uuid = UUID(uuid)
        self.value = bytes(initial)

    def __repr__(self):
        return "Descriptor({!r})".format(self.uuid)


# ---------------------------------------------------------------- central side


class Device:
    """A peer found by a scan, or named by address. ``connect()`` it.

    ``address`` is a string: ``"aa:bb:cc:dd:ee:ff"`` on a board, and whatever
    the OS uses on a host (macOS and browsers hide real addresses). ``addr``
    holds the six raw bytes where the backend knows them, else ``None``.
    """

    def __init__(self, ble, address, addr_type=ADDR_PUBLIC, name=None, native=None):
        self._ble = ble
        if isinstance(address, (bytes, bytearray)):
            self.addr = bytes(address)
            address = ":".join(_hex(bytes((b,))) for b in self.addr)
        else:
            self.addr = None
        self.address = address
        self.addr_type = addr_type
        self.name = name
        #: The backend's own object for this device (aioble Device, bleak BLEDevice, ...).
        self.native = native

    def addr_hex(self):
        return self.address

    def __eq__(self, other):
        return isinstance(other, Device) and self.address == other.address

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.address)

    def __repr__(self):
        return "Device({!r}, name={!r})".format(self.address, self.name)

    async def connect(self, timeout_ms=10000, **options):
        """Connect as central and return the :class:`Connection`.

        Options a backend understands (``min_conn_interval_us``,
        ``max_conn_interval_us`` on a board) pass through; others are ignored.
        """
        return await self._ble._connect(self, timeout_ms, **options)


class ScanResult:
    """One device's advertisement, as aioble reports it.

    ``name()``, ``services()`` and ``manufacturer()`` are methods, as in
    aioble. ``services()`` returns a list of :class:`UUID`.
    """

    def __init__(
        self, device, rssi=None, name=None, services=(), appearance=0, manufacturer=(), connectable=True, service_data=()
    ):
        self.device = device
        self.rssi = rssi
        self._name = name
        self._services = [UUID(s) for s in services]
        self.appearance = appearance
        self._manufacturer = list(manufacturer)
        self._service_data = [(UUID(u), bytes(d)) for u, d in service_data]
        self.connectable = connectable

    def name(self):
        return self._name

    def services(self):
        return list(self._services)

    def manufacturer(self, filter=None):
        return [(m, d) for m, d in self._manufacturer if filter is None or m == filter]

    def service_data(self, uuid=None):
        """``[(UUID, data), ...]``, optionally only for ``uuid``."""
        if uuid is not None:
            uuid = UUID(uuid)
        return [(u, d) for u, d in self._service_data if uuid is None or u == uuid]

    def __repr__(self):
        return "ScanResult({!r}, rssi={})".format(self.device, self.rssi)


class Scanner:
    """What ``ble.scan()`` returns: an async context manager and async iterator.

    A backend either subclasses this and overrides the three hooks, or pushes
    results into it with ``_push()`` and ``_finish()`` from the event loop.
    """

    def __init__(self, ble, duration_ms, active=False, interval_us=None, window_us=None):
        self._ble = ble
        self.duration_ms = duration_ms
        self.active = active
        self.interval_us = interval_us
        self.window_us = window_us
        self._queue = []
        self._event = asyncio.Event()
        self._done = False

    async def _start(self):
        pass

    async def _stop(self):
        pass

    def _push(self, result):
        self._queue.append(result)
        self._event.set()

    def _finish(self):
        self._done = True
        self._event.set()

    async def __aenter__(self):
        await self._start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.cancel()

    async def cancel(self):
        if not self._done:
            self._finish()
            await self._stop()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if self._queue:
                return self._queue.pop(0)
            if self._done:
                raise StopAsyncIteration
            self._event.clear()
            await self._event.wait()


class _Discovery:
    """An async iterator over a list a coroutine produces on first use."""

    def __init__(self, fetch):
        # A callable returning the coroutine, so an iterator nobody walks
        # never creates one.
        self._fetch = fetch
        self._items = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._items is None:
            self._items = list(await self._fetch())
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class Connection:
    """A live link to one peer, from either side.

    ``role`` is the role *this* side plays: ``"central"`` if it connected,
    ``"peripheral"`` if it advertised. ``mtu`` is the current ATT MTU; one
    notification or write carries ``mtu - 3`` bytes. Use ``async with`` to
    disconnect on exit.

    Service discovery works from either role, but in practice only the
    central uses it.
    """

    def __init__(self, ble, device, role):
        self._ble = ble
        self.device = device
        self.role = role
        self._mtu = DEFAULT_MTU

    @property
    def mtu(self):
        """The current ATT MTU. One packet carries ``mtu - 3`` bytes of value."""
        return self._mtu

    def __repr__(self):
        return "Connection({!r}, role={!r}, mtu={})".format(self.device, self.role, self.mtu)

    def is_connected(self):
        raise NotImplementedError

    async def disconnect(self, timeout_ms=2000):
        """Drop the link and wait for it to be gone."""
        raise NotImplementedError

    async def disconnected(self, timeout_ms=None):
        """Wait until the link drops, from either side."""
        raise NotImplementedError

    @property
    def encrypted(self):
        """True once the link is encrypted (after :meth:`pair`, or a bonded reconnect)."""
        return False

    async def pair(self, bond=True, timeout_ms=30000, passkey=None):
        """Pair with the peer and encrypt the link; with ``bond``, keep the keys.

        Either side may call it; in practice the central does, when a read
        fails with ``INSUFFICIENT_ENCRYPTION``. Without ``passkey`` the
        pairing is "just works", which is what a keyboard without a screen
        does. When the peer shows a passkey (a board with a display),
        ``passkey`` is what to type in: an int, a string of six digits, or a
        callable (plain or async) that returns one when asked, such as one
        that prompts a person. A bonded peer reconnects without pairing again,
        for as long as both sides keep their keys; pairing a bonded peer just
        encrypts the link with the stored keys.

        Raises :class:`PairingError` when pairing fails (a wrong passkey, or
        a peer that lost its half of the bond), and :class:`UnsupportedError`
        on a backend without pairing.
        """
        raise UnsupportedError("{} cannot pair".format(self._ble.backend))

    @property
    def authenticated(self):
        """True when the link's keys came from a passkey or numeric comparison."""
        return False

    async def unpair(self):
        """Forget this peer's keys on this side (and, on a laptop, the OS's pairing)."""
        raise UnsupportedError("{} cannot unpair".format(self._ble.backend))

    async def exchange_mtu(self, mtu=None, timeout_ms=1000):
        """Negotiate a larger ATT MTU and return the result.

        Hosts that negotiate on their own (bleak, browsers) just return the
        current value.
        """
        return self.mtu

    def services(self, uuid=None, timeout_ms=2000):
        """Async-iterate the peer's services, optionally only ``uuid``."""
        uuid = None if uuid is None else UUID(uuid)
        return _Discovery(lambda: self._discover_services(uuid, timeout_ms))

    async def service(self, uuid, timeout_ms=2000):
        """The peer's service ``uuid``, or ``None`` if it has none."""
        uuid = UUID(uuid)
        found = None
        async for service in self.services(uuid, timeout_ms):
            if found is None and service.uuid == uuid:
                found = service
        return found

    async def _discover_services(self, uuid, timeout_ms):
        raise NotImplementedError

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()


class ClientService:
    """A service on the peer, found by discovery."""

    def __init__(self, connection, uuid):
        self.connection = connection
        self.uuid = UUID(uuid)

    def __repr__(self):
        return "ClientService({!r})".format(self.uuid)

    def characteristics(self, uuid=None, timeout_ms=2000):
        uuid = None if uuid is None else UUID(uuid)
        return _Discovery(lambda: self._discover_characteristics(uuid, timeout_ms))

    async def characteristic(self, uuid, timeout_ms=2000):
        """The characteristic ``uuid`` in this service, or ``None``."""
        uuid = UUID(uuid)
        found = None
        async for characteristic in self.characteristics(uuid, timeout_ms):
            if found is None and characteristic.uuid == uuid:
                found = characteristic
        return found

    async def _discover_characteristics(self, uuid, timeout_ms):
        raise NotImplementedError


class ClientCharacteristic:
    """A characteristic on the peer. ``properties`` holds its ``FLAG_*`` bits.

    Notifications and indications are queued in arrival order and never
    silently dropped: a backend whose queue overflows raises
    :class:`BLEError` from the next ``notified()``. Call ``subscribe()``
    before you expect any to arrive.
    """

    def __init__(self, service, uuid, properties):
        self.service = service
        self.connection = service.connection
        self.uuid = UUID(uuid)
        self.properties = properties

    def __repr__(self):
        return "ClientCharacteristic({!r}, properties=0x{:02x})".format(self.uuid, self.properties)

    def _check(self, flag, what):
        if not self.properties & flag:
            raise UnsupportedError("{!r} does not support {}".format(self, what))

    async def read(self, timeout_ms=1000):
        """The value. A backend without long reads (``capabilities()["long_read"]``
        is False: MicroPython) returns at most ``connection.mtu - 1`` bytes."""
        raise NotImplementedError

    def descriptors(self, uuid=None, timeout_ms=2000):
        """Async-iterate this characteristic's descriptors, optionally only ``uuid``."""
        uuid = None if uuid is None else UUID(uuid)
        return _Discovery(lambda: self._discover_descriptors(uuid, timeout_ms))

    async def descriptor(self, uuid, timeout_ms=2000):
        """The descriptor ``uuid`` on this characteristic, or ``None``."""
        uuid = UUID(uuid)
        found = None
        async for d in self.descriptors(uuid, timeout_ms):
            if found is None and d.uuid == uuid:
                found = d
        return found

    async def _discover_descriptors(self, uuid, timeout_ms):
        raise UnsupportedError("{} cannot discover descriptors".format(self.connection._ble.backend))

    async def write(self, data, response=None, timeout_ms=1000):
        """Write ``data`` (at most ``connection.mtu - 3`` bytes).

        ``response=None`` asks for a response only when the characteristic
        doesn't allow writing without one. A write without response waits for
        buffer room rather than failing.
        """
        raise NotImplementedError

    async def subscribe(self, notify=True, indicate=False):
        raise NotImplementedError

    async def notified(self, timeout_ms=None):
        """The next notification's data. Raises :class:`DisconnectedError` if the link drops."""
        raise NotImplementedError

    async def indicated(self, timeout_ms=None):
        raise NotImplementedError

    def _want_response(self, response):
        if response is None:
            return bool(self.properties & FLAG_WRITE) and not self.properties & FLAG_WRITE_NO_RESPONSE
        if response:
            self._check(FLAG_WRITE, "write with response")
        else:
            self._check(FLAG_WRITE_NO_RESPONSE, "write without response")
        return bool(response)


class ClientDescriptor:
    """A descriptor on the peer, found by :meth:`ClientCharacteristic.descriptors`."""

    def __init__(self, characteristic, uuid):
        self.characteristic = characteristic
        self.connection = characteristic.connection
        self.uuid = UUID(uuid)

    def __repr__(self):
        return "ClientDescriptor({!r})".format(self.uuid)

    async def read(self, timeout_ms=1000):
        raise NotImplementedError


def is_adapter(obj):
    """True for a bledev :class:`BLE`; False for a raw ``bluetooth.BLE`` or anything else."""
    return isinstance(obj, BLE)


async def passkey_value(passkey):
    """``passkey`` as an int: it may be an int, a string of digits, or a
    callable (plain or async) returning either. ``None`` stays ``None``."""
    if callable(passkey):
        passkey = passkey()
    if hasattr(passkey, "send"):  # a coroutine
        passkey = await passkey
    if passkey is None:
        return None
    return int(passkey)


async def connect_and_set_up(
    ble, setup, *, name=None, service=None, device=None, timeout_ms=10000, attempts=3, setup_timeout_ms=4000, **options
):
    """Find a device, connect, and run ``await setup(connection)``; returns
    ``(connection, what setup returned)``.

    If the link drops or stalls before ``setup`` finishes, this disconnects
    and tries again, up to ``attempts`` times. Profiles use it (``nus``,
    ``midi``), because a link can come up dead: about one reconnect in fifty
    from Windows, the OS reports a connection the peripheral never saw, and
    the first GATT operation on it hangs until Windows gives up nine seconds
    later. ``setup_timeout_ms`` bounds that wait. ``options`` go to
    ``device.connect()``, except ``pair`` (pair before ``setup``) and
    ``passkey`` (for :meth:`Connection.pair`).
    """
    pair = options.pop("pair", False)
    passkey = options.pop("passkey", None)
    error = None
    stale = False
    for _ in range(attempts):
        target = device
        if target is None:
            target = await ble.find(name=name, service=service, timeout_ms=timeout_ms)
        connection = await target.connect(timeout_ms=timeout_ms, **options)
        if pair:
            # Before discovery: a board that wants pairing refuses the
            # subscriptions setup makes. Pairing waits on a person typing a
            # passkey, so setup_timeout_ms doesn't bound it.
            try:
                await connection.pair(passkey=passkey)
            except BaseException:
                if connection.is_connected():
                    await connection.disconnect()
                raise
            reused = getattr(connection, "reused_bond", False)
        else:
            reused = False
        try:
            return connection, await wait_ms(setup(connection), setup_timeout_ms, "setting up the connection")
        except (DisconnectedError, BLETimeoutError) as e:
            error = e
            stale = reused and isinstance(e, DisconnectedError)
        except BaseException:
            if connection.is_connected():
                await connection.disconnect()
            raise
        try:
            await connection.disconnect()
        except BLEError:
            pass
        # Give a dead link time to be noticed before the next try.
        await sleep_ms(500 * (_ + 1))
    if stale:
        # Every attempt encrypted with keys this host already had, and every
        # link fell. Windows hangs up when the board refuses those keys, but
        # it also hands out links the board never saw, for a while after the
        # board resets; from here the two look the same.
        raise PairingError(
            "every link dropped right after connecting with this host's stored keys. Try again in "
            "a few seconds (after a board reset Windows can hold a dead link); if it keeps "
            "happening, " + STALE_BOND
        )
    raise error
