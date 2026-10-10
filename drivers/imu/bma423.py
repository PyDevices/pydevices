# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""Bosch BMA423 (and its replacement, the BMA456) accelerometer.

Returns ``(x, y, z)`` in g, as the other accelerometer drivers here do::

    accel = BMA423(i2c)
    accel.acceleration     # (0.01, -0.02, 1.0) lying flat, face up
    accel.temperature      # degrees C

The step counter, taps and wrist-wear wake-up run in the chip's own feature
engine, which needs Bosch's 6 KB firmware uploaded first (BMA423 only; the
BMA456 takes a different blob). ``load_features()`` does that, from the
``bma423_config`` module beside this one::

    accel.load_features(remap=(1, 0, ~2))   # the same axes as ``axes=``
    accel.enable_features(STEP_COUNTER | WRIST_WEAR | DOUBLE_TAP)
    accel.map_interrupts(INT_WRIST_WEAR | INT_DOUBLE_TAP)   # onto INT1
    accel.steps                              # steps since power-up or reset_steps()
    accel.interrupt_status()                 # INT_* bits latched since the last read

INT1 is set up push-pull, active high and latched, so it stays high until
``interrupt_status()`` reads it: a level an ESP32 can wake from sleep on
(``set_interrupt_pin(active_high=False)`` flips it).

Register map from Bosch's BMA423 datasheet (section 6); the BMA456 keeps the
same addresses for everything used here. The BMA423 has 12-bit data and the
BMA456 16-bit, both left-justified in the same registers, so one scale
serves both.

``axes`` remaps the chip's frame to the board's: a 3-tuple naming, for each
board axis, the chip axis (0, 1, 2) it comes from, negated with ``~`` (so
``~0`` is minus chip X).
"""

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


ADDRESS = const(0x19)
CHIP_BMA423 = const(0x13)
CHIP_BMA456 = const(0x16)

_CHIP_ID = const(0x00)
_DATA_X = const(0x12)
_TEMPERATURE = const(0x22)
_ACC_CONF = const(0x40)
_ACC_RANGE = const(0x41)
_PWR_CONF = const(0x7C)
_PWR_CTRL = const(0x7D)
_INT_STAT_0 = const(0x1C)
_STEP_COUNT = const(0x1E)
_ACTIVITY = const(0x27)
_INTERNAL_STATUS = const(0x2A)
_INT1_IO_CTRL = const(0x53)
_INT_LATCH = const(0x55)
_INT1_MAP = const(0x56)
_INIT_CTRL = const(0x59)
_ASIC_LSB = const(0x5B)
_ASIC_MSB = const(0x5C)
_FEATURES = const(0x5E)

# Feature-engine layout (Bosch BMA423 Sensor API V2.14.13): 70 bytes read
# and written through register 0x5E once the firmware is running.
_FEATURE_SIZE = const(70)
_STEP_OFFSET = const(0x3A)  # +1: reset 0x04, detector 0x08, counter 0x10, activity 0x20
_SINGLE_TAP_OFFSET = const(0x3C)
_DOUBLE_TAP_OFFSET = const(0x3E)
_WRIST_WEAR_OFFSET = const(0x40)
_REMAP_OFFSET = const(0x44)

# enable_features() flags
STEP_COUNTER = const(0x01)
ACTIVITY = const(0x02)
WRIST_WEAR = const(0x04)
SINGLE_TAP = const(0x08)
DOUBLE_TAP = const(0x10)

# interrupt_status() / map_interrupts() bits (INT_STATUS_0 / INT1_MAP)
INT_SINGLE_TAP = const(0x01)
INT_STEP = const(0x02)
INT_ACTIVITY = const(0x04)
INT_WRIST_WEAR = const(0x08)
INT_DOUBLE_TAP = const(0x10)
INT_ANY_MOTION = const(0x20)
INT_NO_MOTION = const(0x40)
INT_ERROR = const(0x80)

ACTIVITIES = ("still", "walking", "running", "unknown")

_RANGES = {2: 0, 4: 1, 8: 2, 16: 3}
# ACC_CONF: acc_perf_mode=1 (continuous filter), bwp=2 (normal), odr=8 (100 Hz)
_CONF_100HZ = const(0xA8)


class BMA423:
    def __init__(self, i2c, address=ADDRESS, *, range_g=4, axes=(0, 1, 2)):
        self._i2c = i2c
        self._address = address
        self._one = bytearray(1)
        self._six = bytearray(6)
        self.chip_id = self._read(_CHIP_ID)
        if self.chip_id not in (CHIP_BMA423, CHIP_BMA456):
            raise OSError("BMA423/BMA456 not found at 0x%02x (chip id 0x%02x)" % (address, self.chip_id))
        if range_g not in _RANGES:
            raise ValueError("range_g is one of 2, 4, 8, 16")
        self._axes = axes
        self._features_loaded = False
        self._write(_PWR_CONF, 0x00)  # advanced power save off: registers stay writable
        _sleep_ms(1)
        self._write(_ACC_CONF, _CONF_100HZ)
        self._write(_ACC_RANGE, _RANGES[range_g])
        self._write(_PWR_CTRL, 0x04)  # accelerometer on
        self._scale = range_g / 32768
        _sleep_ms(2)

    def _read(self, reg):
        self._i2c.readfrom_mem_into(self._address, reg, self._one)
        return self._one[0]

    def _write(self, reg, value):
        self._one[0] = value
        self._i2c.writeto_mem(self._address, reg, self._one)

    @property
    def raw(self):
        """Chip-frame counts, left-justified 16-bit, before remapping."""
        b = self._six
        self._i2c.readfrom_mem_into(self._address, _DATA_X, b)
        out = []
        for i in (0, 2, 4):
            v = b[i] | (b[i + 1] << 8)
            out.append(v - 0x10000 if v & 0x8000 else v)
        return out

    @property
    def acceleration(self):
        """``(x, y, z)`` in g, in the board's frame."""
        raw = self.raw
        s = self._scale
        return tuple((-raw[~a] if a < 0 else raw[a]) * s for a in self._axes)

    # -- feature engine (BMA423 only) ---------------------------------------

    @property
    def features_running(self):
        """True when the feature firmware is loaded and running (it stays
        loaded across a microcontroller reset while the chip keeps power)."""
        return self.chip_id == CHIP_BMA423 and self._read(_INTERNAL_STATUS) & 0x0F == 0x01

    def load_features(self, remap=None, chunk=32, force=False):
        """Upload Bosch's feature firmware, then switch the accelerometer
        back on. Takes about 200 ms; raises ``OSError`` if the chip doesn't
        report the firmware running. Skipped when it is already running
        (an upload restarts the step count), unless ``force``.

        ``remap`` tells the engine how the chip sits on the board, in the
        same form as ``axes=`` (a tilt-to-wake gesture is judged in the
        board's frame), and defaults to this driver's ``axes``. The
        firmware is lost when the chip loses power.
        """
        if self.chip_id != CHIP_BMA423:
            raise OSError("feature firmware is for the BMA423 (this is 0x%02x)" % self.chip_id)
        if not force and self.features_running:
            self._features_loaded = True
            return
        from bma423_config import CONFIG

        self._write(_PWR_CONF, 0x00)
        _sleep_ms(1)
        self._write(_INIT_CTRL, 0x00)
        mv = memoryview(CONFIG)
        for index in range(0, len(CONFIG), chunk):
            self._write(_ASIC_LSB, (index // 2) & 0x0F)
            self._write(_ASIC_MSB, (index // 2) >> 4)
            self._i2c.writeto_mem(self._address, _FEATURES, mv[index : index + chunk])
        self._write(_INIT_CTRL, 0x01)
        for _ in range(30):
            _sleep_ms(10)
            if self._read(_INTERNAL_STATUS) & 0x0F == 0x01:
                break
        else:
            raise OSError("BMA423 feature firmware did not start (status 0x%02x)" % self._read(_INTERNAL_STATUS))
        self._write(_ACC_CONF, _CONF_100HZ)  # the engine wants 50 Hz or more
        self._write(_PWR_CTRL, 0x04)
        axes = self._axes if remap is None else remap
        cfg = self._features()
        x, y, z = (a if a >= 0 else ~a for a in axes)
        cfg[_REMAP_OFFSET] = (x & 3) | ((axes[0] < 0) << 2) | ((y & 3) << 3) | ((axes[1] < 0) << 5) | ((z & 3) << 6)
        cfg[_REMAP_OFFSET + 1] = 1 if axes[2] < 0 else 0
        self._features(cfg)
        self.set_interrupt_pin(True)
        self._features_loaded = True

    def set_interrupt_pin(self, active_high=True):
        """INT1's polarity: push-pull, latched until ``interrupt_status()``
        reads it, high (the default) or low while an event is pending."""
        self._write(_INT1_IO_CTRL, 0x0A if active_high else 0x08)
        self._write(_INT_LATCH, 0x01)

    def _features(self, data=None):
        if data is None:
            buf = bytearray(_FEATURE_SIZE)
            self._i2c.readfrom_mem_into(self._address, _FEATURES, buf)
            return buf
        self._i2c.writeto_mem(self._address, _FEATURES, data)

    def enable_features(self, features, enable=True):
        """Switch features on (or off with ``enable=False``): any of
        ``STEP_COUNTER``, ``ACTIVITY``, ``WRIST_WEAR``, ``SINGLE_TAP``,
        ``DOUBLE_TAP``, or-ed together."""
        cfg = self._features()
        for flag, index, bit in (
            (STEP_COUNTER, _STEP_OFFSET + 1, 0x10),
            (ACTIVITY, _STEP_OFFSET + 1, 0x20),
            (WRIST_WEAR, _WRIST_WEAR_OFFSET, 0x01),
            (SINGLE_TAP, _SINGLE_TAP_OFFSET, 0x01),
            (DOUBLE_TAP, _DOUBLE_TAP_OFFSET, 0x01),
        ):
            if features & flag:
                cfg[index] = (cfg[index] | bit) if enable else (cfg[index] & ~bit)
        self._features(cfg)

    def map_interrupts(self, bits, enable=True):
        """Route ``INT_*`` events to the INT1 pin (or stop with
        ``enable=False``). The status bits latch whether mapped or not."""
        current = self._read(_INT1_MAP)
        self._write(_INT1_MAP, (current | bits) if enable else (current & ~bits))

    def interrupt_status(self):
        """The ``INT_*`` bits latched since the last call. Reading clears
        them and releases a latched INT1."""
        return self._read(_INT_STAT_0)

    @property
    def steps(self):
        """Steps counted since power-up or ``reset_steps()``."""
        b = self._six
        self._i2c.readfrom_mem_into(self._address, _STEP_COUNT, memoryview(b)[:4])
        return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

    def reset_steps(self):
        cfg = self._features()
        cfg[_STEP_OFFSET + 1] |= 0x04
        self._features(cfg)

    @property
    def activity(self):
        """``"still"``, ``"walking"``, ``"running"`` or ``"unknown"``
        (needs ``ACTIVITY`` enabled)."""
        return ACTIVITIES[self._read(_ACTIVITY) & 0x03]

    @property
    def temperature(self):
        """Die temperature in degrees C (1 degree resolution)."""
        t = self._read(_TEMPERATURE)
        return (t - 256 if t & 0x80 else t) + 23


def _sleep_ms(ms):
    try:
        from time import sleep_ms
    except ImportError:  # CPython
        from time import sleep

        sleep(ms / 1000)
        return
    sleep_ms(ms)
