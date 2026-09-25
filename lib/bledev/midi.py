"""MIDI over Bluetooth LE (BLE-MIDI 1.0), as a MIDI port.

The board advertises the standard BLE-MIDI service; a laptop, a phone, a DAW
or another board connects::

    import bledev.midi as midi

    port = await midi.serve(ble, name="rack")    # on the board
    port = await midi.connect(ble, name="rack")  # anywhere that can be a central

Either way you get a :class:`Port`, which is the same MIDI port usbif hands
out for a USB MIDI function (``usbif.MidiPort``): plain MIDI 1.0 bytes, a
``read(buf)`` that never blocks and a ``write(data)``. So the loop an app
runs over a USB controller runs unchanged over a BLE one::

    parser = usbif.MidiParser()          # or any running-status reader
    n = port.read(buf)
    parser.feed(buf, n)
    for status, data in parser.drain():
        ...

When usbif is installed, :class:`Port` *is* a ``usbif.MidiPort`` subclass.
BLE-MIDI's packets, timestamps, running status and SysEx fragments stay
inside; the codec is :mod:`bledev.midi_codec`. For the sender's timestamps
as well, ``await port.receive()`` returns ``(timestamp, message)``.

The characteristic accepts writes with and without response and notifies, as
the BLE-MIDI specification asks, and reads back empty. Every device and host
that speaks BLE-MIDI (macOS and iOS, Android, Windows MIDI Services, BLE-MIDI
controllers) uses the same two UUIDs.
"""

import sys

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

from . import (
    BLEError,
    BLETimeoutError,
    BusyError,
    Characteristic,
    DisconnectedError,
    MAX_MTU,
    Service,
    UnsupportedError,
    UUID,
    connect_and_set_up,
    is_adapter,
    sleep_ms,
    wait_ms,
)
from .midi_codec import TIMESTAMP_MASK, Decoder, Encoder, Splitter

SERVICE = UUID("03b80e5a-ede8-4b33-a751-6ce34ec4c700")
CHARACTERISTIC = UUID("7772e5db-3868-4112-a1a9-f2669d106bf3")

#: The ATT MTU both sides ask for. A note is 5 bytes on the air, so this
#: only matters for SysEx and bursts; it's nus's value, for the same reason.
MTU = 247

#: Received messages a port keeps for a reader that isn't reading.
QUEUE_LIMIT = 1024

_POLL_MS = 50
_BUSY_WAIT_MS = 1

# ---------------------------------------------------------------- the port contract

# usbif's MidiPort is the contract (usbif/lib/usbif/__init__.py). When usbif
# is here, subclass it so isinstance() agrees; when it isn't, the same
# contract, written out.
try:
    from usbif import INOUT, MidiPort as _PortBase, MidiPortInfo
except Exception:  # ImportError, or a usbif that can't load on this host
    IN = "in"
    OUT = "out"
    INOUT = "inout"

    try:
        from collections import namedtuple
    except ImportError:  # pragma: no cover
        from ucollections import namedtuple

    MidiPortInfo = namedtuple("MidiPortInfo", "id name direction")

    class _PortBase:
        """usbif.MidiPort's contract: a MIDI 1.0 byte stream on one port."""

        def __init__(self, info):
            self.info = info
            self.direction = info.direction
            self.is_open = True

        def _check(self, want):
            if not self.is_open:
                raise OSError("MIDI port is closed")
            if self.direction not in (want, INOUT):
                raise OSError("MIDI port {!r} is {}-only".format(self.info.name, self.direction))

        def read(self, buf):
            """Read waiting MIDI bytes into ``buf``; returns how many. Never blocks."""
            self._check(IN)
            return self._read(buf)

        def write(self, data):
            """Write MIDI bytes; returns how many were accepted."""
            self._check(OUT)
            return self._write(data)

        def close(self):
            if not self.is_open:
                return
            try:
                self._close()
            finally:
                self.is_open = False

        deinit = close

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.close()


if sys.implementation.name == "micropython":
    import time

    def now_ms():
        """This host's BLE-MIDI clock: milliseconds, 13 bits."""
        return time.ticks_ms() & TIMESTAMP_MASK

elif sys.implementation.name == "circuitpython":
    # time.monotonic() is a float that loses milliseconds after a few hours.
    try:
        from supervisor import ticks_ms as _ticks_ms
    except ImportError:  # the unix port has no supervisor, and MicroPython's time
        from time import ticks_ms as _ticks_ms

    def now_ms():
        """This host's BLE-MIDI clock: milliseconds, 13 bits."""
        return _ticks_ms() & TIMESTAMP_MASK

else:
    import time

    def now_ms():
        """This host's BLE-MIDI clock: milliseconds, 13 bits."""
        return int(time.monotonic() * 1000) & TIMESTAMP_MASK


def _adapter(ble):
    if is_adapter(ble):
        return ble
    if hasattr(ble, "gap_advertise"):
        from . import mpble

        return mpble.get(ble)
    if hasattr(ble, "start_advertising") and hasattr(ble, "erase_bonding"):
        from . import cpble  # CircuitPython's _bleio.adapter

        return cpble.get(ble)
    raise TypeError("expected a bledev adapter, not {!r}".format(ble))


def _set_mtu(ble, mtu):
    try:
        ble.config(mtu=mtu)
    except UnsupportedError:
        pass


class Port(_PortBase):
    """One BLE-MIDI link, as a MIDI port. Made by :func:`serve` or :func:`connect`.

    ``read(buf)`` and ``write(data)`` are usbif's: plain MIDI bytes, never
    blocking. Writes are sent from a task, packed into as few packets as the
    link allows, so the app needs a running asyncio loop, as everything in
    bledev does. ``await drain()`` waits until they're on the air.

    ``await receive()`` returns the next ``(timestamp, message)``; the
    timestamp is the sender's 13-bit millisecond clock. Use it or ``read()``,
    not both. ``overflowed`` turns true if more than ``queue_limit``
    messages waited unread; they are counted in ``dropped``, not lost
    silently.
    """

    def __init__(self, connection, name, *, queue_limit=QUEUE_LIMIT, running_status=True):
        _PortBase.__init__(self, MidiPortInfo("ble:" + connection.device.address, name, INOUT))
        self.connection = connection
        self.queue_limit = queue_limit
        self.dropped = 0
        self.decode_errors = 0
        self.messages_in = 0
        self.messages_out = 0
        self._messages = []
        self._pending = b""
        self._arrived = asyncio.Event()
        self._decoder = Decoder()
        self._encoder = Encoder(running_status)
        self._splitter = Splitter()
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._send_error = None
        self._closed = False
        self._sender = asyncio.create_task(self._send_loop())

    @property
    def overflowed(self):
        return self.dropped > 0

    # -- receiving

    def _packet(self, data):
        messages = self._decoder.decode(data)
        self.decode_errors = self._decoder.errors
        for item in messages:
            if len(self._messages) >= self.queue_limit:
                self.dropped += 1
            else:
                self._messages.append(item)
                self.messages_in += 1
        if messages:
            self._arrived.set()

    def _read(self, buf):
        n = 0
        size = len(buf)
        while n < size:
            if not self._pending:
                if not self._messages:
                    break
                self._pending = self._messages.pop(0)[1]
            take = min(size - n, len(self._pending))
            buf[n : n + take] = self._pending[:take]
            self._pending = self._pending[take:]
            n += take
        return n

    def any(self):
        """How many messages are waiting."""
        return len(self._messages) + (1 if self._pending else 0)

    async def receive(self, timeout_ms=None):
        """The next ``(timestamp, message)``. Raises :class:`DisconnectedError`
        once the link has closed and everything that arrived is read."""
        while True:
            if self._messages:
                return self._messages.pop(0)
            if self._closed or not self.connection.is_connected():
                raise DisconnectedError("MIDI link closed")
            self._arrived.clear()
            await wait_ms(self._any_news(), timeout_ms, "receive")

    async def _any_news(self):
        await self._arrived.wait()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except DisconnectedError:
            raise StopAsyncIteration

    # -- sending

    def _write(self, data):
        if self._send_error is not None:
            raise self._send_error
        if not self.connection.is_connected():
            raise DisconnectedError("MIDI link closed")
        ts = now_ms()
        count = 0
        for message in self._splitter.feed(data):
            self._encoder.put(ts, message)
            count += 1
        if count:
            self.messages_out += count
            self._idle.clear()
            self._wake.set()
        return len(data)

    def send(self, message, timestamp=None):
        """Queue one complete message, optionally with its own timestamp."""
        self._check("out")
        self._encoder.put(now_ms() if timestamp is None else timestamp, message)
        self.messages_out += 1
        self._idle.clear()
        self._wake.set()

    async def drain(self):
        """Wait until everything written has been handed to the radio."""
        await self._idle.wait()
        if self._send_error is not None:
            raise self._send_error

    async def _send_loop(self):
        try:
            while not self._closed:
                await self._wake.wait()
                self._wake.clear()
                while self._encoder.pending():
                    packet = self._encoder.packet(self.connection.mtu - 3)
                    await self._send_packet(packet)
                self._idle.set()
        except Exception as e:
            self._send_error = e if isinstance(e, BLEError) else BLEError("MIDI send: {}".format(e))
            self._idle.set()

    async def _send_packet(self, packet):
        raise NotImplementedError

    # -- closing

    def _close(self):
        self._finish()
        if self.connection.is_connected():
            try:
                asyncio.create_task(self.connection.disconnect())
            except Exception:
                pass

    async def aclose(self):
        """Close the port and wait for the disconnect."""
        was_open = self.is_open
        self.is_open = False
        self._finish()
        if was_open and self.connection.is_connected():
            await self.connection.disconnect()

    def _finish(self):
        self._closed = True
        self._wake.set()
        self._arrived.set()


class _ServerPort(Port):
    def __init__(self, connection, server, **options):
        Port.__init__(self, connection, server.name, **options)
        self._server = server

    async def _send_packet(self, packet):
        char = self._server.char
        while True:
            try:
                char.notify(self.connection, packet)
                return
            except BusyError:
                if not self.connection.is_connected():
                    raise DisconnectedError("MIDI link closed while sending")
                await sleep_ms(_BUSY_WAIT_MS)


class _ClientPort(Port):
    def __init__(self, connection, char, name, **options):
        Port.__init__(self, connection, name, **options)
        self._char = char
        self._no_response = bool(char.properties & 0x0004)
        self._receiver = asyncio.create_task(self._receive())

    async def _receive(self):
        try:
            while True:
                self._packet(await self._char.notified())
        except Exception:
            pass
        finally:
            self._finish()

    async def _send_packet(self, packet):
        await self._char.write(packet, response=not self._no_response)


class _Server:
    """The BLE-MIDI service on one adapter, shared by every port it serves."""

    def __init__(self, ble, name):
        self.ble = ble
        self.name = name
        self.service = Service(SERVICE)
        self.char = Characteristic(
            self.service,
            CHARACTERISTIC,
            read=True,
            write=True,
            write_no_response=True,
            notify=True,
            capture=True,
            max_len=MAX_MTU - 3,
            initial=b"",
        )
        self.ports = []
        self._task = None

    def add(self, port):
        self.ports.append(port)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def _port_for(self, connection):
        for port in self.ports:
            if port.connection is connection or port.connection == connection:
                return port
        return None

    def _retire_gone(self):
        for port in list(self.ports):
            if port._closed or not port.connection.is_connected():
                self.ports.remove(port)
                port._finish()

    async def _run(self):
        try:
            while self.ports:
                try:
                    connection, data = await self.char.written(timeout_ms=_POLL_MS)
                except BLETimeoutError:
                    self._retire_gone()
                    continue
                port = self._port_for(connection)
                if port is not None:
                    port._packet(data)
        finally:
            self._task = None


def _server_for(ble, name, mtu):
    server = getattr(ble, "_midi_server", None)
    if server is None:
        _set_mtu(ble, mtu)
        server = _Server(ble, name)
        ble.register_services(server.service)
        ble._midi_server = server
    server.name = name
    return server


async def serve(ble, name="bledev-midi", *, timeout_ms=None, interval_us=100000, mtu=MTU, **options):
    """Advertise BLE-MIDI as ``name`` and return a :class:`Port` when a
    central connects. Call it again for the next connection.

    The service is registered once per adapter, the first time; don't register
    other services on the same adapter afterwards.
    """
    ble = _adapter(ble)
    server = _server_for(ble, name, mtu)
    # Hosts that pair (Windows, macOS) name the MIDI port after the GAP device
    # name, not the advertised one; without this Windows lists "MPY ESP32".
    try:
        ble.config(gap_name=name)
    except (UnsupportedError, ValueError, OSError):
        pass
    connection = await ble.advertise(interval_us, name=name, services=[SERVICE], timeout_ms=timeout_ms)
    port = _ServerPort(connection, server, **options)
    server.add(port)
    return port


async def connect(
    ble, name=None, *, device=None, timeout_ms=10000, mtu=MTU, queue_limit=QUEUE_LIMIT, running_status=True, **connect_options
):
    """Find a BLE-MIDI device (by ``name``, or the first one advertising the
    service), connect, subscribe, and return a :class:`Port`.

    ``connect_options`` go to ``device.connect()``: on a board,
    ``min_conn_interval_us=7500, max_conn_interval_us=7500`` asks for the
    shortest connection interval, which is what a MIDI link wants.
    """
    ble = _adapter(ble)
    _set_mtu(ble, mtu)

    async def setup(connection):
        try:
            await connection.exchange_mtu(mtu)
        except (UnsupportedError, BLETimeoutError):
            pass
        service = await connection.service(SERVICE)
        if service is None:
            raise BLEError("{!r} has no BLE-MIDI service".format(connection.device))
        char = await service.characteristic(CHARACTERISTIC)
        if char is None:
            raise BLEError("{!r}: the BLE-MIDI service has no MIDI characteristic".format(connection.device))
        await char.subscribe(notify=True)
        return char

    connection, char = await connect_and_set_up(
        ble, setup, name=name, service=SERVICE, device=device, timeout_ms=timeout_ms, **connect_options
    )
    label = name or getattr(connection.device, "name", None) or connection.device.address
    return _ClientPort(connection, char, label, queue_limit=queue_limit, running_status=running_status)

