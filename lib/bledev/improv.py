"""Wi-Fi setup over BLE with the Improv standard (https://www.improv-wifi.com/ble/).

A board with no Wi-Fi credentials advertises the Improv service; a phone, a
laptop or another board sends it a network name and password; the board joins
and answers with a URL. ESPHome, WLED and Home Assistant speak the same
protocol, so their tools can provision a bledev board too.

On the board (``serve()`` returns once it has joined)::

    import bledev.mpble, bledev.improv as improv
    url = await improv.serve(bledev.mpble.get(), name="kitchen")

From a laptop or another board::

    import bledev.improv as improv
    url = await improv.provision(ble, ssid, password, name="kitchen")

A network that can't be joined raises :class:`ImprovError` with
``code == ERROR_UNABLE_TO_CONNECT``, which the board also reports in its error
characteristic.

The credentials cross the air unencrypted; that is the Improv standard, and
the reason a board should only serve it until it's set up. ``serve()`` never
logs them. Saving them for the next boot is the app's job (``on_join``), so
nothing here writes a credential to the filesystem.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import sys

from . import (
    BLEError,
    BLETimeoutError,
    BusyError,
    Characteristic,
    DisconnectedError,
    MAX_MTU,
    Service,
    UUID,
    sleep_ms,
    wait_ms,
)

SERVICE = UUID("00467768-6228-2272-4663-277478268000")
STATE = UUID("00467768-6228-2272-4663-277478268001")
ERROR = UUID("00467768-6228-2272-4663-277478268002")
RPC = UUID("00467768-6228-2272-4663-277478268003")
RESULT = UUID("00467768-6228-2272-4663-277478268004")
CAPABILITIES = UUID("00467768-6228-2272-4663-277478268005")
#: The 16-bit UUID the advertisement's service data is filed under.
SERVICE_DATA = UUID(0x4677)

STATE_AUTHORIZATION_REQUIRED = 0x01
STATE_AUTHORIZED = 0x02
STATE_PROVISIONING = 0x03
STATE_PROVISIONED = 0x04

ERROR_NONE = 0x00
ERROR_INVALID_RPC = 0x01
ERROR_UNKNOWN_RPC = 0x02
ERROR_UNABLE_TO_CONNECT = 0x03
ERROR_NOT_AUTHORIZED = 0x04
ERROR_BAD_HOSTNAME = 0x05
ERROR_UNKNOWN = 0xFF

CMD_WIFI_SETTINGS = 0x01
CMD_IDENTIFY = 0x02
CMD_DEVICE_INFO = 0x03
CMD_WIFI_SCAN = 0x04
CMD_HOSTNAME = 0x05
CMD_DEVICE_NAME = 0x06

CAP_IDENTIFY = 0x01
CAP_DEVICE_INFO = 0x02
CAP_WIFI_SCAN = 0x04
CAP_HOSTNAME = 0x08

#: How long an authorization given with ``authorize()`` lasts (the standard
#: suggests about a minute).
AUTHORIZATION_MS = 60000

_ERROR_NAMES = {
    ERROR_INVALID_RPC: "invalid RPC packet",
    ERROR_UNKNOWN_RPC: "unknown RPC command",
    ERROR_UNABLE_TO_CONNECT: "unable to connect",
    ERROR_NOT_AUTHORIZED: "not authorized",
    ERROR_BAD_HOSTNAME: "bad hostname",
    ERROR_UNKNOWN: "unknown error",
}


class ImprovError(BLEError):
    """The device reported an Improv error. ``code`` is one of ``ERROR_*``."""

    def __init__(self, code, message=None):
        super().__init__(message or "Improv error 0x{:02x}: {}".format(code, _ERROR_NAMES.get(code, "?")))
        self.code = code


# ---------------------------------------------------------------- packets


def checksum(data):
    """The standard's checksum: the sum of every byte, keeping the low byte."""
    return sum(data) & 0xFF


def _encode(s):
    return s.encode() if isinstance(s, str) else bytes(s)


def pack(command, *strings):
    """An RPC command or result: ``command, length, (len, bytes)..., checksum``."""
    body = bytearray()
    for s in strings:
        s = _encode(s)
        if len(s) > 255:
            raise ValueError("an Improv string is at most 255 bytes")
        body.append(len(s))
        body.extend(s)
    if len(body) > 255:
        raise ValueError("an Improv packet carries at most 255 bytes")
    packet = bytes((command, len(body))) + bytes(body)
    return packet + bytes((checksum(packet),))


def packet_length(buffer):
    """The full length of the packet that starts ``buffer``, or ``None`` until two bytes are in."""
    if len(buffer) < 2:
        return None
    return buffer[1] + 3


def unpack(packet):
    """``(command, [bytes, ...])`` from one whole packet. Raises :class:`ImprovError`."""
    packet = bytes(packet)
    if len(packet) < 3 or len(packet) != packet[1] + 3:
        raise ImprovError(ERROR_INVALID_RPC, "Improv packet has the wrong length")
    if checksum(packet[:-1]) != packet[-1]:
        raise ImprovError(ERROR_INVALID_RPC, "Improv packet checksum mismatch")
    body = packet[2:-1]
    strings = []
    i = 0
    while i < len(body):
        n = body[i]
        if i + 1 + n > len(body):
            raise ImprovError(ERROR_INVALID_RPC, "Improv string runs past the packet")
        strings.append(body[i + 1 : i + 1 + n])
        i += 1 + n
    return packet[0], strings


def service_data(state, capabilities):
    """The six bytes the advertisement carries under :data:`SERVICE_DATA`."""
    return bytes((state, capabilities, 0, 0, 0, 0))


# ---------------------------------------------------------------- joining Wi-Fi on a board

# network.WLAN statuses that mean the attempt failed rather than is under way.
_FAILED = (200, 201, 202, 203, 204)  # beacon timeout, no AP, wrong password, assoc fail, handshake timeout
_FAIL_AFTER_MS = 5000


async def wifi_connect(ssid, password, timeout_ms=20000):
    """Join ``ssid`` with MicroPython's ``network.WLAN``; the IP address, or ``None``.

    A status that means failure (no such network, wrong password) ends the
    attempt after it has held for five seconds, since the ESP32 retries a
    few times on its own; otherwise it waits up to ``timeout_ms``.
    """
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.disconnect()
    except OSError:
        pass
    wlan.connect(ssid, password)
    waited = 0
    failing = 0
    while waited < timeout_ms:
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            if ip and ip != "0.0.0.0":
                return ip
        status = wlan.status()
        failing = failing + 250 if status in _FAILED or status == getattr(network, "STAT_IDLE", -1) else 0
        if failing >= _FAIL_AFTER_MS:
            break
        await sleep_ms(250)
        waited += 250
    try:
        wlan.disconnect()
    except OSError:
        pass
    return None


def wifi_scan():
    """``[(ssid, rssi, secured), ...]`` from ``network.WLAN.scan()``, strongest first."""
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    found = {}
    for ssid, _bssid, _channel, rssi, security, _hidden in wlan.scan():
        ssid = ssid.decode("utf-8", "replace") if isinstance(ssid, bytes) else ssid
        if ssid and (ssid not in found or found[ssid][1] < rssi):
            found[ssid] = (ssid, rssi, security != 0)
    return sorted(found.values(), key=lambda n: -n[1])


def _default_device_info(name):
    impl = sys.implementation
    version = ".".join(str(v) for v in impl.version[:3])
    chip = sys.platform
    try:
        import os

        chip = os.uname().machine
    except (ImportError, AttributeError):
        pass
    return (impl.name, version, chip, name)


# ---------------------------------------------------------------- the device side


class Server:
    """The Improv service on a peripheral adapter.

    ``join(ssid, password)`` is an async callable returning the IP address
    as a string, or ``None`` if the network couldn't be joined; the default
    is :func:`wifi_connect`, on MicroPython. ``redirect`` is the URL the client
    is sent to afterwards, with ``{ip}`` filled in; ``None`` sends none.
    ``on_join(ssid, password, ip)`` runs after a successful join, so the app
    can store the credentials for the next boot.

    ``require_authorization=True`` starts in "authorization required" until
    :meth:`authorize` (from a button, say). ``identify`` is a callable that
    makes the device noticeable (blink, beep); ``scan`` returns
    ``[(ssid, rssi, secured), ...]``. Each one given turns on its capability.
    """

    def __init__(
        self,
        ble,
        name="improv",
        *,
        join=None,
        redirect="http://{ip}/",
        on_join=None,
        require_authorization=False,
        identify=None,
        scan=None,
        device_info=None,
    ):
        self.ble = ble
        self.name = name
        self._join = join or wifi_connect
        self.redirect = redirect
        self._on_join = on_join
        self._identify = identify
        if scan is None and sys.implementation.name == "micropython":
            scan = wifi_scan
        self._scan = scan
        self._device_info = tuple(device_info or _default_device_info(name))
        caps = CAP_DEVICE_INFO
        if identify is not None:
            caps |= CAP_IDENTIFY
        if scan is not None:
            caps |= CAP_WIFI_SCAN
        self.capabilities = caps
        self.state = STATE_AUTHORIZATION_REQUIRED if require_authorization else STATE_AUTHORIZED
        self.error = ERROR_NONE
        self.url = None
        self.ip = None
        self._require_authorization = require_authorization
        self._authorized_until = None
        self._connection = None

        self.service = Service(SERVICE)
        self._state = Characteristic(self.service, STATE, read=True, notify=True, initial=bytes((self.state,)))
        self._error = Characteristic(self.service, ERROR, read=True, notify=True, initial=b"\x00")
        self._rpc = Characteristic(
            self.service, RPC, write=True, write_no_response=True, capture=True, max_len=MAX_MTU - 3
        )
        self._result = Characteristic(self.service, RESULT, read=True, notify=True, max_len=260)
        self._caps = Characteristic(self.service, CAPABILITIES, read=True, initial=bytes((caps,)))
        self._registered = False

    # -- state

    def authorize(self):
        """Mark the device authorized for :data:`AUTHORIZATION_MS` (from a button press)."""
        if self.state == STATE_AUTHORIZATION_REQUIRED:
            self._authorized_until = AUTHORIZATION_MS
            self.state = STATE_AUTHORIZED
            self._state.write(bytes((STATE_AUTHORIZED,)))
            if self._connection is not None:
                asyncio.create_task(self._notify(self._state, bytes((STATE_AUTHORIZED,))))

    async def _set_state(self, state):
        self.state = state
        self._state.write(bytes((state,)))
        await self._notify(self._state, bytes((state,)))

    async def _set_error(self, error):
        self.error = error
        self._error.write(bytes((error,)))
        await self._notify(self._error, bytes((error,)))

    async def _notify(self, characteristic, data):
        connection = self._connection
        if connection is None:
            return
        size = connection.mtu - 3
        for i in range(0, len(data), size):
            while True:
                try:
                    characteristic.notify(connection, data[i : i + size])
                    break
                except BusyError:
                    await sleep_ms(2)
                except DisconnectedError:
                    return

    async def _send_result(self, command, *strings):
        packet = pack(command, *strings)
        self._result.write(packet)
        await self._notify(self._result, packet)

    # -- serving

    def _register(self):
        if not self._registered:
            self.ble.register_services(self.service)
            self._registered = True

    async def serve(self, timeout_ms=None):
        """Advertise until a client provisions the device; return the redirect URL (or IP).

        ``timeout_ms`` bounds each wait for a client to connect.
        """
        self._register()
        while True:
            connection = await self.ble.advertise(
                name=self.name,
                services=[SERVICE],
                service_data=[(SERVICE_DATA, service_data(self.state, self.capabilities))],
                timeout_ms=timeout_ms,
            )
            if await self.session(connection):
                return self.url if self.url is not None else self.ip

    async def session(self, connection):
        """Serve one connected client. True once the device is provisioned."""
        self._connection = connection
        buffer = bytearray()
        clock = 0
        try:
            while connection.is_connected():
                try:
                    writer, data = await self._rpc.written(timeout_ms=250)
                except BLETimeoutError:
                    clock += 250
                    await self._tick(250)
                    if self.state == STATE_PROVISIONED and clock > 3000:
                        break  # the client has had time to read the result
                    continue
                if writer is not connection and writer != connection:
                    continue
                buffer.extend(data)
                while True:
                    size = packet_length(buffer)
                    if size is None or len(buffer) < size:
                        break
                    packet, buffer = bytes(buffer[:size]), buffer[size:]
                    clock = 0
                    await self._handle(packet)
        finally:
            self._connection = None
            if connection.is_connected() and self.state == STATE_PROVISIONED:
                try:
                    await connection.disconnect()
                except BLEError:
                    pass
        return self.state == STATE_PROVISIONED

    async def _tick(self, ms):
        if self._authorized_until is not None:
            self._authorized_until -= ms
            if self._authorized_until <= 0:
                self._authorized_until = None
                if self.state == STATE_AUTHORIZED:
                    await self._set_state(STATE_AUTHORIZATION_REQUIRED)

    async def _handle(self, packet):
        try:
            command, strings = unpack(packet)
        except ImprovError as e:
            await self._set_error(e.code)
            return
        if command == CMD_WIFI_SETTINGS:
            await self._wifi(strings)
        elif command == CMD_IDENTIFY and self._identify is not None:
            await self._set_error(ERROR_NONE)
            self._identify()
        elif command == CMD_DEVICE_INFO:
            await self._set_error(ERROR_NONE)
            await self._send_result(CMD_DEVICE_INFO, *self._device_info)
        elif command == CMD_WIFI_SCAN and self._scan is not None:
            await self._set_error(ERROR_NONE)
            for ssid, rssi, secured in self._scan():
                await self._send_result(CMD_WIFI_SCAN, ssid, str(rssi), "YES" if secured else "NO")
            await self._send_result(CMD_WIFI_SCAN)
        else:
            await self._set_error(ERROR_UNKNOWN_RPC)

    async def _wifi(self, strings):
        if len(strings) != 2:
            await self._set_error(ERROR_INVALID_RPC)
            return
        if self.state == STATE_AUTHORIZATION_REQUIRED:
            await self._set_error(ERROR_NOT_AUTHORIZED)
            return
        ssid = strings[0].decode()
        password = strings[1].decode()
        await self._set_error(ERROR_NONE)
        await self._set_state(STATE_PROVISIONING)
        try:
            ip = await self._join(ssid, password)
        except Exception:
            ip = None
        if not ip:
            await self._set_error(ERROR_UNABLE_TO_CONNECT)
            await self._set_state(STATE_AUTHORIZATION_REQUIRED if self._require_authorization and self._authorized_until is None else STATE_AUTHORIZED)
            return
        self.ip = ip
        self.url = self.redirect.format(ip=ip) if self.redirect else None
        if self._on_join is not None:
            self._on_join(ssid, password, ip)
        await self._set_state(STATE_PROVISIONED)
        if self.url:
            await self._send_result(CMD_WIFI_SETTINGS, self.url)
        else:
            await self._send_result(CMD_WIFI_SETTINGS)


async def serve(ble, name="improv", *, timeout_ms=None, **options):
    """Serve Improv on ``ble`` until provisioned; return the redirect URL (or the IP).

    ``options`` go to :class:`Server`.
    """
    return await Server(ble, name, **options).serve(timeout_ms)


# ---------------------------------------------------------------- the client side


class Client:
    """A connection to an Improv device. Use :meth:`connect`, or :func:`provision`."""

    def __init__(self, connection, chars):
        self.connection = connection
        self._state, self._error, self._rpc, self._result, self._caps = chars
        self._events = []
        self._event = asyncio.Event()
        self._tasks = []
        self.capabilities = 0

    @classmethod
    async def connect(cls, ble, name=None, *, device=None, timeout_ms=10000):
        """Find the device (by ``name``, or the first advertising Improv), connect, subscribe."""
        if device is None:
            device = await ble.find(name=name, service=SERVICE, timeout_ms=timeout_ms)
        connection = await device.connect(timeout_ms=timeout_ms)
        try:
            try:
                await connection.exchange_mtu(MAX_MTU)
            except BLEError:
                pass
            service = await connection.service(SERVICE)
            if service is None:
                raise BLEError("{!r} has no Improv service".format(device))
            chars = []
            for uuid in (STATE, ERROR, RPC, RESULT, CAPABILITIES):
                c = await service.characteristic(uuid)
                if c is None:
                    raise BLEError("{!r}: the Improv service lacks {}".format(device, uuid))
                chars.append(c)
            client = cls(connection, chars)
            await client._start()
        except BaseException:
            if connection.is_connected():
                await connection.disconnect()
            raise
        return client

    async def _start(self):
        for kind, c in (("state", self._state), ("error", self._error), ("result", self._result)):
            await c.subscribe(notify=True)
            self._tasks.append(asyncio.create_task(self._watch(kind, c)))
        caps = await self._caps.read()
        self.capabilities = caps[0] if caps else 0

    async def _watch(self, kind, characteristic):
        try:
            while True:
                # Await first: ``self._events`` is replaced between commands.
                data = await characteristic.notified()
                self._events.append((kind, data))
                self._event.set()
        except BLEError as e:
            self._events.append(("gone", e))
            self._event.set()

    async def _next_event(self, timeout_ms):
        while not self._events:
            self._event.clear()
            await wait_ms(self._event.wait(), timeout_ms, "Improv reply")
        return self._events.pop(0)

    async def state(self):
        """The device's current ``STATE_*``."""
        return (await self._state.read())[0]

    async def error(self):
        """The device's current ``ERROR_*``."""
        return (await self._error.read())[0]

    async def close(self):
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self.connection.is_connected():
            await self.connection.disconnect()

    async def _command(self, packet):
        size = self.connection.mtu - 3
        for i in range(0, len(packet), size):
            await self._rpc.write(packet[i : i + size])

    async def _results(self, command, timeout_ms):
        """Collect RPC results for ``command``; raise on a device error."""
        buffer = bytearray()
        while True:
            kind, data = await self._next_event(timeout_ms)
            if kind == "gone":
                raise data
            if kind == "error" and data and data[0] != ERROR_NONE:
                raise ImprovError(data[0])
            if kind == "state":
                continue
            if kind == "result":
                buffer.extend(data)
                size = packet_length(buffer)
                if size is not None and len(buffer) >= size:
                    packet, buffer = bytes(buffer[:size]), buffer[size:]
                    got_command, strings = unpack(packet)
                    if got_command == command:
                        return strings

    async def send_wifi(self, ssid, password, timeout_ms=60000):
        """Send credentials; return the redirect URL (``""`` if the device sends none).

        Raises :class:`ImprovError` (``ERROR_UNABLE_TO_CONNECT`` for a network
        the device couldn't join).
        """
        state = await self.state()
        if state == STATE_AUTHORIZATION_REQUIRED:
            state = await self._await_state(STATE_AUTHORIZED, timeout_ms)
        self._events = []
        await self._command(pack(CMD_WIFI_SETTINGS, ssid, password))
        strings = await self._results(CMD_WIFI_SETTINGS, timeout_ms)
        state = await self.state()
        if state != STATE_PROVISIONED:
            raise ImprovError(ERROR_UNKNOWN, "the device sent a result but reports state {}".format(state))
        return strings[0].decode() if strings else ""

    async def _await_state(self, want, timeout_ms):
        while True:
            try:
                kind, data = await self._next_event(timeout_ms)
            except BLETimeoutError:
                raise ImprovError(ERROR_NOT_AUTHORIZED, "the device was not authorized in time")
            if kind == "gone":
                raise data
            if kind == "state" and data and data[0] == want:
                return want

    async def device_info(self, timeout_ms=5000):
        """``[firmware, version, chip, device name, ...]`` as strings."""
        self._events = []
        await self._command(pack(CMD_DEVICE_INFO))
        return [s.decode() for s in await self._results(CMD_DEVICE_INFO, timeout_ms)]

    async def identify(self):
        await self._command(pack(CMD_IDENTIFY))

    async def scan(self, timeout_ms=20000):
        """``[(ssid, rssi, secured), ...]`` as the device sees them."""
        self._events = []
        await self._command(pack(CMD_WIFI_SCAN))
        found = []
        while True:
            strings = await self._results(CMD_WIFI_SCAN, timeout_ms)
            if not strings:
                return found
            found.append((strings[0].decode(), int(strings[1]), strings[2] == b"YES"))


async def provision(ble, ssid, password, name=None, *, device=None, timeout_ms=60000):
    """Connect to an Improv device, send it ``ssid`` and ``password``, and return its redirect URL.

    Raises :class:`ImprovError` if it can't join.
    """
    client = await Client.connect(ble, name, device=device, timeout_ms=min(timeout_ms, 20000))
    try:
        return await client.send_wifi(ssid, password, timeout_ms)
    finally:
        await client.close()
