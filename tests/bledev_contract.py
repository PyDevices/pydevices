# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The bledev contract, checked against ``bledev.fake``.

A plain script, not unittest, so the same file runs on CPython and on
MicroPython (which has no unittest)::

    python tests/bledev_contract.py
    micropython tests/bledev_contract.py
    python tests/bledev_contract.py --plant=corrupt   # must FAIL

It prints one PASS/FAIL line per check and exits non-zero on any failure.
``tests/test_bledev.py`` runs it both ways, and runs every plant to prove the
checks can fail: a plant breaks the fake the way a real backend could, and a
contract that still passes under it isn't checking anything.

A new backend can reuse these checks: most take two adapters and don't care
which backend they are (see ``docs/bledev.md``).
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir + _sep + ".." + _sep + "lib")

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import bledev
from bledev import (
    BLEError,
    BLETimeoutError,
    BusyError,
    Characteristic,
    DisconnectedError,
    GattError,
    Service,
    UnsupportedError,
    UUID,
)
from bledev import fake, improv, nus, repl
from bledev.fake import Air, FakeBLE

MICROPYTHON = sys.implementation.name == "micropython"

#: A check that hangs (a lost notification, say) fails after this long.
CHECK_TIMEOUT_S = 5

SVC = UUID("12345678-1234-5678-1234-56789abcdef0")
CHR_RW = UUID("12345678-1234-5678-1234-56789abcdef1")
CHR_STREAM = UUID("12345678-1234-5678-1234-56789abcdef2")
CHR_IND = UUID("12345678-1234-5678-1234-56789abcdef3")

TESTS = []


def check(fn):
    TESTS.append(fn)
    return fn


class Failed(Exception):
    pass


def expect(cond, message="expectation failed"):
    if not cond:
        raise Failed(message)


def equal(a, b, what="value"):
    if a != b:
        raise Failed("{}: {} != {}".format(what, _short(a), _short(b)))


def _short(value):
    text = repr(value)
    return text if len(text) <= 100 else text[:97] + "..."


async def raises(exc_type, awaitable):
    try:
        await awaitable
    except exc_type as e:
        return e
    raise Failed("expected {}".format(exc_type.__name__))


def raises_sync(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as e:
        return e
    raise Failed("expected {}".format(exc_type.__name__))


def pattern(n, seed=0):
    """Bytes nobody gets right by accident: position-dependent, not periodic at 256."""
    return bytes(((i * 7 + (i >> 8) * 13 + seed) & 0xFF) for i in range(n))


def gatt(initial=b"hi"):
    service = Service(SVC)
    rw = Characteristic(service, CHR_RW, read=True, write=True, initial=initial)
    stream = Characteristic(
        service, CHR_STREAM, write_no_response=True, notify=True, capture=True, max_len=100
    )
    ind = Characteristic(service, CHR_IND, indicate=True, read=True)
    return service, rw, stream, ind


async def pair(air, *, board_mtu=23, central_mtu=23, services=None, name="board", **fake_options):
    """A peripheral with the test service, and a central connected to it."""
    board = FakeBLE(air=air, mtu=board_mtu, **fake_options)
    laptop = FakeBLE(air=air, peripheral=False, mtu=central_mtu, **fake_options)
    parts = gatt()
    board.register_services(parts[0])
    adv = asyncio.create_task(board.advertise(name=name, services=services or [SVC], timeout_ms=2000))
    device = await laptop.find(name=name, timeout_ms=2000)
    central = await device.connect(timeout_ms=2000)
    peripheral = await adv
    return board, laptop, central, peripheral, parts


async def client_chars(central):
    service = await central.service(SVC)
    expect(service is not None, "service not found")
    return (
        await service.characteristic(CHR_RW),
        await service.characteristic(CHR_STREAM),
        await service.characteristic(CHR_IND),
    )


# ---------------------------------------------------------------- values


@check
async def uuid_forms_agree(air):
    short = UUID(0x180F)
    for other in ("180f", "0x180F", "0000180f-0000-1000-8000-00805f9b34fb", b"\x0f\x18", UUID(0x180F)):
        equal(UUID(other), short, "UUID({!r})".format(other))
    equal(short.short, 0x180F, "short")
    equal(str(short), "0000180f-0000-1000-8000-00805f9b34fb", "str")
    equal(short.to_bytes(), b"\x0f\x18", "to_bytes")
    long = UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    equal(str(long), "6e400001-b5a3-f393-e0a9-e50e24dcca9e", "str(long)")
    equal(long.short, None, "long.short")
    equal(UUID(long.to_bytes()), long, "wire round trip")
    equal(long.to_bytes()[0], 0x9E, "little-endian wire order")
    expect(hash(UUID("180f")) == hash(short), "hash follows equality")
    expect(short != long and not (short == long), "different UUIDs differ")
    expect(short in [long, UUID(0x180F)], "list membership")
    expect({short: 1}.get(UUID("0x180f")) == 1, "dict key")
    raises_sync(ValueError, UUID, "not-a-uuid")
    raises_sync(ValueError, UUID, b"\x00\x01\x02")


@check
async def errors_share_a_base(air):
    for exc in (UnsupportedError, DisconnectedError, BLETimeoutError, BusyError, GattError):
        expect(issubclass(exc, BLEError), exc.__name__)
    equal(GattError(0x0A).status, 0x0A, "GattError.status")


@check
async def advertisement_packing(air):
    adv, resp = bledev.pack_advertisement("rack", [nus.SERVICE])
    expect(len(adv) <= 31 and not resp, "short name fits in the advertisement")
    name, services, _, _ = bledev.decode_advertisement(adv)
    equal(name, "rack", "name")
    equal(services, [nus.SERVICE], "services")
    adv, resp = bledev.pack_advertisement("a-rather-long-board-name", [nus.SERVICE])
    equal(bledev.decode_advertisement(adv)[0], None, "long name left the advertisement")
    equal(bledev.decode_advertisement(adv, resp)[0], "a-rather-long-board-name", "and went to the scan response")
    adv, resp = bledev.pack_advertisement(None, [0x180F], appearance=0x03C1, manufacturer=(0xFFFF, b"\x01\x02"))
    _, services, appearance, manufacturer = bledev.decode_advertisement(adv, resp)
    equal(services, [UUID(0x180F)], "16-bit service")
    equal(appearance, 0x03C1, "appearance")
    equal(manufacturer, [(0xFFFF, b"\x01\x02")], "manufacturer")
    raises_sync(ValueError, bledev.pack_advertisement, "x" * 40, [nus.SERVICE])
    # Improv's layout: a 128-bit service and 16-bit service data fill the
    # advertisement to exactly 31 bytes, and the name goes to the response.
    adv, resp = bledev.pack_advertisement("imp", [nus.SERVICE], service_data=[(0x4677, b"\x02\x01\0\0\0\0")])
    equal(len(adv), 31, "a full 31-byte advertisement")
    equal(bledev.decode_service_data(adv), [(UUID(0x4677), b"\x02\x01\0\0\0\0")], "service data")
    equal(bledev.decode_advertisement(resp)[0], "imp", "the name overflowed to the response")


@check
async def scan_reports_service_data(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    adv = asyncio.create_task(board.advertise(name="imp", services=[SVC], service_data=[(0x4677, b"\x01")]))
    await asyncio.sleep(0)
    async with laptop.scan(100, active=False) as scanner:
        async for result in scanner:
            equal(result.service_data(0x4677), [(UUID(0x4677), b"\x01")], "service_data()")
            equal(result.service_data(0x180F), [], "service_data(other)")
            break
    adv.cancel()


# ---------------------------------------------------------------- roles


@check
async def capabilities_report_roles(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    for ble in (board, laptop):
        caps = ble.capabilities()
        for key in ("backend", "central", "peripheral", "mtu", "max_mtu", "indicate", "pairing", "l2cap"):
            expect(key in caps, "capabilities lacks " + key)
        equal(caps["backend"], "fake", "backend")
    expect(board.capabilities()["peripheral"], "board can be a peripheral")
    expect(not laptop.capabilities()["peripheral"], "laptop cannot")
    expect(laptop.capabilities()["central"], "laptop can be central")


@check
async def central_only_cannot_advertise(air):
    laptop = FakeBLE(air=air, peripheral=False)
    await raises(UnsupportedError, laptop.advertise(name="x", timeout_ms=10))
    raises_sync(UnsupportedError, laptop.register_services, Service(SVC))
    await raises(UnsupportedError, nus.serve(laptop, name="x", timeout_ms=10))
    board = FakeBLE(air=air, central=False)
    raises_sync(UnsupportedError, board.scan, 10)


@check
async def config_mtu(air):
    ble = FakeBLE(air=air)
    ble.config(mtu=185)
    equal(ble.config("mtu"), 185, "config('mtu')")
    raises_sync(UnsupportedError, ble.config, flux=1)


# ---------------------------------------------------------------- discovery


@check
async def find_by_name_and_service(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    adv = asyncio.create_task(board.advertise(name="rack", services=[SVC], timeout_ms=1000))
    device = await laptop.find(name="rack", timeout_ms=1000)
    equal(device.name, "rack", "device.name")
    expect(isinstance(device.address, str), "address is a string")
    device2 = await laptop.find(service=SVC, timeout_ms=1000)
    equal(device2, device, "same device by service")
    adv.cancel()


@check
async def scan_yields_results(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    adv = asyncio.create_task(board.advertise(name="rack", services=[SVC], manufacturer=(0x1234, b"z")))
    await asyncio.sleep(0)
    seen = []
    async with laptop.scan(100, active=True) as scanner:  # manufacturer data overflows to the scan response
        async for result in scanner:
            seen.append(result)
            break
    expect(seen, "scan found nothing")
    result = seen[0]
    equal(result.name(), "rack", "name()")
    expect(SVC in result.services(), "services()")
    equal(result.manufacturer(0x1234), [(0x1234, b"z")], "manufacturer()")
    expect(result.rssi is not None, "rssi")
    adv.cancel()


@check
async def passive_scan_misses_a_long_name(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    adv = asyncio.create_task(board.advertise(name="a-rather-long-board-name", services=[SVC]))
    await raises(BLETimeoutError, laptop.find(name="a-rather-long-board-name", timeout_ms=60, active=False))
    device = await laptop.find(name="a-rather-long-board-name", timeout_ms=200, active=True)
    expect(device is not None, "active scan finds it")
    adv.cancel()


@check
async def timeouts_raise(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    await raises(BLETimeoutError, board.advertise(name="lonely", timeout_ms=30))
    await raises(BLETimeoutError, laptop.find(name="nobody", timeout_ms=30))
    ghost = bledev.Device(laptop, "fa:ce:ff:ff:ff:ff")
    await raises(BLETimeoutError, ghost.connect(timeout_ms=30))


@check
async def connect_and_discover(air):
    board, laptop, central, peripheral, parts = await pair(air)
    equal(central.role, "central", "central.role")
    equal(peripheral.role, "peripheral", "peripheral.role")
    expect(central.is_connected() and peripheral.is_connected(), "both connected")
    equal(central.mtu, 23, "default mtu")
    names = []
    async for service in central.services():
        names.append(service.uuid)
    equal(names, [SVC], "services()")
    equal(await central.service(UUID(0x180F)), None, "missing service is None")
    service = await central.service(SVC)
    chars = []
    async for c in service.characteristics():
        chars.append(c.uuid)
    equal(chars, [CHR_RW, CHR_STREAM, CHR_IND], "characteristics()")
    rw = await service.characteristic(CHR_RW)
    expect(rw.properties & bledev.FLAG_READ and rw.properties & bledev.FLAG_WRITE, "properties")
    equal(await service.characteristic(UUID(0x2A19)), None, "missing characteristic is None")


# ---------------------------------------------------------------- GATT


@check
async def read_and_write(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    equal(await crw.read(), b"hi", "initial value")
    rw.write(b"local")
    equal(await crw.read(), b"local", "after local write")
    waiter = asyncio.create_task(rw.written(timeout_ms=1000))
    await crw.write(b"remote", response=True)
    writer = await waiter
    expect(writer is peripheral, "written() returns the writer's connection")
    equal(rw.read(), b"remote", "server sees the write")
    await raises(UnsupportedError, crw.write(b"x", response=False))
    await raises(UnsupportedError, cstream.read())


@check
async def capture_keeps_every_write_in_order(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    sent = [pattern(20, seed=i) for i in range(60)]
    for chunk in sent:
        await cstream.write(chunk)
    got = []
    for _ in sent:
        connection, data = await stream.written(timeout_ms=500)
        expect(connection is peripheral, "capture reports the connection")
        got.append(data)
    equal(got, sent, "captured writes")
    await raises(BLETimeoutError, stream.written(timeout_ms=0))


@check
async def notifications_need_a_subscription(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    stream.notify(peripheral, b"early")
    await raises(BLETimeoutError, cstream.notified(timeout_ms=30))
    await cstream.subscribe(notify=True)
    stream.notify(peripheral, b"late")
    equal(await cstream.notified(timeout_ms=500), b"late", "after subscribe")


@check
async def notifications_arrive_in_order(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    sent = [pattern(20, seed=i) for i in range(300)]

    async def send():
        for chunk in sent:
            while True:
                try:
                    stream.notify(peripheral, chunk)
                    break
                except BusyError:
                    await asyncio.sleep(0)

    sender = asyncio.create_task(send())
    got = []
    for _ in sent:
        got.append(await cstream.notified(timeout_ms=1000))
    await sender
    equal(len(got), len(sent), "count")
    equal(got, sent, "notifications")


@check
async def a_burst_reports_busy(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air, notify_buffers=4)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    for i in range(4):
        stream.notify(peripheral, bytes((i,)))
    raises_sync(BusyError, stream.notify, peripheral, b"x")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stream.notify(peripheral, b"room again")


@check
async def mtu_bounds_every_packet(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air, board_mtu=185, central_mtu=247)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    raises_sync(BLEError, stream.notify, peripheral, bytes(21))
    await raises(BLEError, cstream.write(bytes(21)))
    agreed = await central.exchange_mtu()
    equal(agreed, 185, "the smaller MTU wins")
    equal(central.mtu, 185, "central.mtu")
    equal(peripheral.mtu, 185, "peripheral.mtu follows")
    await cstream.write(bytes(100))
    await raises(BLEError, cstream.write(bytes(101)))  # max_len=100
    stream.notify(peripheral, bytes(182))
    equal(len(await cstream.notified(timeout_ms=500)), 182, "a full-MTU notification")


@check
async def indications(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    await cind.subscribe(notify=False, indicate=True)
    await ind.indicate(peripheral, b"ack me")
    equal(await cind.indicated(timeout_ms=500), b"ack me", "indicated()")
    raises_sync(UnsupportedError, ind.notify, peripheral, b"x")


@check
async def overrun_is_loud(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air, queue_limit=10)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    for i in range(30):
        while True:
            try:
                stream.notify(peripheral, bytes((i,)))
                break
            except BusyError:
                await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await raises(BLEError, cstream.notified(timeout_ms=100))


# ---------------------------------------------------------------- lifecycle


@check
async def disconnect_reaches_both_sides(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    waiting = asyncio.create_task(cstream.notified())
    await asyncio.sleep(0)
    await peripheral.disconnect()
    await central.disconnected(timeout_ms=500)
    expect(not central.is_connected() and not peripheral.is_connected(), "both down")
    await raises(DisconnectedError, waiting)
    await raises(DisconnectedError, crw.read())
    await raises(DisconnectedError, crw.write(b"x"))
    raises_sync(DisconnectedError, stream.notify, peripheral, b"x")


@check
async def data_sent_before_a_disconnect_is_kept(air):
    board, laptop, central, peripheral, (svc, rw, stream, ind) = await pair(air)
    crw, cstream, cind = await client_chars(central)
    await cstream.subscribe()
    stream.notify(peripheral, b"last words")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await central.disconnect()
    equal(await cstream.notified(timeout_ms=100), b"last words", "queued before the drop")
    await raises(DisconnectedError, cstream.notified(timeout_ms=100))


@check
async def async_with_disconnects(air):
    board, laptop, central, peripheral, parts = await pair(air)
    async with central:
        expect(central.is_connected(), "inside")
    expect(not central.is_connected(), "after")
    await peripheral.disconnected(timeout_ms=100)


@check
async def advertise_again_after_a_connection(air):
    board, laptop, central, peripheral, parts = await pair(air)
    adv = asyncio.create_task(board.advertise(name="board", timeout_ms=1000))
    device = await laptop.find(name="board", timeout_ms=1000)
    second = await device.connect(timeout_ms=1000)
    other = await adv
    expect(other is not peripheral, "a new connection")
    expect(central.is_connected() and second.is_connected(), "both links up")


@check
async def close_drops_everything(air):
    board, laptop, central, peripheral, parts = await pair(air)
    board.close()
    expect(not central.is_connected(), "closed")


# ---------------------------------------------------------------- nus


async def nus_pair(air, *, name="rack", mtu=nus.MTU, **options):
    board = FakeBLE(air=air, **options)
    laptop = FakeBLE(air=air, peripheral=False, **options)
    served = asyncio.create_task(nus.serve(board, name=name, mtu=mtu, timeout_ms=2000))
    client = await nus.connect(laptop, name=name, mtu=mtu, timeout_ms=2000)
    server = await served
    return board, laptop, server, client


@check
async def nus_round_trip(air):
    board, laptop, server, client = await nus_pair(air)
    equal(client.connection.mtu, nus.MTU, "negotiated MTU")
    await client.write(b"ping\n")
    equal(await server.readline(), b"ping\n", "central -> peripheral")
    await server.write(b"pong\n")
    equal(await client.readline(), b"pong\n", "peripheral -> central")


@check
async def nus_bulk_both_ways(air):
    board, laptop, server, client = await nus_pair(air)
    down = pattern(10240, seed=1)
    up = pattern(10240, seed=2)
    sender = asyncio.create_task(server.write(down))
    got = await client.readexactly(len(down))
    await sender
    equal(len(got), len(down), "downstream length")
    expect(got == down, "downstream bytes differ")
    sender = asyncio.create_task(client.write(up))
    got = await server.readexactly(len(up))
    await sender
    expect(got == up, "upstream bytes differ")
    equal(server.bytes_in, len(up), "bytes_in")
    equal(server.bytes_out, len(down), "bytes_out")


@check
async def nus_small_mtu_still_intact(air):
    board, laptop, server, client = await nus_pair(air, mtu=23)
    equal(client.connection.mtu, 23, "mtu")
    data = pattern(2000, seed=3)
    sender = asyncio.create_task(client.write(data))
    expect(await server.readexactly(len(data)) == data, "bytes differ")
    await sender


@check
async def nus_lines_and_end_of_stream(air):
    board, laptop, server, client = await nus_pair(air)
    await client.write(b"one\ntwo\nthree")
    await asyncio.sleep(0)
    await client.close()
    lines = []
    async for line in server:
        lines.append(line)
    equal(lines, [b"one\n", b"two\n", b"three"], "lines, then the unterminated tail")
    equal(await server.read(), b"", "end of stream")
    expect(server.closed, "server.closed")
    await raises(DisconnectedError, client.write(b"x"))


@check
async def nus_serves_two_links(air):
    board = FakeBLE(air=air)
    a = FakeBLE(air=air, peripheral=False)
    b = FakeBLE(air=air, peripheral=False)
    served = asyncio.create_task(nus.serve(board, name="hub", timeout_ms=2000))
    link_a = await nus.connect(a, name="hub", timeout_ms=2000)
    server_a = await served
    served = asyncio.create_task(nus.serve(board, name="hub", timeout_ms=2000))
    link_b = await nus.connect(b, name="hub", timeout_ms=2000)
    server_b = await served
    await link_a.write(b"from a\n")
    await link_b.write(b"from b\n")
    equal(await server_b.readline(), b"from b\n", "b's bytes go to b's link")
    equal(await server_a.readline(), b"from a\n", "a's bytes go to a's link")


@check
async def nus_readexactly_short_stream(air):
    board, laptop, server, client = await nus_pair(air)
    await server.write(b"abc")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await server.close()
    await raises(DisconnectedError, client.readexactly(10))


# ---------------------------------------------------------------- repl login


@check
async def repl_login_right_password(air):
    login = repl.Login("hunter22")
    reply, verdict, rest = login.feed(b"\r")
    equal((reply, verdict), (repl.PROMPT, None), "an empty line asks for the prompt")
    login.feed(b"hunt")
    reply, verdict, rest = login.feed(b"er22\r\n1 + 1\r")
    equal((reply, verdict, rest), (repl.BANNER, True, b"1 + 1\r"), "split password, then code")


@check
async def repl_login_wrong_password(air):
    login = repl.Login("hunter22")
    reply, verdict, rest = login.feed(b"hunter2\rimport os; os.remove('main.py')\r")
    equal((reply, verdict, rest), (repl.DENIED, False, b""), "refused, and the code after it dropped")
    equal(login.feed(b"hunter22\r"), (b"", False, b""), "no second attempt")
    equal(repl.Login("hunter22").feed(b"x" * 100)[1], False, "an overlong line is refused")
    expect(not repl._check_password(b"hunter2", b"hunter22"), "prefix")
    expect(not repl._check_password(b"hunter222", b"hunter22"), "longer")
    expect(repl._check_password(b"hunter22", b"hunter22"), "equal")


# ---------------------------------------------------------------- improv


SSID = "a-network-name-that-is-32-bytes!"
PASSWORD = "a-password-long-enough-to-cross-several-23-byte-mtu-packets-63"


async def improv_pair(air, **server_options):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    joined = []

    async def join(ssid, password):
        joined.append((ssid, password))
        await asyncio.sleep(0)
        return "10.0.0.5" if (ssid, password) == (SSID, PASSWORD) else None

    server = improv.Server(board, "imp", join=join, **server_options)
    task = asyncio.create_task(server.serve(timeout_ms=3000))
    return board, laptop, server, task, joined


@check
async def improv_packets(air):
    packet = improv.pack(improv.CMD_WIFI_SETTINGS, "ab", "cd")
    equal(packet[:-1], b"\x01\x06\x02ab\x02cd", "layout")
    equal(packet[-1], sum(packet[:-1]) & 0xFF, "checksum")
    equal(improv.unpack(packet), (1, [b"ab", b"cd"]), "unpack")
    bad = packet[:-1] + bytes(((packet[-1] + 1) & 0xFF,))
    e = raises_sync(improv.ImprovError, improv.unpack, bad)
    equal(e.code, improv.ERROR_INVALID_RPC, "bad checksum code")


@check
async def improv_advertises_its_state(air):
    board, laptop, server, task, joined = await improv_pair(air)
    async with laptop.scan(200, active=False) as scanner:
        async for result in scanner:
            expect(improv.SERVICE in result.services(), "service UUID in the advertisement")
            equal(result.service_data(improv.SERVICE_DATA),
                  [(improv.SERVICE_DATA, bytes((improv.STATE_AUTHORIZED, server.capabilities, 0, 0, 0, 0)))],
                  "state and capabilities in the service data")
            break
    task.cancel()


@check
async def improv_provisions(air):
    board, laptop, server, task, joined = await improv_pair(air)
    client = await improv.Client.connect(laptop, "imp", timeout_ms=2000)
    equal(client.connection.mtu, 23, "a small MTU, so the RPC crosses several writes")
    info = await client.device_info(timeout_ms=2000)
    equal(len(info), 4, "device info has four strings")
    equal(info[3], "imp", "device name")
    url = await client.send_wifi(SSID, PASSWORD, timeout_ms=2000)
    equal(url, "http://10.0.0.5/", "redirect URL")
    equal(joined, [(SSID, PASSWORD)], "the device got the credentials intact")
    equal(await client.state(), improv.STATE_PROVISIONED, "state")
    await client.close()
    equal(await wait_task(task), "http://10.0.0.5/", "serve() returns the URL")


async def wait_task(task):
    return await asyncio.wait_for(task, 3)


@check
async def improv_wrong_network(air):
    board, laptop, server, task, joined = await improv_pair(air)
    client = await improv.Client.connect(laptop, "imp", timeout_ms=2000)
    e = await raises(improv.ImprovError, client.send_wifi("nope", "wrong", timeout_ms=2000))
    equal(e.code, improv.ERROR_UNABLE_TO_CONNECT, "error code")
    equal(await client.error(), improv.ERROR_UNABLE_TO_CONNECT, "the error characteristic")
    equal(await client.state(), improv.STATE_AUTHORIZED, "back to authorized")
    url = await client.send_wifi(SSID, PASSWORD, timeout_ms=2000)
    equal(url, "http://10.0.0.5/", "a second, right attempt works")
    await client.close()
    task.cancel()


@check
async def improv_needs_authorization(air):
    board, laptop, server, task, joined = await improv_pair(air, require_authorization=True)
    client = await improv.Client.connect(laptop, "imp", timeout_ms=2000)
    equal(await client.state(), improv.STATE_AUTHORIZATION_REQUIRED, "starts locked")
    e = await raises(improv.ImprovError, client.send_wifi(SSID, PASSWORD, timeout_ms=100))
    equal(e.code, improv.ERROR_NOT_AUTHORIZED, "not authorized in time")
    equal(joined, [], "nothing was joined")

    async def press():
        await asyncio.sleep(0.05)
        server.authorize()

    asyncio.create_task(press())
    equal(await client.send_wifi(SSID, PASSWORD, timeout_ms=2000), "http://10.0.0.5/", "after a button press")
    await client.close()
    task.cancel()


@check
async def improv_rejects_a_bad_packet(air):
    board, laptop, server, task, joined = await improv_pair(air)
    client = await improv.Client.connect(laptop, "imp", timeout_ms=2000)
    await client._command(b"\x01\x00\x00")  # checksum should be 0x01
    for _ in range(20):
        await asyncio.sleep(0)
    equal(await client.error(), improv.ERROR_INVALID_RPC, "invalid RPC")
    await client._command(improv.pack(0x7E))
    for _ in range(20):
        await asyncio.sleep(0)
    equal(await client.error(), improv.ERROR_UNKNOWN_RPC, "unknown RPC")
    await client.close()
    task.cancel()


@check
async def improv_scan(air):
    nets = [("one", -40, True), ("two", -70, False)]
    board, laptop, server, task, joined = await improv_pair(air, scan=lambda: nets)
    client = await improv.Client.connect(laptop, "imp", timeout_ms=2000)
    expect(client.capabilities & improv.CAP_WIFI_SCAN, "scan capability")
    equal(await client.scan(timeout_ms=2000), nets, "scan results")
    await client.close()
    task.cancel()


# ---------------------------------------------------------------- auto


@check
async def setup_retries_a_link_that_drops(air):
    # Windows sometimes reports a connection the peripheral never saw; the
    # first GATT operation then fails. connect_and_set_up tries again.
    board, laptop = _two(air)
    attempts = []

    async def setup(connection):
        attempts.append(connection)
        if len(attempts) == 1:
            raise bledev.DisconnectedError("the first link came up dead")
        return "ready"

    served = asyncio.create_task(_serve_twice(board))
    connection, result = await bledev.connect_and_set_up(laptop, setup, name="board", timeout_ms=2000)
    equal(result, "ready", "setup's result")
    equal(len(attempts), 2, "attempts")
    expect(not attempts[0].is_connected(), "the dead link was closed")
    expect(connection.is_connected(), "the second link is up")
    served.cancel()


def _two(air):
    board = FakeBLE(air=air)
    laptop = FakeBLE(air=air, peripheral=False)
    board.register_services(gatt()[0])
    return board, laptop


async def _serve_twice(board):
    for _ in range(2):
        await board.advertise(name="board", timeout_ms=2000)


@check
async def setup_gives_up_after_its_attempts(air):
    board, laptop = _two(air)
    served = asyncio.create_task(_serve_twice(board))

    async def setup(connection):
        await asyncio.sleep(10)

    await raises(
        BLETimeoutError,
        bledev.connect_and_set_up(laptop, setup, name="board", timeout_ms=2000, attempts=2, setup_timeout_ms=100),
    )
    served.cancel()


@check
async def auto_picks_or_explains(air):
    import bledev.auto as auto

    name = auto.backend_name()
    expect(name in (None, "mpble", "bleak", "webble", "fake"), "backend_name: {!r}".format(name))
    ble = auto.adapter(backend="fake", air=air)
    equal(ble.backend, "fake", "forced backend")
    if name is None:
        await raises(UnsupportedError, _call(auto.adapter))


async def _call(fn, *args, **kwargs):
    return fn(*args, **kwargs)


# ---------------------------------------------------------------- plants


def _plant(name):
    """Break the fake on purpose. Each plant must make at least one check fail."""
    if name == "drop":
        put = fake._Inbox.put
        count = [0]

        def dropping_put(self, item):
            count[0] += 1
            if count[0] % 97 == 0:
                return  # silently lost, the way aioble's one-slot queue loses data
            put(self, item)

        fake._Inbox.put = dropping_put
    elif name == "corrupt":
        feed = nus.Link._feed

        def corrupting_feed(self, data):
            if len(data) > 8:
                data = bytearray(data)
                data[5] ^= 0x01
            feed(self, data)

        nus.Link._feed = corrupting_feed
    elif name == "reorder":
        drain = fake._Link._drain

        async def reordering_drain(self):
            if len(self.in_flight) > 1:
                self.in_flight[0], self.in_flight[1] = self.in_flight[1], self.in_flight[0]
            await drain(self)

        fake._Link._drain = reordering_drain
    elif name == "truncate":
        check_size = fake._ServerCharacteristic._check_size

        def lax(self, connection, data):
            pass  # what NimBLE does: no error, the tail is cut on the air

        fake._ServerCharacteristic._check_size = lax
    elif name == "overwrite":
        # aioble's client queue holds one notification; a second replaces it.
        def one_slot(self, item):
            self.items[:] = [item]
            self.event.set()

        fake._Inbox.put = one_slot
    else:
        raise SystemExit("unknown plant " + name)


PLANTS = ("drop", "corrupt", "reorder", "truncate", "overwrite")


def _print_exception(e):
    if MICROPYTHON:
        sys.print_exception(e)
    else:
        import traceback

        traceback.print_exception(type(e), e, e.__traceback__)


def run(only=None, verbose=False):
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        if MICROPYTHON:
            asyncio.new_event_loop()
        try:
            asyncio.run(asyncio.wait_for(fn(Air()), CHECK_TIMEOUT_S))
        except Exception as e:
            failed += 1
            print("FAIL", fn.__name__, "-", type(e).__name__, e)
            if verbose:
                _print_exception(e)
        else:
            print("PASS", fn.__name__)
    print("{} checks, {} failed ({})".format(len(TESTS) if not only else len(only), failed, sys.implementation.name))
    return failed


def main(argv):
    only = []
    verbose = False
    for arg in argv:
        if arg.startswith("--plant="):
            _plant(arg.split("=", 1)[1])
            print("PLANTED", arg.split("=", 1)[1])
        elif arg in ("-v", "--verbose"):
            verbose = True
        else:
            only.append(arg)
    sys.exit(1 if run(only, verbose) else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
