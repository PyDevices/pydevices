# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""bledev.cpble without a board: a stand-in ``_bleio`` that behaves the way
CircuitPython 10.3's does where it matters, and checks of the parts cpble adds.

The stand-in's ``PacketBuffer`` does what the real one does with a buffer pool
that has run dry: it keeps the packet, appends the next write to it (so two
notifications arrive as one), and a write that doesn't fit beside the kept
packet would wait forever inside ``_bleio``, which here raises instead. The
checks prove notifications leave one per ``notify()`` and never hit that wait,
and a planted fault (cpble's send reverted to a plain ``write(data)``) must
fail them. The same code over the real radio is ``bledev_board/``.
"""

import asyncio
import sys
import types
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

PAYLOAD = 244


class _Stall(Exception):
    """What _bleio would do instead: wait forever for a packet nothing retries."""


def _stub():
    m = types.ModuleType("_bleio")

    class BluetoothError(Exception):
        pass

    class SecurityError(BluetoothError):
        pass

    class UUID:
        def __init__(self, value):
            if isinstance(value, int):
                self.size, self.uuid16, self._raw = 16, value, None
            else:
                raw = bytes.fromhex(value.replace("-", ""))
                self.size, self.uuid16, self._raw = 128, None, raw

        @property
        def uuid128(self):
            return bytes(reversed(self._raw))  # little-endian, as _bleio's

    class Attribute:
        NO_ACCESS, OPEN, ENCRYPT_NO_MITM, ENCRYPT_WITH_MITM = 0, 1, 2, 3

    class Service:
        def __init__(self, uuid):
            self.uuid = uuid
            self.characteristics = []
            # As _bleio's: in the GATT table until the board reloads.
            m.adapter.gatt.append(self)

        def deinit(self):
            pass

    class Characteristic:
        BROADCAST, READ, WRITE_NO_RESPONSE, WRITE, NOTIFY, INDICATE = 1, 2, 4, 8, 16, 32

        def __init__(self):
            self._value = b""
            self.packets = None

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, data):
            # As _bleio does: setting a local value notifies every subscriber.
            self._value = bytes(data)
            if self.packets is not None and self.packets.subscribed:
                self.packets.sent.append(self._value)

        @classmethod
        def add_to_service(cls, service, uuid, *, properties, read_perm, write_perm, max_length, fixed_length, initial_value):
            c = cls()
            c.uuid, c.properties, c.value = uuid, properties, bytes(initial_value)
            service.characteristics.append(c)
            return c

    class Descriptor:
        @staticmethod
        def add_to_characteristic(*args, **kwargs):
            return None

    class PacketBuffer:
        def __init__(self, characteristic, *, buffer_size, max_packet_size=None):
            self.characteristic = characteristic
            characteristic.packets = self
            self.pending = b""
            self.sent = []
            self.incoming = []
            self.subscribed = True
            self.pool = True  # False: NimBLE has no mbufs left

        @property
        def outgoing_packet_length(self):
            # As _bleio does: it raises, rather than returning -1, until the
            # central subscribes.
            if not self.subscribed:
                raise ValueError("No connection: length cannot be determined")
            return PAYLOAD

        def _try(self):
            if self.pending and self.pool:
                self.sent.append(self.pending)
                self.pending = b""

        def write(self, data, *, header=None):
            if not self.subscribed:
                return 0
            data, header = bytes(data), bytes(header or b"")
            if self.pending and len(data) + len(self.pending) > PAYLOAD:
                raise _Stall("PacketBuffer.write would wait forever")
            n = 0
            if not self.pending:
                self.pending += header
                n += len(header)
            self.pending += data
            self._try()
            return n + len(data)

        def readinto(self, buf):
            if not self.incoming:
                return 0
            packet = self.incoming.pop(0)
            buf[: len(packet)] = packet
            return len(packet)

        def deinit(self):
            pass

    class CharacteristicBuffer:
        def __init__(self, characteristic, *, timeout, buffer_size):
            characteristic.stream = self
            self.data = b""
            self.size = buffer_size

        def feed(self, data):
            room = self.size - len(self.data)
            self.data += data[:room]  # a full ring drops the rest, silently

        @property
        def in_waiting(self):
            return len(self.data)

        def read(self, n):
            out, self.data = self.data[:n], self.data[n:]
            return out

        def deinit(self):
            pass

    class Connection:
        connected = True
        max_packet_length = 253
        paired = False

        def disconnect(self):
            self.connected = False

    class Adapter:
        enabled = True
        name = "stub"
        advertising = False

        def __init__(self):
            self.connections = ()
            self.gatt = []

        def start_advertising(self, data, *, scan_response=None, connectable=True, interval=0.1):
            self.advertised = (bytes(data), scan_response)
            self.advertising = True
            self.connections = (Connection(),)  # a central connects at once

        def stop_advertising(self):
            self.advertising = False

        def stop_scan(self):
            pass

    for name, value in list(locals().items()):
        if isinstance(value, type):
            setattr(m, name, value)
    m.adapter = Adapter()
    return m


sys.modules["_bleio"] = _stub()

import bledev  # noqa: E402
import bledev.cpble as cpble  # noqa: E402
import bledev.nus as nus  # noqa: E402

_bleio = sys.modules["_bleio"]


def run(coro):
    return asyncio.run(coro)


async def _serve(queue_limit=64, stream_buffer=32768):
    _bleio.adapter = _bleio.Adapter()
    cpble._shared = None
    ble = cpble.CPBLE(queue_limit=queue_limit, stream_buffer=stream_buffer)
    service = bledev.Service(nus.SERVICE)
    rx = bledev.Characteristic(service, nus.RX, write=True, write_no_response=True, capture=True, max_len=244)
    tx = bledev.Characteristic(service, nus.TX, notify=True)
    stream = bledev.Characteristic(service, "12345678-1234-5678-1234-56789abcdef2",
                                   write_no_response=True, notify=True, capture=True, max_len=100)
    ble.register_services(service)
    connection = await ble.advertise(name="gate", services=[nus.SERVICE])
    return ble, connection, rx, tx, stream


class CPBLEChecks(unittest.TestCase):
    def test_uuids_round_trip(self):
        for uuid in (bledev.UUID(0x180F), nus.SERVICE):
            self.assertEqual(cpble._uuid(cpble._cuuid(uuid)), uuid)

    def test_errors_translate(self):
        e = cpble._translate(_bleio.BluetoothError("Unknown system firmware error: 271"), "read")
        self.assertIsInstance(e, bledev.GattError)
        self.assertEqual(e.status, bledev.INSUFFICIENT_ENCRYPTION)
        self.assertIsInstance(cpble._translate(ConnectionError("Not connected"), "w"), bledev.DisconnectedError)
        self.assertIsInstance(cpble._translate(MemoryError("Nimble out of memory"), "w"), bledev.BusyError)
        self.assertIsInstance(cpble._translate(TimeoutError(), "w"), bledev.BLETimeoutError)

    def test_advertises_what_the_other_backends_do(self):
        async def main():
            ble, connection, *_ = await _serve()
            adv, resp = bledev.pack_advertisement("gate", [nus.SERVICE])
            self.assertEqual(ble.raw.advertised[0], adv)
            self.assertEqual(ble.raw.name, "gate")
            self.assertEqual(connection.role, "peripheral")
            self.assertEqual(connection.mtu, 247)  # capped: one link-layer packet

        run(main())

    def test_notifications_leave_whole_and_never_stall(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve()
            pb = tx._impl._packets
            sent = []
            for i in range(40):
                packet = bytes([i]) * 200
                pb.pool = i % 3 != 1  # the pool runs dry every third packet
                while True:
                    try:
                        tx.notify(connection, packet)
                        break
                    except bledev.BusyError:
                        pb.pool = True  # the radio caught up
                        await asyncio.sleep(0)
                sent.append(packet)
            pb.pool = True
            await asyncio.sleep(0.02)  # the retry loop sends what's left
            return pb.sent, sent

        got, sent = run(main())
        self.assertEqual(got, sent)

    def test_an_unsubscribed_central_gets_nothing(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve()
            tx._impl._packets.subscribed = False
            tx.notify(connection, b"early")
            return tx._impl._packets.sent

        self.assertEqual(run(main()), [])

    def test_a_written_value_goes_out_once(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve()
            # Write, then notify: the portable way, and what every backend
            # must send exactly once.
            for value in (b"one", b"two"):
                tx.write(value)
                tx.notify(connection)
            return tx._impl._packets.sent

        self.assertEqual(run(main()), [b"one", b"two"])

    def test_a_value_written_before_subscribing_still_goes_out(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve()
            tx._impl._packets.subscribed = False
            tx.write(b"early")
            tx._impl._packets.subscribed = True
            tx.notify(connection)
            return tx._impl._packets.sent

        self.assertEqual(run(main()), [b"early"])

    def test_captured_writes_in_order_and_cut_to_max_len(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve()
            stream._impl._packets.incoming = [bytes([i]) * 120 for i in range(5)]
            got = []
            for _ in range(5):
                conn, data = await stream.written(timeout_ms=100)
                self.assertIs(conn, connection)
                got.append(data)
            return got

        self.assertEqual(run(main()), [bytes([i]) * 100 for i in range(5)])

    def test_a_full_stream_buffer_is_an_error(self):
        async def main():
            ble, connection, rx, tx, stream = await _serve(stream_buffer=1024)
            rx._impl._stream.feed(bytes(2000))
            with self.assertRaises(bledev.BLEError):
                await rx.written(timeout_ms=100)

        run(main())


COUNTER = "8e7f0001-6a3c-4b1e-9d2a-5c0e1f2a3b4c"


def _counter_run(extra=False):
    """One run of a counter peripheral, as a script run from the REPL makes
    it: a new CPBLE and new Service objects, over the board's one adapter."""
    ble = cpble.CPBLE()
    service = bledev.Service(COUNTER)
    count = bledev.Characteristic(service, "8e7f0002-6a3c-4b1e-9d2a-5c0e1f2a3b4c",
                                  read=True, notify=True, initial=bytes(4))
    message = bledev.Characteristic(service, "8e7f0003-6a3c-4b1e-9d2a-5c0e1f2a3b4c",
                                    write=True, capture=True, max_len=64)
    if extra:
        bledev.Characteristic(service, "8e7f0004-6a3c-4b1e-9d2a-5c0e1f2a3b4c", read=True)
    ble.register_services(service)
    return ble, count, message


def _copies(uuid):
    return [s for s in _bleio.adapter.gatt if cpble._uuid(s.uuid) == bledev.UUID(uuid)]


class RunTwice(unittest.TestCase):
    """_bleio keeps a service until the board reloads. A peripheral run twice
    from the REPL must serve one copy, and the second run's objects must get
    its traffic."""

    def setUp(self):
        _bleio.adapter = _bleio.Adapter()

    def test_a_second_run_takes_over_the_served_copy(self):
        async def main():
            ble1, count1, message1 = _counter_run()
            native = count1._impl.native
            count1.write(b"\x07\x00\x00\x00")
            ble2, count2, message2 = _counter_run()
            self.assertEqual(len(_copies(COUNTER)), 1, "the service was added twice")
            # The same native characteristic (so the same handle), reset to
            # the second run's initial value.
            self.assertIs(count2._impl.native, native)
            self.assertEqual(count2.read(), bytes(4))
            # Nothing of the first run is bound any more.
            self.assertIsNone(count1._impl)
            self.assertIsNone(message1._impl)
            # A notification from the second run reaches the central.
            connection = await ble2.advertise(name="counter", services=[bledev.UUID(COUNTER)])
            count2.write(b"\x01\x00\x00\x00")
            count2.notify(connection)
            count2.notify(connection, b"\x02\x00\x00\x00")
            self.assertEqual(count2._impl._packets.sent, [b"\x01\x00\x00\x00", b"\x02\x00\x00\x00"])
            # A central's write reaches the second run's message.
            message2._impl.native.stream.feed(b"hello")
            _, data = await message2.written(timeout_ms=100)
            self.assertEqual(data, b"hello")
            with self.assertRaises(bledev.BLEError):
                await message1.written(timeout_ms=100)

        run(main())

    def test_other_characteristics_ask_for_a_reload(self):
        ble1, count1, message1 = _counter_run()
        with self.assertRaises(bledev.BLEError) as caught:
            _counter_run(extra=True)
        self.assertIn("Ctrl-D", str(caught.exception))
        self.assertEqual(len(_copies(COUNTER)), 1)
        # The refused run changed nothing: the first run still serves.
        self.assertIsNotNone(count1._impl)
        self.assertIsNotNone(message1._impl)

    def test_a_reload_serves_afresh(self):
        _counter_run()
        _bleio.adapter = _bleio.Adapter()  # what Ctrl-D leaves: an empty table
        ble, count, message = _counter_run(extra=True)
        self.assertEqual(len(_copies(COUNTER)), 1)


def _circuitpython():
    """A CircuitPython unix binary and a directory holding Adafruit's asyncio
    and adafruit_ticks, or ``(None, why)``. ``PYDEVICES_CIRCUITPYTHON`` and
    ``PYDEVICES_CP_ASYNCIO`` name them; otherwise the workspace layout, where
    ``bin/circuitpython`` and the ``circuitpython`` checkout (whose ``frozen/``
    carries both libraries) sit beside this repository."""
    import os
    from pathlib import Path

    binary = os.environ.get("PYDEVICES_CIRCUITPYTHON")
    libs = os.environ.get("PYDEVICES_CP_ASYNCIO")
    here = Path(__file__).resolve().parent
    for parent in here.parents:
        if binary is None and (parent / "bin" / "circuitpython").is_file():
            binary = str(parent / "bin" / "circuitpython")
        frozen = parent / "circuitpython" / "frozen"
        if libs is None and (frozen / "Adafruit_CircuitPython_asyncio" / "asyncio").is_dir():
            libs = frozen
    if binary is None:
        return None, "no circuitpython binary"
    if libs is None:
        return None, "no Adafruit asyncio library"
    return (binary, libs), None


class OnCircuitPython(unittest.TestCase):
    """bledev's contract and codec checks, run by CircuitPython's own
    interpreter (the unix port, with Adafruit's asyncio). The file-transfer
    server and pairing checks are MicroPython's and aren't run here."""

    def test_contract_and_codecs(self):
        import os
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        found, why = _circuitpython()
        if found is None:
            message = why + ": bledev's checks did NOT run on CircuitPython"
            if os.environ.get("PYDEVICES_REQUIRE_CIRCUITPYTHON") == "1":
                self.fail(message)
            sys.stderr.write("\n*** " + message + " ***\n")
            self.skipTest(message)
        binary, libs = found
        here = Path(__file__).resolve().parent
        if isinstance(libs, Path):  # the checkout's frozen/: gather the two libraries
            scratch = tempfile.TemporaryDirectory()
            self.addCleanup(scratch.cleanup)
            shutil.copytree(str(libs / "Adafruit_CircuitPython_asyncio" / "asyncio"), os.path.join(scratch.name, "asyncio"))
            shutil.copy(str(libs / "Adafruit_CircuitPython_Ticks" / "adafruit_ticks.py"), scratch.name)
            libs = scratch.name
        env = dict(os.environ, MICROPYPATH=str(here.parent / "lib") + ":" + libs)
        for script, tail in (
            ("bledev_contract.py", " 0 failed (circuitpython)"),
            ("bledev_midi_codec.py", " 0 failed"),
            ("bledev_hid_checks.py", " 0 failed (circuitpython)"),
        ):
            with self.subTest(script=script):
                result = subprocess.run([binary, str(here / script)], capture_output=True, text=True, timeout=600, env=env)
                self.assertIn(tail, result.stdout, result.stdout[-2000:] + result.stderr[-2000:])
                self.assertIn("circuitpython", result.stdout)


class Planted(unittest.TestCase):
    """cpble's send reverted to a plain PacketBuffer.write(data): the checks above must fail."""

    def test_plain_write_fails_the_checks(self):
        original = cpble._CPServerCharacteristic._send

        def plain(self, connection, data, what):
            try:
                self._packets.outgoing_packet_length
            except ValueError:
                return
            self._packets.write(data)

        cpble._CPServerCharacteristic._send = plain
        try:
            checks = CPBLEChecks("test_notifications_leave_whole_and_never_stall")
            result = unittest.TestResult()
            checks.run(result)
            self.assertFalse(result.wasSuccessful(), "the planted plain write went unnoticed")
        finally:
            cpble._CPServerCharacteristic._send = original


class PlantedCopy(unittest.TestCase):
    """cpble forgetting what it served, so each run adds another copy: the
    run-twice check must fail."""

    def test_a_forgetful_register_fails_the_check(self):
        original = cpble.CPBLE.register_services

        def forgetful(self, *services):
            cpble._served = {}
            return original(self, *services)

        cpble.CPBLE.register_services = forgetful
        try:
            checks = RunTwice("test_a_second_run_takes_over_the_served_copy")
            result = unittest.TestResult()
            checks.run(result)
            self.assertFalse(result.wasSuccessful(), "a second copy of the service went unnoticed")
        finally:
            cpble.CPBLE.register_services = original


if __name__ == "__main__":
    unittest.main()
