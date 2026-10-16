"""A gamepad for a :class:`bledev.hid.Peripheral`, in the shape of Adafruit's
``hid_gamepad.py`` example (``adafruit_hid`` dropped its own gamepad in 5.0)::

    import bledev.hid as hid
    from bledev.hid_gamepad import Gamepad

    per = hid.Peripheral(ble, gamepad=True)
    await per.serve()
    gp = Gamepad(per.devices)
    gp.press_buttons(1, 3)
    gp.move_joysticks(x=-127, y=0)
    gp.set_hat(2)            # east; None is centred
    gp.release_all_buttons()

Sixteen buttons numbered 1 to 16, one hat (0 to 7 clockwise from north, or
None) and four axes, X, Y, Z and Rz, from -127 to 127. Each call sends the
whole report at once, as Adafruit's example does.
"""

import struct

_KEEP = object()


def _find(devices):
    if hasattr(devices, "send_report"):
        devices = (devices,)
    for dev in devices:
        if dev.usage_page == 0x01 and dev.usage == 0x05 and hasattr(dev, "send_report"):
            return dev
    raise ValueError("Could not find matching HID device.")


def _axis(value):
    if not -127 <= value <= 127:
        raise ValueError("Joystick values must be in range -127 to 127")
    return value


class Gamepad:
    """Emulate a gamepad with sixteen buttons, a hat and four joystick axes."""

    def __init__(self, devices):
        self._device = _find(devices)
        self._report = bytearray(7)
        self._buttons = 0
        self._hat = None
        self._axes = [0, 0, 0, 0]
        self._last = bytearray(7)

    def press_buttons(self, *buttons):
        """Press and hold the given buttons (1 to 16)."""
        for b in buttons:
            self._buttons |= 1 << self._validate_button(b) - 1
        self._send()

    def release_buttons(self, *buttons):
        """Release the given buttons."""
        for b in buttons:
            self._buttons &= ~(1 << self._validate_button(b) - 1)
        self._send()

    def release_all_buttons(self):
        """Release every button."""
        self._buttons = 0
        self._send()

    def click_buttons(self, *buttons):
        """Press and release the given buttons."""
        self.press_buttons(*buttons)
        self.release_buttons(*buttons)

    def move_joysticks(self, x=None, y=None, z=None, r_z=None):
        """Set any of the four axes; ``None`` leaves an axis where it is."""
        for i, v in enumerate((x, y, z, r_z)):
            if v is not None:
                self._axes[i] = _axis(v)
        self._send()

    def set_hat(self, direction):
        """Point the hat: 0 north to 7 north-west, clockwise, or None for centred."""
        if direction is not None and not 0 <= direction <= 7:
            raise ValueError("hat direction must be 0 to 7, or None")
        self._hat = direction
        self._send()

    def set(self, buttons=None, hat=_KEEP, x=None, y=None, z=None, r_z=None):
        """Change any part of the state in one report: ``buttons`` as a bit
        mask (bit 0 is button 1), ``hat`` as for :meth:`set_hat`, the axes as
        for :meth:`move_joysticks`. Anything left out stays as it is."""
        if buttons is not None:
            self._buttons = buttons & 0xFFFF
        if hat is not _KEEP:
            if hat is not None and not 0 <= hat <= 7:
                raise ValueError("hat direction must be 0 to 7, or None")
            self._hat = hat
        for i, v in enumerate((x, y, z, r_z)):
            if v is not None:
                self._axes[i] = _axis(v)
        self._send()

    def reset_all(self):
        """Release every button, centre the hat and every axis."""
        self._buttons = 0
        self._hat = None
        self._axes = [0, 0, 0, 0]
        self._send(always=True)

    def _send(self, always=False):
        x, y, z, rz = self._axes
        struct.pack_into("<HBbbbb", self._report, 0, self._buttons & 0xFFFF,
                         0 if self._hat is None else self._hat + 1, x, y, z, rz)
        if always or self._report != self._last:
            self._device.send_report(self._report)
            self._last[:] = self._report

    @staticmethod
    def _validate_button(button):
        if not 1 <= button <= 16:
            raise ValueError("Button number must in range 1 to 16")
        return button
