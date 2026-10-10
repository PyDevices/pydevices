# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""X-Powers AXP2101 power management IC: rails, battery and the power key.

A small subset of the chip, enough for a board config to power its
peripherals before it starts them, read the battery, and see presses of the
power key. Register addresses and bit positions follow X-Powers' datasheet
as transcribed in XPowersLib (MIT, https://github.com/lewisxhe/XPowersLib,
``src/REG/AXP2101Constants.h`` and ``Micropython/src/AXP2101.py``).

Works with ``machine.I2C`` on MicroPython and, through a small adapter that
supplies ``readfrom_mem``/``writeto_mem``, with ``busio.I2C`` on
CircuitPython.

The rails are named the way the datasheet names them::

    pmu = AXP2101(i2c)
    pmu.set_rail("aldo2", 3300)     # millivolts, and switched on
    pmu.rail_enabled("aldo2")       # True
    pmu.battery_voltage             # volts, or None with no battery
    pmu.battery_status              # "missing", "dead", "charging", "discharging", "full"

The charger is the chip's: ``charger()`` sets its currents and cut-off and
switches it on or off, ``charge_state`` says what stage it is in. On a board
with no thermistor on the TS pin, call ``set_ts_pin(False)`` (or the charger
reads the missing sensor as a cold battery and never starts).
"""

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


ADDRESS = const(0x34)
CHIP_ID = const(0x4A)

_STATUS1 = const(0x00)
_STATUS2 = const(0x01)
_IC_TYPE = const(0x03)
_CHARGE_GAUGE_WDT = const(0x18)
_TS_PIN_CTRL = const(0x50)
_PRECHARGE = const(0x61)
_CHARGE_CURRENT = const(0x62)
_TERMINATION = const(0x63)
_CHARGE_VOLTAGE = const(0x64)
_ADC_CHANNELS = const(0x30)
_VBAT_H = const(0x34)
_DIE_TEMP_H = const(0x3C)
_VBUS_H = const(0x38)
_VSYS_H = const(0x3A)
_INTEN1 = const(0x40)
_INTEN2 = const(0x41)
_INTEN3 = const(0x42)
_INTSTS1 = const(0x48)
_INTSTS2 = const(0x49)
_INTSTS3 = const(0x4A)
_BAT_DET = const(0x68)
_BTN_BAT_VOLTAGE = const(0x6A)
_DCDC_ONOFF = const(0x80)
_LDO_ONOFF0 = const(0x90)
_LDO_ONOFF1 = const(0x91)
_BAT_PERCENT = const(0xA4)

# Power key events in INTSTS2 (and their enables in INTEN2).
KEY_RELEASED = const(0x01)  # positive edge
KEY_PRESSED = const(0x02)  # negative edge
KEY_LONG = const(0x04)
KEY_SHORT = const(0x08)

# ADC channel enables (register 0x30).
ADC_BATTERY = const(0x01)
ADC_VBUS = const(0x04)
ADC_VSYS = const(0x08)
ADC_DIE_TEMP = const(0x10)
_ADC_TS = const(0x02)

# Charge stages, STATUS2 bits 2-0.
CHARGE_STAGES = ("trickle", "precharge", "constant current", "constant voltage", "done", "not charging")
# Below this a fitted cell is treated as dead: a Li-ion cell this low is over-discharged.
DEAD_BATTERY_V = 3.0
# Fast-charge currents the chip offers (register 0x62 values 1-16), in mA.
_CHARGE_MA = (25, 50, 75, 100, 125, 150, 175, 200, 300, 400, 500, 600, 700, 800, 900, 1000)
_CHARGE_MV = (4000, 4100, 4200, 4350, 4400)

# name: (on/off register, bit, voltage register, min mV, max mV, step mV)
_LDOS = {
    "aldo1": (_LDO_ONOFF0, 0, 0x92, 500, 3500, 100),
    "aldo2": (_LDO_ONOFF0, 1, 0x93, 500, 3500, 100),
    "aldo3": (_LDO_ONOFF0, 2, 0x94, 500, 3500, 100),
    "aldo4": (_LDO_ONOFF0, 3, 0x95, 500, 3500, 100),
    "bldo1": (_LDO_ONOFF0, 4, 0x96, 500, 3500, 100),
    "bldo2": (_LDO_ONOFF0, 5, 0x97, 500, 3500, 100),
    "cpusldo": (_LDO_ONOFF0, 6, 0x98, 500, 1400, 50),
    "dldo1": (_LDO_ONOFF0, 7, 0x99, 500, 3400, 100),
    "dldo2": (_LDO_ONOFF1, 0, 0x9A, 500, 3400, 100),
}
# DC-DC converters: switched only. Their voltage steps are piecewise and a
# board that needs one moved can write the register itself.
_DCDCS = {"dcdc1": 0, "dcdc2": 1, "dcdc3": 2, "dcdc4": 3, "dcdc5": 4}


class AXP2101:
    """The AXP2101 at ``address`` on ``i2c``.

    Constructing reads the chip ID and raises ``OSError`` if anything else
    answers, so a board config fails at the line that names the PMU rather
    than later, at a peripheral that never powered up. It changes nothing
    else: every rail stays as the chip's OTP or a previous program left it.
    """

    def __init__(self, i2c, address=ADDRESS):
        self._i2c = i2c
        self._address = address
        self._buf = bytearray(1)
        self._buf2 = bytearray(2)
        chip = self._read(_IC_TYPE)
        if chip != CHIP_ID:
            raise OSError("AXP2101 not found at 0x%02x (chip id 0x%02x)" % (address, chip))

    # -- registers ---------------------------------------------------------

    def _read(self, reg):
        self._i2c.readfrom_mem_into(self._address, reg, self._buf)
        return self._buf[0]

    def _write(self, reg, value):
        self._buf[0] = value & 0xFF
        self._i2c.writeto_mem(self._address, reg, self._buf)

    def _update(self, reg, mask, value):
        self._write(reg, (self._read(reg) & ~mask) | (value & mask))

    def _read14(self, reg, bits):
        self._i2c.readfrom_mem_into(self._address, reg, self._buf2)
        return ((self._buf2[0] & ((1 << (bits - 8)) - 1)) << 8) | self._buf2[1]

    # -- rails -------------------------------------------------------------

    def set_rail(self, name, millivolts=None, enable=True):
        """Set an LDO's voltage (when given) and switch it on or off.

        The voltage is written before the rail is enabled, so a peripheral
        never sees the old voltage. DC-DC converters take ``enable`` only.
        """
        if name in _DCDCS:
            if millivolts is not None:
                raise ValueError("set a DC-DC voltage through its register")
            bit = 1 << _DCDCS[name]
            self._update(_DCDC_ONOFF, bit, bit if enable else 0)
            return
        onoff, bit, vreg, lo, hi, step = _LDOS[name]
        if millivolts is not None:
            if not lo <= millivolts <= hi or (millivolts - lo) % step:
                raise ValueError("%s takes %d-%d mV in %d mV steps" % (name, lo, hi, step))
            self._update(vreg, 0x1F, (millivolts - lo) // step)
        self._update(onoff, 1 << bit, (1 << bit) if enable else 0)

    def rail_enabled(self, name):
        if name in _DCDCS:
            return bool(self._read(_DCDC_ONOFF) & (1 << _DCDCS[name]))
        onoff, bit = _LDOS[name][:2]
        return bool(self._read(onoff) & (1 << bit))

    def rail_millivolts(self, name):
        onoff, bit, vreg, lo, hi, step = _LDOS[name]
        return lo + (self._read(vreg) & 0x1F) * step

    def set_backup_battery(self, millivolts=3300, enable=True):
        """Charge the RTC's backup cell (VBACKUP), 2600-3300 mV.

        On boards whose real-time clock is fed from VBACKUP this is also the
        clock's supply: with it off the clock may not answer on I2C at all.
        """
        if not 2600 <= millivolts <= 3300 or millivolts % 100:
            raise ValueError("backup battery takes 2600-3300 mV in 100 mV steps")
        self._update(_BTN_BAT_VOLTAGE, 0x07, (millivolts - 2600) // 100)
        self._update(_CHARGE_GAUGE_WDT, 0x04, 0x04 if enable else 0)

    # -- measurement -------------------------------------------------------

    def enable_adc(self, channels=ADC_BATTERY | ADC_VBUS | ADC_VSYS | ADC_DIE_TEMP):
        """Switch on the ADC channels the voltage properties read, and
        battery detection. Idempotent."""
        self._update(_ADC_CHANNELS, channels, channels)
        self._update(_BAT_DET, 0x01, 0x01)

    def set_ts_pin(self, monitor):
        """Battery temperature sensing on the TS pin, on or off.

        Off makes TS an external input the charger ignores, which is what a
        board with no thermistor fitted needs: otherwise the open pin reads
        as a battery too cold to charge, and the charger holds off.
        """
        if monitor:
            self._update(_TS_PIN_CTRL, 0x1F, 0x0A)  # as the chip powers up: thermistor input, current source on
            self._update(_ADC_CHANNELS, _ADC_TS, _ADC_TS)
        else:
            self._update(_TS_PIN_CTRL, 0x1F, 0x10)
            self._update(_ADC_CHANNELS, _ADC_TS, 0)

    def charger(self, enable=None, *, current_ma=None, precharge_ma=None, termination_ma=None, voltage_mv=None):
        """Set the charger and switch it on or off; returns whether it's on.

        ``current_ma`` is the fast-charge current (25-200 mA in 25 mA
        steps, then 100 mA steps to 1000), ``precharge_ma`` and
        ``termination_ma`` 0-200 mA in 25 mA steps, ``voltage_mv`` the
        cut-off: 4000, 4100, 4200, 4350 or 4400. Anything left out stays as
        it is. Size the current for the cell: a fifth to half of its rated
        capacity per hour (a 470 mAh cell: about 100-200 mA).
        """
        if current_ma is not None:
            if current_ma not in _CHARGE_MA:
                raise ValueError("current_ma is one of %s" % (_CHARGE_MA,))
            self._update(_CHARGE_CURRENT, 0x1F, _CHARGE_MA.index(current_ma) + 1)
        for reg, ma, name in ((_PRECHARGE, precharge_ma, "precharge_ma"), (_TERMINATION, termination_ma, "termination_ma")):
            if ma is not None:
                if not 0 <= ma <= 200 or ma % 25:
                    raise ValueError("%s takes 0-200 in 25 mA steps" % name)
                self._update(reg, 0x0F, ma // 25)
        if termination_ma is not None:
            self._update(_TERMINATION, 0x10, 0x10)
        if voltage_mv is not None:
            if voltage_mv not in _CHARGE_MV:
                raise ValueError("voltage_mv is one of %s" % (_CHARGE_MV,))
            self._update(_CHARGE_VOLTAGE, 0x07, _CHARGE_MV.index(voltage_mv) + 1)
        if enable is not None:
            self._update(_CHARGE_GAUGE_WDT, 0x02, 0x02 if enable else 0)
        return bool(self._read(_CHARGE_GAUGE_WDT) & 0x02)

    @property
    def charge_state(self):
        """The charger's stage: one of ``CHARGE_STAGES`` ("trickle",
        "precharge", "constant current", "constant voltage", "done", "not
        charging")."""
        stage = self._read(_STATUS2) & 0x07
        return CHARGE_STAGES[stage] if stage < len(CHARGE_STAGES) else "not charging"

    @property
    def die_temperature(self):
        """The chip's own temperature in degrees C (not the battery's)."""
        return 22.0 + (7274 - self._read14(_DIE_TEMP_H, 14)) / 20.0

    @property
    def battery_status(self):
        """``"missing"``, ``"dead"`` (fitted but below ``DEAD_BATTERY_V``),
        ``"charging"``, ``"full"`` or ``"discharging"``."""
        v = self.battery_voltage
        if v is None:
            return "missing"
        if v < DEAD_BATTERY_V:
            return "dead"
        if self.charging:
            return "charging"
        if self.charge_state == "done":
            return "full"
        return "discharging"

    @property
    def battery_present(self):
        return bool(self._read(_STATUS1) & 0x08)

    @property
    def vbus_present(self):
        return bool(self._read(_STATUS1) & 0x20)

    @property
    def battery_voltage(self):
        """Battery voltage in volts, or ``None`` with no battery fitted."""
        if not self.battery_present:
            return None
        return self._read14(_VBAT_H, 13) / 1000

    @property
    def vbus_voltage(self):
        """USB input voltage in volts (0.0 when unplugged)."""
        return self._read14(_VBUS_H, 14) / 1000

    @property
    def system_voltage(self):
        return self._read14(_VSYS_H, 14) / 1000

    @property
    def voltage(self):
        """Battery voltage, the same as ``battery_voltage`` -- the name
        ``battery_adc.BatteryADC`` uses, so either serves a ``battery`` role."""
        return self.battery_voltage

    @property
    def percent(self):
        """The fuel gauge's charge estimate, 0-100, or ``None`` with no
        battery or a dead one (see ``battery_status``).

        The gauge needs a few charge cycles before this means much."""
        v = self.battery_voltage
        if v is None or v < DEAD_BATTERY_V:
            return None
        return self._read(_BAT_PERCENT)

    @property
    def charging(self):
        return (self._read(_STATUS2) >> 5) & 0x03 == 0x01

    # -- power key ---------------------------------------------------------

    def enable_key_events(self, events=KEY_PRESSED | KEY_RELEASED | KEY_SHORT | KEY_LONG):
        """Route power-key events to the IRQ pin as well as the status
        register. The status bits latch either way."""
        self._update(_INTEN2, 0x0F, events)

    def key_events(self, clear=True):
        """The power-key events latched since the last call, as
        ``KEY_*`` bits; clears them unless ``clear=False``."""
        events = self._read(_INTSTS2) & 0x0F
        if clear and events:
            self._write(_INTSTS2, events)
        return events

    def clear_irq(self):
        for reg in (_INTSTS1, _INTSTS2, _INTSTS3):
            self._write(reg, 0xFF)

    def irq_pin_only(self, key_events=KEY_SHORT | KEY_PRESSED):
        """Route only power-key events to the IRQ pin (it goes low on one
        until ``clear_irq()``), so the pin can wake a sleeping MCU on the
        key and nothing else."""
        self._write(_INTEN1, 0)
        self._write(_INTEN3, 0)
        self._update(_INTEN2, 0xFF, key_events & 0x0F)
        self.clear_irq()


class PowerKey:
    """A power key read as a button, from the PMU's latched edges.

    The AXP2101 has no live "key is down" bit, only events, so the state is
    rebuilt from them: a press edge holds it down until a release edge. A
    press and release that both landed between two polls still reads as
    pressed once, so a quick tap is never lost.
    """

    def __init__(self, pmu):
        self._pmu = pmu
        self._down = False
        pmu.key_events()  # drop anything latched before we were looking

    @property
    def pressed(self):
        """True while held, or once for a tap since the last read."""
        events = self._pmu.key_events()
        if events & KEY_PRESSED and events & KEY_RELEASED:
            self._down = False
            return True
        if events & KEY_PRESSED:
            self._down = True
        elif events & KEY_RELEASED:
            self._down = False
        return self._down

    @property
    def value(self):
        """The key read like a pulled-up input pin: False while pressed.

        So ``keypad_gpio.GPIOButtons`` takes it beside real active-low pins."""
        return not self.pressed
