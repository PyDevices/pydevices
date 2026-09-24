"""Nordic UART Service: a two-way byte stream over BLE.

The board advertises and the other side connects::

    import bledev.nus as nus

    link = await nus.serve(ble, name="rack")    # on the board
    link = await nus.connect(ble, name="rack")  # on the laptop, phone or another board

Both return a :class:`Link`, which reads like an asyncio stream::

    await link.write(b"hello\\n")
    line = await link.readline()
    async for line in link:        # lines until the link closes
        ...
    await link.close()

The UUIDs are Nordic's, so nRF Connect, Web Bluetooth serial terminals and
Workbench's Bluetooth transport all speak to it. ``RX`` is what the central
writes; ``TX`` is what the peripheral notifies.

``ble`` is a bledev adapter. A raw MicroPython ``bluetooth.BLE`` is wrapped in
:class:`bledev.mpble.MPBLE` for you.
"""

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
    is_adapter,
    sleep_ms,
)

SERVICE = UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
RX = UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
TX = UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")

#: The ATT MTU both sides ask for. 247 fills one data-length-extended link
#: packet (251 bytes), so a notification carries 244 bytes.
MTU = 247

# How long the server's receive loop waits before checking for links whose
# peer has gone, in milliseconds. A closed link reports end-of-stream only
# after every write that arrived before the disconnect has been read.
_POLL_MS = 50

# How long a send waits after the controller reports its buffers full.
_BUSY_WAIT_MS = 2


def _adapter(ble):
    if is_adapter(ble):
        return ble
    if hasattr(ble, "gap_advertise"):
        from .mpble import MPBLE

        return MPBLE(ble)
    raise TypeError("expected a bledev adapter, not {!r}".format(ble))


def _set_mtu(ble, mtu):
    try:
        ble.config(mtu=mtu)
    except UnsupportedError:
        pass


class Link:
    """One end of a NUS byte stream. Made by :func:`serve` or :func:`connect`.

    ``read()`` returns ``b""`` once the link has closed and everything that
    arrived before has been read. ``bytes_in`` and ``bytes_out`` count
    payload bytes.
    """

    def __init__(self, connection):
        self.connection = connection
        self._buf = bytearray()
        self._event = asyncio.Event()
        self._closed = False
        self._error = None
        self.bytes_in = 0
        self.bytes_out = 0

    def __repr__(self):
        return "Link({!r})".format(self.connection)

    @property
    def closed(self):
        """True once the link is down and nothing is left to read."""
        return self._closed and not self._buf

    # -- fed by the receive side

    def _feed(self, data):
        if data:
            self._buf.extend(data)
            self.bytes_in += len(data)
            self._event.set()

    def _finish(self, error=None):
        if error is not None and self._error is None:
            self._error = error
        self._closed = True
        self._event.set()

    async def _wait(self):
        self._event.clear()
        await self._event.wait()

    def _check_error(self):
        if self._error is not None:
            error, self._error = self._error, None
            raise error

    # -- reading

    async def read(self, n=-1):
        """Up to ``n`` bytes (all that's buffered when ``n`` < 0), waiting for at least one."""
        while not self._buf:
            self._check_error()
            if self._closed:
                return b""
            await self._wait()
        if n < 0 or n >= len(self._buf):
            data = bytes(self._buf)
            self._buf = bytearray()
        else:
            data = bytes(self._buf[:n])
            self._buf = self._buf[n:]
        return data

    async def readexactly(self, n):
        """Exactly ``n`` bytes. Raises :class:`DisconnectedError` if the link closes first."""
        while len(self._buf) < n:
            self._check_error()
            if self._closed:
                raise DisconnectedError(
                    "link closed after {} of {} bytes".format(len(self._buf), n)
                )
            await self._wait()
        data = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return data

    async def readline(self):
        """Bytes up to and including ``b"\\n"``; at end of stream, whatever is left."""
        while True:
            i = self._buf.find(b"\n")
            if i >= 0:
                data = bytes(self._buf[: i + 1])
                self._buf = self._buf[i + 1 :]
                return data
            self._check_error()
            if self._closed:
                data = bytes(self._buf)
                self._buf = bytearray()
                return data
            await self._wait()

    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.readline()
        if not line:
            raise StopAsyncIteration
        return line

    # -- writing

    def _payload(self):
        return max(1, self.connection.mtu - 3)

    async def write(self, data):
        """Send all of ``data``, split to the link's MTU. Returns when the stack has it."""
        data = memoryview(bytes(data))
        sent = 0
        while sent < len(data):
            if not self.connection.is_connected():
                raise DisconnectedError("link closed after sending {} of {} bytes".format(sent, len(data)))
            n = min(self._payload(), len(data) - sent)
            await self._send(bytes(data[sent : sent + n]))
            sent += n
            self.bytes_out += n

    async def drain(self):
        """For asyncio-stream compatibility; ``write()`` already waited."""

    async def close(self):
        """Disconnect. Anything already received stays readable."""
        if self.connection.is_connected():
            await self.connection.disconnect()
        self._finish()

    async def _send(self, chunk):
        raise NotImplementedError


class _ServerLink(Link):
    """The peripheral's end: receives writes on RX, notifies on TX."""

    def __init__(self, connection, server):
        Link.__init__(self, connection)
        self._server = server
        self._peer_gone = False
        self._watch = asyncio.create_task(self._watch_disconnect())

    async def _watch_disconnect(self):
        try:
            await self.connection.disconnected()
        finally:
            # The server loop closes the link once the receive queue is empty,
            # so writes that raced the disconnect are still delivered.
            self._peer_gone = True
            self._server.wake()

    async def _send(self, chunk):
        tx = self._server.tx
        while True:
            try:
                tx.notify(self.connection, chunk)
                return
            except BusyError:
                if not self.connection.is_connected():
                    raise DisconnectedError("link closed while sending")
                await sleep_ms(_BUSY_WAIT_MS)


class _Server:
    """The GATT service on one adapter, shared by every link it serves."""

    def __init__(self, ble):
        self.ble = ble
        self.service = Service(SERVICE)
        self.rx = Characteristic(
            self.service, RX, write=True, write_no_response=True, capture=True, max_len=MAX_MTU - 3
        )
        self.tx = Characteristic(self.service, TX, notify=True)
        self.links = []
        self._task = None

    def add(self, link):
        self.links.append(link)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def wake(self):
        pass  # the loop polls; kept so a backend with an event can hook it

    def _link_for(self, connection):
        for link in self.links:
            if link.connection is connection or link.connection == connection:
                return link
        return None

    def _retire_gone(self):
        for link in list(self.links):
            if link._peer_gone:
                self.links.remove(link)
                link._finish()

    async def _run(self):
        try:
            while self.links:
                try:
                    connection, data = await self.rx.written(timeout_ms=_POLL_MS)
                except BLETimeoutError:
                    self._retire_gone()
                    continue
                link = self._link_for(connection)
                if link is not None:
                    link._feed(data)
        except Exception as e:  # a receive queue overrun, most likely
            for link in self.links:
                link._finish(e)
            self.links = []
        finally:
            self._task = None


def _server_for(ble, mtu):
    server = getattr(ble, "_nus_server", None)
    if server is None:
        _set_mtu(ble, mtu)
        server = _Server(ble)
        ble.register_services(server.service)
        ble._nus_server = server
    return server


async def serve(ble, name="bledev", *, timeout_ms=None, interval_us=100000, mtu=MTU):
    """Advertise the Nordic UART service as ``name`` and return a :class:`Link`
    when a central connects.

    Call it again for the next connection; the service is registered once per
    adapter, so don't register other services on the same adapter afterwards.
    """
    ble = _adapter(ble)
    server = _server_for(ble, mtu)
    connection = await ble.advertise(interval_us, name=name, services=[SERVICE], timeout_ms=timeout_ms)
    link = _ServerLink(connection, server)
    server.add(link)
    return link


class _ClientLink(Link):
    """The central's end: writes RX, receives TX notifications."""

    def __init__(self, connection, rx, tx):
        Link.__init__(self, connection)
        self._rx = rx
        self._tx = tx
        self._no_response = bool(rx.properties & 0x0004)
        self._pump = asyncio.create_task(self._receive())

    async def _receive(self):
        error = None
        try:
            while True:
                self._feed(await self._tx.notified())
        except DisconnectedError:
            pass
        except Exception as e:
            error = e
        finally:
            self._finish(error)

    async def _send(self, chunk):
        await self._rx.write(chunk, response=not self._no_response)


async def connect(ble, name=None, *, device=None, timeout_ms=10000, mtu=MTU, **connect_options):
    """Find a NUS peripheral (by ``name``, or the first one advertising the
    service), connect, and return a :class:`Link`.

    Pass ``device`` to skip the scan. ``connect_options`` go to
    ``device.connect()``; on a board, ``min_conn_interval_us`` and
    ``max_conn_interval_us`` trade power for throughput.
    """
    ble = _adapter(ble)
    _set_mtu(ble, mtu)
    if device is None:
        device = await ble.find(name=name, service=SERVICE, timeout_ms=timeout_ms)
    connection = await device.connect(timeout_ms=timeout_ms, **connect_options)
    try:
        try:
            await connection.exchange_mtu(mtu)
        except (UnsupportedError, BLETimeoutError):
            pass
        service = await connection.service(SERVICE)
        if service is None:
            raise BLEError("{!r} has no Nordic UART service".format(device))
        rx = await service.characteristic(RX)
        tx = await service.characteristic(TX)
        if rx is None or tx is None:
            raise BLEError("{!r}: Nordic UART service is missing RX or TX".format(device))
        await tx.subscribe(notify=True)
    except BaseException:
        if connection.is_connected():
            await connection.disconnect()
        raise
    return _ClientLink(connection, rx, tx)
