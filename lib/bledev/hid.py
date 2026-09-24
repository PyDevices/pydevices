"""BLE keyboards and game controllers, both ways: HID over GATT (HOGP).

**As a host** (central), a board or a laptop connects to a BLE keyboard,
remote or gamepad and gets PyDevices events, the same ``events.Key`` and
``events.Joy*`` records a USB keyboard gives through usbif or SDL gives on the
desktop::

    import bledev.hid as hid

    host = await hid.connect(ble, name="Keyboard K380")
    while True:
        for event in await host.events():
            print(event)

It reads the device's Report Map, parses it (:mod:`bledev.hidreport`),
subscribes to every input report and decodes each one as it arrives. A
keyboard that insists on pairing gets it: the first read that fails for want
of encryption pairs the link and tries again, and with ``bond=True`` (the
default) the keys are kept, so the next connect is quick.

**As a device** (peripheral), a board advertises as a BLE keyboard, media
remote and gamepad, and types, taps and moves what you tell it::

    kb = hid.Peripheral(ble)                 # keyboard + consumer + gamepad
    await kb.serve()                         # waits for a host
    await kb.keyboard.type("Hello\\n")
    await kb.consumer.tap(hid.VOLUME_UP)
    await kb.gamepad.send(axes=(0, 127, 0, 0), buttons=0b101, hat=2)

Its name, appearance and Report Map follow from which of the three it
offers, the same way every time, because hosts cache a device's services
against its identity (``docs/ble.md`` in the anchor repo, section 7).

A laptop (bleak) or a browser can't advertise, so they are hosts only.
Windows keeps HID devices for itself once paired; don't pair a board you are
testing with the PC you are testing from, or it will type into it.
"""

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

import struct

try:
    from time import ticks_diff, ticks_us
except ImportError:  # CPython
    import time as _time

    def ticks_us():
        return int(_time.perf_counter() * 1000000)

    def ticks_diff(a, b):
        return a - b


from . import (
    BLEError,
    BusyError,
    Characteristic,
    Descriptor,
    GattError,
    INSUFFICIENT_AUTHENTICATION,
    INSUFFICIENT_ENCRYPTION,
    Service,
    UUID,
    sleep_ms,
    wait_ms,
)
from .hidreport import INPUT, OUTPUT, Decoder, HIDParseError, ReportMap

# GATT numbers from the HID Service and HOGP specifications.
HID_SERVICE = UUID(0x1812)
HID_INFORMATION = UUID(0x2A4A)
REPORT_MAP = UUID(0x2A4B)
HID_CONTROL_POINT = UUID(0x2A4C)
REPORT = UUID(0x2A4D)
PROTOCOL_MODE = UUID(0x2A4E)
REPORT_REFERENCE = UUID(0x2908)
BATTERY_SERVICE = UUID(0x180F)
BATTERY_LEVEL = UUID(0x2A19)
DEVICE_INFORMATION = UUID(0x180A)
PNP_ID = UUID(0x2A50)
MANUFACTURER_NAME = UUID(0x2A29)

#: The HID characteristics under a vendor UUID, for inspection from a laptop.
#: Windows hides the HID service (0x1812) from apps entirely, and Chrome's
#: Web Bluetooth blocklist does too, so a laptop can only see a board's HID
#: characteristics if the board serves them under another UUID.
INSPECT_SERVICE = UUID("b1ed0000-4849-4400-8000-00805f9b34fb")

APPEARANCE_HID = 0x03C0
APPEARANCE_KEYBOARD = 0x03C1
APPEARANCE_GAMEPAD = 0x03C4

# The report IDs a board serves.
KEYBOARD_ID = 1
CONSUMER_ID = 2
GAMEPAD_ID = 3

# Consumer usages worth a name.
VOLUME_UP = 0xE9
VOLUME_DOWN = 0xEA
MUTE = 0xE2
PLAY_PAUSE = 0xCD
NEXT_TRACK = 0xB5
PREV_TRACK = 0xB6

# Modifier bits in a keyboard report.
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08
MOD_RCTRL = 0x10
MOD_RSHIFT = 0x20
MOD_RALT = 0x40
MOD_RGUI = 0x80

KEYBOARD_MAP = bytes((
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, KEYBOARD_ID,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02,                          # 8 modifier bits
    0x95, 0x01, 0x75, 0x08, 0x81, 0x01,                          # reserved byte
    0x95, 0x05, 0x75, 0x01, 0x05, 0x08, 0x19, 0x01, 0x29, 0x05,
    0x91, 0x02, 0x95, 0x01, 0x75, 0x03, 0x91, 0x01,              # LEDs out
    0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65,
    0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00,              # 6 keys
    0xC0,
))

CONSUMER_MAP = bytes((
    0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, CONSUMER_ID,
    0x75, 0x10, 0x95, 0x01, 0x15, 0x01, 0x26, 0x8C, 0x02,
    0x19, 0x01, 0x2A, 0x8C, 0x02, 0x81, 0x00,                    # one 16-bit usage
    0xC0,
))

GAMEPAD_MAP = bytes((
    0x05, 0x01, 0x09, 0x05, 0xA1, 0x01, 0x85, GAMEPAD_ID,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x10, 0x81, 0x02,                          # 16 buttons
    0x05, 0x01, 0x09, 0x39, 0x15, 0x01, 0x25, 0x08,
    0x35, 0x00, 0x46, 0x3B, 0x01, 0x65, 0x14,
    0x75, 0x04, 0x95, 0x01, 0x81, 0x42,                          # hat, null = centred
    0x35, 0x00, 0x45, 0x00, 0x65, 0x00, 0x81, 0x03,              # 4 bits padding
    0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x35,
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x04, 0x81, 0x02,  # X Y Z Rz, -127..127
    0xC0,
))


def report_map(keyboard=True, consumer=True, gamepad=True):
    """The Report Map a board serves for this set of functions, always the same bytes."""
    return (KEYBOARD_MAP if keyboard else b"") + (CONSUMER_MAP if consumer else b"") + (GAMEPAD_MAP if gamepad else b"")


def identity(keyboard=True, consumer=True, gamepad=True):
    """``(name, appearance, product_id)`` for a set of functions, derived the same way every time."""
    parts = []
    if keyboard:
        parts.append("Keyboard")
    if gamepad:
        parts.append("Gamepad")
    if consumer and not keyboard:
        parts.append("Remote")
    name = "PyDevices " + "+".join(parts) if parts else "PyDevices HID"
    if keyboard and not gamepad:
        appearance = APPEARANCE_KEYBOARD
    elif gamepad and not keyboard and not consumer:
        appearance = APPEARANCE_GAMEPAD
    else:
        appearance = APPEARANCE_HID
    product = (1 if keyboard else 0) | (2 if consumer else 0) | (4 if gamepad else 0)
    return name, appearance, product


# US layout: character -> (usage, shift).
def _us_layout():
    table = {"\n": (0x28, False), "\t": (0x2B, False), " ": (0x2C, False)}
    for i in range(26):
        table[chr(ord("a") + i)] = (0x04 + i, False)
        table[chr(ord("A") + i)] = (0x04 + i, True)
    for i, (plain, shifted) in enumerate(zip("1234567890", "!@#$%^&*()")):
        table[plain] = (0x1E + i, False)
        table[shifted] = (0x1E + i, True)
    for usage, plain, shifted in (
        (0x2D, "-", "_"), (0x2E, "=", "+"), (0x2F, "[", "{"), (0x30, "]", "}"),
        (0x31, "\\", "|"), (0x33, ";", ":"), (0x34, "'", '"'), (0x35, "`", "~"),
        (0x36, ",", "<"), (0x37, ".", ">"), (0x38, "/", "?"),
    ):
        table[plain] = (usage, False)
        table[shifted] = (usage, True)
    return table


US_LAYOUT = _us_layout()


# ---------------------------------------------------------------- the device (peripheral)


class _Sender:
    def __init__(self, owner, characteristic, size):
        self._owner = owner
        self._char = characteristic
        self._size = size

    async def _send(self, report):
        report = bytes(report)
        if len(report) != self._size:
            raise ValueError("report is {} bytes, not {}".format(len(report), self._size))
        conn = self._owner.connection
        if conn is None or not conn.is_connected():
            raise BLEError("no host connected")
        self._char.write(report)
        waited = 0
        while True:
            try:
                self._char.notify(conn, report)
                self._owner.last_send_us = ticks_us()
                return
            except BusyError:
                if waited >= 2000:
                    raise
                await sleep_ms(2)
                waited += 2


class Keyboard(_Sender):
    """The keyboard half of a :class:`Peripheral`. Usages are HID keyboard usages."""

    async def send(self, modifiers=0, keys=()):
        """Send one report: ``modifiers`` bits held, and up to six usages held."""
        keys = list(keys)[:6]
        await self._send(bytes([modifiers, 0] + keys + [0] * (6 - len(keys))))

    async def tap(self, usage, modifiers=0, hold_ms=0):
        """Press and release one key (with ``modifiers`` held around it)."""
        await self.send(modifiers, (usage,))
        if hold_ms:
            await sleep_ms(hold_ms)
        await self.send(0, ())

    async def type(self, text, gap_ms=0):
        """Type ``text`` on a US layout: each character a press and a release."""
        for ch in text:
            usage, shift = US_LAYOUT[ch]
            await self.tap(usage, MOD_LSHIFT if shift else 0)
            if gap_ms:
                await sleep_ms(gap_ms)


class Consumer(_Sender):
    """Media keys: consumer-page usages such as :data:`VOLUME_UP`."""

    async def send(self, usage=0):
        await self._send(struct.pack("<H", usage))

    async def tap(self, usage, hold_ms=0):
        await self.send(usage)
        if hold_ms:
            await sleep_ms(hold_ms)
        await self.send(0)


class Gamepad(_Sender):
    """Sixteen buttons, one hat and four axes (X, Y, Z, Rz) from -127 to 127."""

    async def send(self, axes=(0, 0, 0, 0), buttons=0, hat=None):
        """``buttons`` is a bit mask (bit 0 is button 0); ``hat`` 0..7 clockwise from north, or None."""
        x, y, z, rz = axes
        await self._send(struct.pack("<HBbbbb", buttons & 0xFFFF, 0 if hat is None else hat + 1, x, y, z, rz))


class Peripheral:
    """A board that is a BLE keyboard, media remote and gamepad (any of the three).

    ``encrypted=True`` serves the Report Map and reports only to a host that
    has paired, as real keyboards do; the host pairs "just works". Call
    ``ble.enable_bonding()`` first on MicroPython so the keys are kept.

    ``service_uuid=INSPECT_SERVICE`` serves the same characteristics under a
    vendor UUID instead of 0x1812, so a laptop can read them (no host will
    treat the board as a keyboard then).
    """

    def __init__(self, ble, *, keyboard=True, consumer=True, gamepad=True,
                 name=None, encrypted=False, battery=100, manufacturer="PyDevices",
                 service_uuid=HID_SERVICE):
        if not (keyboard or consumer or gamepad):
            raise ValueError("a HID peripheral needs at least one function")
        self.ble = ble
        default_name, self.appearance, product = identity(keyboard, consumer, gamepad)
        self.name = name or default_name
        self.report_map = report_map(keyboard, consumer, gamepad)
        self.connection = None
        self.last_send_us = None
        self._leds = []
        self._leds_flag = asyncio.Event()

        self.service_uuid = UUID(service_uuid)
        hid = Service(self.service_uuid)
        # bcdHID 1.11, no country, normally connectable.
        Characteristic(hid, HID_INFORMATION, read=True, initial=b"\x11\x01\x00\x02")
        Characteristic(hid, REPORT_MAP, read=True, initial=self.report_map, encrypted=encrypted)
        Characteristic(hid, HID_CONTROL_POINT, write_no_response=True, max_len=1)
        self.keyboard = self.consumer = self.gamepad = None
        if keyboard:
            c = self._report(hid, KEYBOARD_ID, 8, encrypted)
            self.keyboard = Keyboard(self, c, 8)
            self._led_char = Characteristic(hid, REPORT, read=True, write=True, write_no_response=True,
                                            initial=b"\x00", capture=True, max_len=1, encrypted=encrypted)
            Descriptor(self._led_char, REPORT_REFERENCE, bytes((KEYBOARD_ID, OUTPUT)))
        else:
            self._led_char = None
        if consumer:
            self.consumer = Consumer(self, self._report(hid, CONSUMER_ID, 2, encrypted), 2)
        if gamepad:
            self.gamepad = Gamepad(self, self._report(hid, GAMEPAD_ID, 7, encrypted), 7)
        battery_svc = Service(BATTERY_SERVICE)
        self.battery = Characteristic(battery_svc, BATTERY_LEVEL, read=True, notify=True, initial=bytes((battery,)))
        info = Service(DEVICE_INFORMATION)
        Characteristic(info, MANUFACTURER_NAME, read=True, initial=manufacturer.encode())
        # PnP ID: vendor ID source 1 (Bluetooth SIG), company 0xFFFF (the
        # number the SIG reserves for testing), product from the function set.
        Characteristic(info, PNP_ID, read=True, initial=struct.pack("<BHHH", 1, 0xFFFF, product, 0x0100))
        self.services = (hid, battery_svc, info)
        self._registered = False
        self._led_task = None

    def _report(self, service, report_id, size, encrypted):
        c = Characteristic(service, REPORT, read=True, notify=True, initial=bytes(size), encrypted=encrypted)
        Descriptor(c, REPORT_REFERENCE, bytes((report_id, INPUT)))
        return c

    async def serve(self, timeout_ms=None):
        """Advertise until a host connects, and return the connection."""
        if not self._registered:
            self.ble.register_services(*self.services)
            self._registered = True
        self.connection = await self.ble.advertise(
            name=self.name, services=[self.service_uuid], appearance=self.appearance, timeout_ms=timeout_ms
        )
        if self._led_char is not None and self._led_task is None:
            self._led_task = asyncio.create_task(self._watch_leds())
        return self.connection

    async def _watch_leds(self):
        while True:
            try:
                _, data = await self._led_char.written()
            except BLEError:
                await sleep_ms(10)
                continue
            self._leds.append((ticks_us(), bytes(data)))
            self._leds_flag.set()

    async def leds(self, timeout_ms=None):
        """The next LED report the host writes, as ``(ticks_us, data)``."""
        while not self._leds:
            self._leds_flag.clear()
            await wait_ms(self._leds_flag.wait(), timeout_ms, "leds")
        return self._leds.pop(0)

    def close(self):
        if self._led_task is not None:
            self._led_task.cancel()
            self._led_task = None


# ---------------------------------------------------------------- the host (central)


class Host:
    """One connected HID device, as a stream of PyDevices events.

    Make it with :func:`connect`, or :meth:`start` it on a connection you
    already have. ``report_map`` is the parsed :class:`ReportMap`;
    ``paired`` says whether it had to pair.
    """

    def __init__(self, connection, *, bond=True, instance_id=0, queue_limit=256, service_uuid=HID_SERVICE):
        self.connection = connection
        self.service_uuid = UUID(service_uuid)
        self.bond = bond
        self.instance_id = instance_id
        self.report_map = None
        self.decoder = None
        self.paired = False
        #: When the last input report arrived, in ``ticks_us``.
        self.last_report_us = None
        self._queue = []
        self._limit = queue_limit
        self._overrun = 0
        self._flag = asyncio.Event()
        self._tasks = []
        self._error = None
        self._leds = None

    async def _secure(self, op):
        # A device that wants an encrypted link says so with an error; pair
        # and try once more.
        try:
            return await op()
        except GattError as e:
            if e.status not in (INSUFFICIENT_ENCRYPTION, INSUFFICIENT_AUTHENTICATION) or self.paired:
                raise
        await self.connection.pair(bond=self.bond)
        self.paired = True
        return await op()

    async def start(self, timeout_ms=5000):
        conn = self.connection
        caps = conn._ble.capabilities()
        if not caps.get("long_read", True):
            # One ATT read carries mtu - 1 bytes of the Report Map.
            await conn.exchange_mtu(247)
        service = await conn.service(self.service_uuid, timeout_ms)
        if service is None:
            raise BLEError("{} has no HID service".format(conn.device))
        chars = []
        async for c in service.characteristics(None, timeout_ms):
            chars.append(c)
        rmap = [c for c in chars if c.uuid == REPORT_MAP]
        if not rmap:
            raise BLEError("the HID service has no Report Map")
        data = await self._secure(lambda: rmap[0].read(timeout_ms))
        try:
            self.report_map = ReportMap(data)
        except HIDParseError as e:
            if not caps.get("long_read", True) and len(data) >= conn.mtu - 1:
                raise BLEError(
                    "the Report Map is at least {} bytes and this host reads one packet "
                    "(mtu {} - 1); MicroPython has no long read".format(len(data), conn.mtu)
                )
            raise BLEError("the Report Map doesn't parse: {}".format(e))
        self.decoder = Decoder(self.report_map, self.instance_id)
        for c in chars:
            if c.uuid == PROTOCOL_MODE:
                # Report protocol (1), which is also the default after connecting.
                try:
                    await self._secure(lambda: c.write(b"\x01", response=False))
                except BLEError:
                    pass
        inputs = []
        for c in chars:
            if c.uuid != REPORT:
                continue
            ref = await c.descriptor(REPORT_REFERENCE, timeout_ms)
            if ref is None:
                continue
            value = await self._secure(lambda: ref.read(timeout_ms))
            if len(value) < 2:
                continue
            report_id, kind = value[0], value[1]
            if kind == INPUT:
                inputs.append((c, report_id))
            elif kind == OUTPUT and report_id and self.report_map.report(OUTPUT, report_id):
                self._leds = (c, report_id)
        if not inputs:
            raise BLEError("the HID service has no input reports")
        for c, report_id in inputs:
            await self._secure(lambda: c.subscribe(notify=True))
        for c, report_id in inputs:
            self._tasks.append(asyncio.create_task(self._reader(c, report_id)))
        if self._leds is not None:
            # Hosts set a keyboard's LEDs once they're listening; it also
            # tells our own Peripheral that someone is (Peripheral.leds()).
            await self.set_leds(0)
        return self

    async def _reader(self, characteristic, report_id):
        try:
            while True:
                data = await characteristic.notified()
                self.last_report_us = ticks_us()
                for event in self.decoder.feed(data, report_id):
                    if len(self._queue) >= self._limit:
                        self._overrun += 1
                    else:
                        self._queue.append(event)
                self._flag.set()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # a disconnect, or an overrun below us
            self._error = e
            self._flag.set()

    def _check(self):
        if self._overrun:
            n, self._overrun = self._overrun, 0
            raise BLEError("{} HID event(s) dropped: nobody read them".format(n))

    def poll(self):
        """Every event decoded so far, as a list (possibly empty). Never waits."""
        self._check()
        out, self._queue = self._queue, []
        if not out and self._error is not None:
            raise self._error
        return out

    async def events(self, timeout_ms=None):
        """Wait for at least one event, and return every one waiting."""
        while not self._queue:
            self._check()
            if self._error is not None:
                raise self._error
            self._flag.clear()
            await wait_ms(self._flag.wait(), timeout_ms, "HID events")
        return self.poll()

    async def set_leds(self, bits):
        """Write the keyboard's LED report (Num Lock is bit 0), if it has one."""
        if self._leds is None:
            raise BLEError("this device has no LED report")
        c, _ = self._leds
        await self._secure(lambda: c.write(bytes((bits,)), response=False))

    async def close(self):
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        if self.connection.is_connected():
            await self.connection.disconnect()


async def connect(ble, name=None, *, device=None, timeout_ms=10000, bond=True, instance_id=0,
                  service_uuid=HID_SERVICE, **options):
    """Find a BLE HID device (by ``name``, or any advertising the HID service),
    connect, and return a started :class:`Host`."""
    if device is None:
        device = await ble.find(name=name, service=None if name else service_uuid, timeout_ms=timeout_ms)
    connection = await device.connect(timeout_ms=timeout_ms, **options)
    host = Host(connection, bond=bond, instance_id=instance_id, service_uuid=service_uuid)
    try:
        await host.start()
    except BaseException:
        await host.close()
        raise
    return host


__all__ = [
    "Host", "Peripheral", "Keyboard", "Consumer", "Gamepad", "connect", "report_map", "identity",
    "US_LAYOUT", "ticks_us", "ticks_diff",
]
