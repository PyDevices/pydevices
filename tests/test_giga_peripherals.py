# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""The GIGA Display Shield's IMU shares the touch controller's I2C bus.

The BMI270 and the GT911 are both on I2C4. A second ``machine.I2C`` on that
port would leave one of them answering and the other silent, so the IMU
roles must take ``board_config.i2c`` when the display is up, and open port 4
once, and only once, when it isn't. These load the board's
board_peripherals.py with stand-in ``machine`` and ``bmi270`` modules.
"""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

_PATH = "board_configs/fbdisplay/arduino-giga-display-shield/board_peripherals.py"


def _fakes(events):
    machine = types.ModuleType("machine")

    class I2C:
        def __init__(self, port, **kwargs):
            self.port = port
            self.timingr = kwargs.get("timingr")
            events.append(("I2C", port))

    class Pin:
        IN = OUT = PULL_DOWN = 0

        def __init__(self, name, mode=None, pull=None, value=None):
            self.name = name
            self.pull = pull
            self.level = value

        def value(self, v=None):
            if v is None:
                return self.level
            self.level = v

    class Signal:
        def __init__(self, pin, invert=False):
            self.pin = pin
            self.invert = invert

        def on(self):
            self.pin.value(0 if self.invert else 1)

    machine.I2C = I2C
    machine.Pin = Pin
    machine.Signal = Signal

    bmi270 = types.ModuleType("bmi270")

    class BMI270:
        def __init__(self, bus, address=0x68):
            self.bus = bus
            self.address = address
            events.append(("BMI270", bus, address))

    bmi270.BMI270 = BMI270
    # MicroPython's time, which has sleep_ms.
    clock = types.ModuleType("time")
    clock.sleep_ms = lambda ms: None
    return {"machine": machine, "bmi270": bmi270, "time": clock, "board_config": None}


def _load(modules):
    spec = importlib.util.spec_from_file_location("giga_board_peripherals_under_test", _env.ROOT / _PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class GigaPeripheralsTests(unittest.TestCase):
    def test_imu_takes_board_configs_bus(self):
        events = []
        modules = _fakes(events)
        bp = _load(modules)
        shared = modules["machine"].I2C(4)
        events.clear()
        modules["board_config"] = types.SimpleNamespace(i2c=shared)
        with mock.patch.dict(sys.modules, modules):
            accel = bp.accelerometer()
            gyro = bp.gyroscope()
        self.assertIs(accel, gyro)
        self.assertEqual(events, [("BMI270", shared, 0x68)])

    def test_without_board_config_port_4_opens_once(self):
        events = []
        modules = _fakes(events)
        bp = _load(modules)
        with mock.patch.dict(sys.modules, modules):
            bp.accelerometer()
            bp.gyroscope()
            bus = bp._i2c_bus()
        self.assertEqual([e for e in events if e[0] == "I2C"], [("I2C", 4)])
        self.assertEqual(bus.port, 4)
        self.assertEqual(bus.timingr, bp.I2C_TIMINGR)

    def test_i2c_timing_is_fast_mode_at_120_mhz(self):
        # I2C(freq=400_000) on an H7 writes a 54 MHz value that runs this bus
        # near 1 MHz; the board passes its own. Decoded per the STM32H7
        # reference manual's TIMINGR fields, ignoring the sync delays (which
        # only lengthen each phase).
        bp = _load(_fakes([]))
        t = bp.I2C_TIMINGR
        tick = ((t >> 28) + 1) * 1000 / 120  # ns at 120 MHz
        low = round(((t & 0xFF) + 1) * tick)
        high = round((((t >> 8) & 0xFF) + 1) * tick)
        setup = round((((t >> 20) & 0xF) + 1) * tick)
        self.assertGreaterEqual(low, 1300)
        self.assertGreaterEqual(high, 600)
        self.assertGreaterEqual(setup, 100 + 300)  # tSU;DAT plus the slowest rise
        self.assertGreaterEqual(low + high, 2500 - 150)  # at most 400 kHz with the sync delays

    def test_led_is_active_low_and_starts_off(self):
        modules = _fakes([])
        bp = _load(modules)
        with mock.patch.dict(sys.modules, modules):
            led = bp.led()
        self.assertEqual((led.pin.name, led.pin.level, led.invert), ("LED_GREEN", 1, True))
        led.on()
        self.assertEqual(led.pin.level, 0)

    def test_boot_button_is_pc13_pulled_down(self):
        modules = _fakes([])
        bp = _load(modules)
        with mock.patch.dict(sys.modules, modules):
            button = bp.boot_button()
        self.assertEqual((button.name, button.pull), ("PC13", modules["machine"].Pin.PULL_DOWN))

    def test_usb_midi_starts_the_midi_device(self):
        modules = _fakes([])
        midiports = types.ModuleType("midiports")
        usb_device = types.ModuleType("midiports.usb_device")
        usb_device.ports = lambda: ("in", "out")
        midiports.usb_device = usb_device
        modules.update({"midiports": midiports, "midiports.usb_device": usb_device})
        bp = _load(modules)
        with mock.patch.dict(sys.modules, modules):
            self.assertEqual(bp.usb_midi(), ("in", "out"))

    def test_the_dac_ring_follows_what_the_caller_asks_for(self):
        bp = _load(_fakes([]))
        for kwargs, want in (({}, None), ({"latency": "low"}, None),
                             ({"latency": "buffered"}, bp.BUFFERED_MS),
                             ({"queue_ms": 40}, 40), ({"latency": "buffered", "queue_ms": 120}, 120)):
            with self.subTest(**kwargs):
                self.assertEqual(bp._pcm_out(**kwargs)._inner.buffer_ms, want)

    def test_every_role_has_a_hook(self):
        bp = _load(_fakes([]))
        for role in bp.PERIPHERALS:
            with self.subTest(role=role):
                self.assertTrue(callable(getattr(bp, role)))


if __name__ == "__main__":
    unittest.main()
