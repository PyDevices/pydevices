# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``bledev.hid`` end to end over ``bledev.fake``: a peripheral types, a host decodes.

A plain script, like ``bledev_contract.py``, so it runs on CPython and
MicroPython::

    python tests/bledev_hid_checks.py
    micropython tests/bledev_hid_checks.py
    python tests/bledev_hid_checks.py --plant=drop_report   # must FAIL

The scripted input and its expected events are ``bledev_board/hid_script.py``,
the same file the board-to-board gate uses.
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
sys.path.insert(0, _dir + _sep + ".." + _sep + "lib")
sys.path.insert(0, _dir + _sep + "bledev_board")
# --adafruit=DIR: adafruit_hid as bledev_hid's package file installs it, and
# shims a desktop interpreter needs, appended so a real module wins.
for _a in sys.argv[1:]:
    if _a.startswith("--adafruit="):
        sys.path.insert(0, _a[len("--adafruit="):])
        sys.path.append(_a[len("--adafruit="):] + _sep + "shims")

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import bledev
from bledev import BLEError, GattError, INSUFFICIENT_ENCRYPTION, fake, hid, hidreport
from bledev.fake import Air, FakeBLE
from bledev.hidreport import INPUT, OUTPUT, ReportMap
import hid_script

MICROPYTHON = sys.implementation.name == "micropython"
CHECK_TIMEOUT_S = 10


class Failed(Exception):
    pass


def equal(got, want, what):
    if got != want:
        raise Failed("{}: got {!r}, want {!r}".format(what, got, want))


async def _pair_up(air, *, encrypted=False, central_kw=None, peripheral_kw=None, **pkw):
    # adafruit_hid sends synchronously, and the fake frees a notification
    # buffer only when the event loop turns (a controller frees them in its
    # own task), so the board gets room for a whole script.
    peripheral_kw = dict(peripheral_kw or {})
    peripheral_kw.setdefault("notify_buffers", 512)
    board = FakeBLE(air=air, mtu=247, **peripheral_kw)
    host_ble = FakeBLE(air=air, mtu=247, **(central_kw or {}))
    per = hid.Peripheral(board, encrypted=encrypted, **pkw)
    serving = asyncio.create_task(per.serve())
    host = await hid.connect(host_ble, name=per.name, timeout_ms=2000)
    await serving
    return board, host_ble, per, host


async def _collect(host, n, timeout_ms=3000):
    got = []
    while len(got) < n:
        got += await host.events(timeout_ms)
    return got


async def c_served_map_parses(air):
    # Our own map, by hand: CircuitPython's keyboard (8 bytes in, 1 out),
    # mouse (4) and consumer control (2), then the gamepad when asked for (7).
    m = ReportMap(hid.report_map())
    equal(m.applications, [0x00010006, 0x00010002, 0x000C0001], "applications")
    equal([(r.report_id, r.size) for r in m.inputs()], [(1, 8), (2, 4), (3, 2)], "input reports")
    equal(m.report(OUTPUT, 1).size, 1, "LED report")
    m = ReportMap(hid.report_map(gamepad=True))
    equal([(r.report_id, r.size) for r in m.inputs()], [(1, 8), (2, 4), (3, 2), (4, 7)], "with the gamepad")
    equal(hid.identity(), ("PyDevices Keyboard+Mouse", 0x03C0, 11), "identity, the default three")
    equal(hid.identity(True, False, False, False), ("PyDevices Keyboard", 0x03C1, 1), "identity, keyboard")
    equal(hid.identity(False, True, False, False), ("PyDevices Mouse", 0x03C2, 8), "identity, mouse")
    equal(hid.identity(False, False, False, True), ("PyDevices Gamepad", 0x03C4, 4), "identity, gamepad")
    equal(hid.identity(False, False, True, False), ("PyDevices Remote", 0x03C0, 2), "identity, remote")
    equal(hid.identity(True, True, True, True), ("PyDevices HID", 0x03C0, 15), "identity, all four: too long a name")


async def c_devices_have_usb_hids_shape(air):
    board = FakeBLE(air=air, mtu=247)
    per = hid.Peripheral(board, gamepad=True)
    got = [(d.usage_page, d.usage, d.report_id, d.in_report_length) for d in per.devices]
    equal(got, [(1, 6, 1, 8), (1, 2, 2, 4), (12, 1, 3, 2), (1, 5, 4, 7)], "devices")
    from adafruit_hid.keyboard import Keyboard
    from adafruit_hid.mouse import Mouse

    equal(Keyboard(per.devices)._keyboard_device is per.devices[0], True, "adafruit_hid finds the keyboard")
    equal(Mouse(per.devices)._mouse_device is per.devices[1], True, "adafruit_hid finds the mouse")
    try:
        per.devices[0].send_report(bytes(8))
    except BLEError:
        pass
    else:
        raise Failed("a report was sent with no host connected")
    for bad in ((bytes(7), None), (bytes(8), 2)):
        try:
            per.devices[0].send_report(*bad)
        except (ValueError, BLEError):
            pass
        else:
            raise Failed("send_report took {!r}".format(bad))


async def c_led_report_reaches_the_device(air):
    board, host_ble, per, host = await _pair_up(air)
    equal(board.config("gap_name"), per.name, "GAP name follows the HID name")
    await per.leds(2000)  # the host writes the LEDs once it has subscribed
    await host.set_leds(0x02)  # Caps Lock
    t, data = await per.leds(2000)
    equal(per.devices[0].get_last_received_report(), data, "get_last_received_report()")
    equal(data[0] & 0x02, 0x02, "Caps Lock's bit")
    from adafruit_hid.keyboard import Keyboard

    equal(Keyboard(per.devices).led_on(Keyboard.LED_CAPS_LOCK), True, "adafruit_hid reads it")
    await host.close()


async def c_a_backend_that_notifies_on_write_sends_once(air):
    # CircuitPython's _bleio notifies when a value is set; notifying again
    # would send each report twice, and a mouse would move twice.
    board = FakeBLE(air=air, mtu=247, notify_buffers=512)
    caps = board.capabilities()
    caps["write_notifies"] = True
    board.capabilities = lambda: caps
    per = hid.Peripheral(board)
    serving = asyncio.create_task(per.serve())
    host = await hid.connect(FakeBLE(air=air, mtu=247), name=per.name, timeout_ms=2000)
    await serving
    sent = []
    for d in per.devices:
        d._char.notify = lambda conn, data, _n=sent: _n.append(data)
    per.devices[1].send_report(b"\x00\x28\xf4\x00")
    equal(sent, [], "no notify on top of the write")
    await host.close()


async def c_a_busy_radio_gives_up(air):
    board, host_ble, per, host = await _pair_up(air, peripheral_kw={"notify_buffers": 2})
    old = hid.SEND_WAIT_MS
    hid.SEND_WAIT_MS = 20
    try:
        for _ in range(3):
            per.devices[2].send_report(b"\xe9\x00")
    except bledev.BusyError:
        pass
    else:
        raise Failed("a radio that stays busy didn't stop send_report")
    finally:
        hid.SEND_WAIT_MS = old
    await host.close()


async def c_script_round_trip(air):
    board, host_ble, per, host = await _pair_up(air)
    want = hid_script.expected(has_gamepad=False)
    await per.leds(2000)  # the host writes the LEDs once it has subscribed
    await hid_script.perform(per)
    got = await _collect(host, len(want))
    problem = hid_script.compare(got, want)
    if problem:
        raise Failed(problem)
    equal(hid_script.typed_text(got), hid_script.TEXT, "typed text")
    await asyncio.sleep(0)
    equal(host.poll(), [], "nothing extra")
    await host.close()


async def c_encrypted_pairs_and_bonds(air):
    board, host_ble, per, host = await _pair_up(air, encrypted=True)
    equal(host.paired, True, "the host had to pair")
    check_bond = board.address in host_ble.bonds and host_ble.address in board.bonds
    equal(check_bond, True, "both sides bonded")
    per.devices[0].send_report(b"\x00\x00\x04\x00\x00\x00\x00\x00")
    per.devices[0].send_report(bytes(8))
    got = await _collect(host, 2)
    equal([e.key for e in got], [ord("a"), ord("a")], "a key through an encrypted link")
    await host.close()


async def c_unpaired_read_refused(air):
    board = FakeBLE(air=air, mtu=247)
    other = FakeBLE(air=air, mtu=247)
    per = hid.Peripheral(board, encrypted=True)
    serving = asyncio.create_task(per.serve())
    device = await other.find(name=per.name, timeout_ms=2000)
    conn = await device.connect()
    await serving
    svc = await conn.service(hid.HID_SERVICE)
    rmap = await svc.characteristic(hid.REPORT_MAP)
    try:
        await rmap.read()
    except GattError as e:
        equal(e.status, INSUFFICIENT_ENCRYPTION, "status")
    else:
        raise Failed("an encrypted Report Map was read without pairing")
    await conn.disconnect()


async def c_short_read_host_says_why(air):
    # MicroPython reads one packet. At MTU 23 the map (162 bytes) is cut to
    # 22, and the host must say so instead of decoding garbage.
    board = FakeBLE(air=air, mtu=23)
    host_ble = FakeBLE(air=air, mtu=23, long_reads=False)
    per = hid.Peripheral(board)
    serving = asyncio.create_task(per.serve())
    try:
        await hid.connect(host_ble, name=per.name, timeout_ms=2000)
    except BLEError as e:
        if "long read" not in str(e):
            raise Failed("wrong error: {}".format(e))
    else:
        raise Failed("a truncated Report Map was accepted")
    await serving


async def c_map_fits_one_packet_at_247(air):
    # The same host at MTU 247 reads the whole map in one packet.
    board = FakeBLE(air=air, mtu=247)
    host_ble = FakeBLE(air=air, mtu=247, long_reads=False)
    per = hid.Peripheral(board)
    serving = asyncio.create_task(per.serve())
    host = await hid.connect(host_ble, name=per.name, timeout_ms=2000)
    await serving
    equal(host.report_map.descriptor, hid.report_map(), "whole map")
    await host.close()


async def c_disconnect_ends_events(air):
    board, host_ble, per, host = await _pair_up(air)
    await per.connection.disconnect()
    try:
        await host.events(1000)
    except bledev.DisconnectedError:
        pass
    else:
        raise Failed("events() didn't end on a disconnect")


async def c_gamepad_round_trip(air):
    board, host_ble, per, host = await _pair_up(air, gamepad=True)
    steps = [st for st in hid_script.STEPS if st[0] == "pad"]
    want = hid_script.expected(steps)
    await per.leds(2000)
    await hid_script.perform(per, steps)
    got = await _collect(host, len(want))
    problem = hid_script.compare(got, want)
    if problem:
        raise Failed(problem)
    await host.close()


TESTS = [
    c_served_map_parses,
    c_devices_have_usb_hids_shape,
    c_led_report_reaches_the_device,
    c_a_backend_that_notifies_on_write_sends_once,
    c_a_busy_radio_gives_up,
    c_script_round_trip,
    c_gamepad_round_trip,
    c_encrypted_pairs_and_bonds,
    c_unpaired_read_refused,
    c_short_read_host_says_why,
    c_map_fits_one_packet_at_247,
    c_disconnect_ends_events,
]


def _plant(name):
    if name == "drop_report":
        # The link loses one notification in twenty.
        orig = fake._Inbox.put
        count = [0]

        def put(self, item):
            count[0] += 1
            if count[0] % 20 == 7:
                self.event.set()
                return
            orig(self, item)

        fake._Inbox.put = put
    elif name == "shift_lost":
        # The peripheral forgets Shift.
        orig = hid.Device.send_report

        def send_report(self, report, report_id=None):
            if self.usage == 0x06:
                report = bytes((report[0] & ~0x02,)) + bytes(report[1:])
            orig(self, report, report_id)

        hid.Device.send_report = send_report
    elif name == "shift_lost_host":
        # The host's decoder forgets Shift.
        orig = hidreport.Decoder.feed

        def feed(self, data, report_id=None):
            if report_id == hid.KEYBOARD_ID and data:
                data = bytes((data[0] & ~0x02,)) + bytes(data[1:])
            return orig(self, data, report_id)

        hidreport.Decoder.feed = feed
    elif name == "axis_sign":
        # The decoder reads axes unsigned.
        orig = hidreport.Field.raw

        def raw(self, data, n=0):
            v = orig(self, data, n)
            return v & ((1 << self.size) - 1)

        hidreport.Field.raw = raw
    elif name == "no_pair":
        # The host never pairs.
        async def pair(self, bond=True, timeout_ms=20000):
            return None

        fake._FakeConnection.pair = pair
    else:
        raise SystemExit("unknown plant " + name)


PLANTS = ("drop_report", "shift_lost", "axis_sign", "no_pair")


def run():
    failed = 0
    for fn in TESTS:
        if MICROPYTHON:
            asyncio.new_event_loop()
        try:
            asyncio.run(asyncio.wait_for(fn(Air()), CHECK_TIMEOUT_S))
        except Exception as e:
            failed += 1
            print("FAIL", fn.__name__, "-", type(e).__name__, e)
        else:
            print("PASS", fn.__name__)
    print("{} checks, {} failed ({})".format(len(TESTS), failed, sys.implementation.name))
    return failed


def main(argv):
    for arg in argv:
        if arg.startswith("--plant="):
            _plant(arg.split("=", 1)[1])
            print("PLANTED", arg.split("=", 1)[1])
    sys.exit(1 if run() else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
