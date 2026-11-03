# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

from appdev import JoystickDriver


def _pin_level(pin):
    """Read a pin-like object (``Pin.value()`` / ``DigitalInOut.value``)."""
    value = pin.value
    return value() if callable(value) else value


def _axis_u16(axis):
    """Read 0–65535 from ``machine.ADC.read_u16`` or ``analogio.AnalogIn.value``."""
    if hasattr(axis, "read_u16"):
        return axis.read_u16()
    return axis.value


class GPIOJoystick(JoystickDriver):
    """
    A driver for a joystick that uses GPIO inputs.

    Args:
        instance_id: The instance ID of the joystick. (pygame joystick index)
        axes: ADC-like objects (``read_u16()`` or ``.value`` 0–65535).
        buttons: Pin-like objects for the buttons.
        button_high: True if logic high when button is pressed.
        hats: A list of tuples of Pin objects for the hats. A hat is a 4-way switch, like a d-pad. 4 pins: left, right, down, up.
    """

    def __init__(
        self,
        instance_id: int,
        axes,
        buttons=None,
        button_high: bool = False,
        hats=None,
    ):
        if hats is None:
            hats = []
        if buttons is None:
            buttons = []
        self._instance_id = instance_id
        self._axes = axes
        self._buttons = buttons
        self._hats = hats
        self._button_high = button_high

    def get_instance_id(self):
        return self._instance_id

    def get_numaxes(self):
        return len(self._axes)

    def get_numbuttons(self):
        return len(self._buttons)

    def get_numhats(self):
        return len(self._hats)

    def get_axis(self, axis):
        return _axis_u16(self._axes[axis]) / 32767.5 - 1

    def get_button(self, button):
        cmp = 1 if self._button_high else 0
        return _pin_level(self._buttons[button]) == cmp

    def get_hat(self, hat):
        l, r, d, u = self._hats[hat]
        cmp = 1 if self._button_high else 0
        lv, rv, dv, uv = (_pin_level(p) for p in (l, r, d, u))
        if (lv == cmp and rv == cmp) or (uv == cmp and dv == cmp):
            raise ValueError("Hat is in an invalid position")

        return (
            -1 if lv == cmp else 1 if rv == cmp else 0,
            -1 if dv == cmp else 1 if uv == cmp else 0,
        )

    def get_numballs(self):
        return 0
