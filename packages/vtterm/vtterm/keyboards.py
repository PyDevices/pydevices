# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Keyboards on the USB host port and over BLE, read from a timer.

Each source has ``poll()``, which never waits and returns a list of
``events.Key`` records (possibly empty), ``status``, a line saying what it's
connected to, and ``close()``. Sources look for a keyboard on their own and
find it again after it's unplugged or switched off.
"""

import events
import keys

# Imported once here: on MicroPython, importing a built-in module such as
# time inside a function looks for a file of that name on every call, which
# took 77 ms a time on an ESP32-S3 and starved the REPL.
from .console import ticks_diff, ticks_ms

#: How often a source with no keyboard looks for one, in ms.
LOOK_MS = 1000


def _now():
    return ticks_ms()


def _due(last, ms):
    return last is None or ticks_diff(ticks_ms(), last) >= ms


class UsbKeyboard:
    """A keyboard on the board's USB host port, in boot protocol.

    Starting the host takes the port: a board whose REPL is on its native
    USB loses that until `close`.
    """

    def __init__(self):
        import usb.core
        from usb.host import hid

        self._core = usb.core
        self._hid = hid
        usb.core.start(classes=("hid",))
        self.kbd = None
        self.status = "USB: no keyboard yet"
        self._looked = None

    def _look(self):
        hid = self._hid
        self._looked = _now()
        dev = self._core.find(custom_match=hid.Device.match(hid.KEYBOARD))
        if dev is None:
            return
        self.kbd = hid.Device(dev, protocol=hid.KEYBOARD, boot=True)
        self.status = "USB: %s %s" % (dev.manufacturer or "%04x" % dev.idVendor, dev.product or "%04x" % dev.idProduct)

    def poll(self):
        KEY_DOWN, KEY_UP = self._hid.KEY_DOWN, self._hid.KEY_UP
        if self.kbd is None:
            if _due(self._looked, LOOK_MS):
                self._look()
            return []
        out = []
        try:
            while True:
                ev = self.kbd.read(1)  # ms; 0 would wait forever, as in pyusb
                if not ev:
                    break
                kind, usage = ev[0], ev[1]
                if kind != KEY_DOWN and kind != KEY_UP:
                    continue
                pressed = events.KEYDOWN if kind == KEY_DOWN else events.KEYUP
                mod = keys.hid_modifiers(ev[2])
                if 0xE0 <= usage <= 0xE7:
                    code = keys.HID_MODIFIERS[usage - 0xE0][1]
                else:
                    code = keys.hid_keycode(usage)
                if code is not None:
                    out.append(events.Key(pressed, keys.keyname(code), code, mod, usage, None))
        except self._core.USBError:
            # Unplugged: look again.
            self._drop()
            self.status = "USB: keyboard gone"
        return out

    def _drop(self):
        kbd, self.kbd = self.kbd, None
        if kbd is not None:
            try:
                kbd.close()
            except Exception:
                pass

    def close(self):
        self._drop()
        self._core.stop()


async def _yield():
    # asyncio.sleep_ms(0) itself isn't a coroutine, so run() refuses it.
    import asyncio

    await asyncio.sleep_ms(0)


class BleKeyboard:
    """The first BLE keyboard advertising the HID service, as a host.

    bledev runs on asyncio, and the REPL runs no event loop, so `poll` runs
    the loop's ready tasks for one pass each time it's called.
    """

    def __init__(self, timeout_ms=8000):
        import asyncio

        import bledev.auto

        self._asyncio = asyncio
        self.ble = bledev.auto.adapter()
        self.host = None
        self.status = "BLE: looking for a keyboard"
        self.timeout_ms = timeout_ms
        self._task = asyncio.create_task(self._keep())
        self._closed = False

    async def _keep(self):
        import bledev.hid

        while not self._closed:
            try:
                host = await bledev.hid.connect(self.ble, timeout_ms=self.timeout_ms)
            except Exception as e:  # noqa: BLE001 - none near, or it went away: say so and look again
                self.status = "BLE: %s" % (e,) if str(e) else "BLE: no keyboard found"
                await self._asyncio.sleep_ms(LOOK_MS)
                continue
            self.host = host
            name = getattr(host.connection, "name", None) or "keyboard"
            self.status = "BLE: %s" % name
            # poll() drops self.host when a read fails; this loop watches its own copy.
            while not self._closed and self.host is host and host.connection.is_connected():
                await self._asyncio.sleep_ms(200)
            self.host = None
            try:
                await host.close()
            except Exception:  # noqa: BLE001 - it's gone either way
                pass
            if not self._closed:
                self.status = "BLE: keyboard gone"

    def _pump(self):
        self._asyncio.run(_yield())

    def poll(self):
        self._pump()
        host = self.host
        if host is None:
            return []
        try:
            return [e for e in host.poll() if hasattr(e, "key")]
        except Exception as e:  # noqa: BLE001 - the link dropped; _keep finds it again
            self.status = "BLE: %s" % (e,)
            self.host = None
            return []

    def close(self):
        self._closed = True
        host, self.host = self.host, None
        if host is not None:
            try:
                self._asyncio.run(host.close())
            except Exception:
                pass
        self._task.cancel()
        try:
            self._pump()
        except Exception:
            pass


def start_all():
    """Start every keyboard source this board can have.

    Returns:
        tuple: ``(sources, missing)``: the sources that started, and a line
        for each that couldn't, saying why.
    """
    out, missing = [], []
    for name, cls in (("USB", UsbKeyboard), ("BLE", BleKeyboard)):
        try:
            out.append(cls())
        except ImportError:
            missing.append("%s: not in this firmware" % name)
        except Exception as e:  # noqa: BLE001 - one source failing leaves the other
            missing.append("%s: %s" % (name, e))
    return out, missing
