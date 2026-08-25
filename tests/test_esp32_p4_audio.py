"""Host simulation of the ESP32-P4 board audio wiring."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

ROOT = _env.ROOT
BOARD = ROOT / "board_configs" / "fbdisplay" / "esp32-p4-wifi6-touch-lcd-4b"


class FakeI2C:
    def __init__(self):
        self.registers = {}

    def writeto_mem(self, address, register, data):
        self.registers[register] = data[0]

    def readfrom_mem_into(self, address, register, target):
        target[0] = self.registers.get(register, 0)


class FakePin:
    OUT = 1
    instances = {}

    def __init__(self, number, mode=None, value=None):
        self.number = number
        self.state = value
        self.instances[number] = self

    def value(self, value=None):
        if value is not None:
            self.state = value
        return self.state


class FakeI2S:
    TX = 1
    RX = 2
    STEREO = 3
    MONO = 4

    def __init__(self, number, **kwargs):
        self.number = number
        self.options = kwargs
        self.closed = False

    def write(self, data):
        return len(data)

    def readinto(self, target):
        target[:] = bytes(len(target))
        return len(target)

    def deinit(self):
        self.closed = True


class FakePWM:
    instances = []

    def __init__(self, pin, freq=None, duty_u16=None):
        self.pin = pin
        self._freq = freq
        self.duty_u16 = duty_u16
        self.closed = False
        self.instances.append(self)

    def freq(self, value=None):
        if value is not None:
            self._freq = value
        return self._freq

    def deinit(self):
        self.closed = True


class ESP32P4AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_modules = {
            name: sys.modules.get(name) for name in ("audiocore", "board_config", "boarddev", "machine")
        }
        sys.modules["audiocore"] = types.SimpleNamespace()
        cls.i2c = FakeI2C()
        sys.modules["board_config"] = types.SimpleNamespace(i2c=cls.i2c)
        sys.modules["boarddev"] = types.SimpleNamespace(bind_lazy=lambda *args: None)
        sys.modules["machine"] = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin, PWM=FakePWM)
        spec = importlib.util.spec_from_file_location("p4_board_peripherals", BOARD / "board_peripherals.py")
        cls.board = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.board)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def tearDown(self):
        for session in (self.board._SESSION, self.board._INPUT_SESSION):
            session._owners[:] = []
            # Drop the cached codec too: it holds register state from whatever
            # this test opened, and the next test expects a fresh bring-up.
            session.codec = None
        self.i2c.registers.clear()
        FakePin.instances.clear()
        FakePWM.instances.clear()
        self.board._pa = None
        self.board._mclk = None

    def test_output_format_is_24khz_mono_pcm(self):
        from audiodev import AudioFormat

        output = self.board.audio_out()
        self.assertEqual(output.format, AudioFormat(24000, 1, 16))

    def test_output_has_codec_controls_and_amplifier_lifecycle(self):
        output = self.board.audio_out()
        self.assertIsNotNone(output.codec)
        self.assertEqual(output.codec.mclk_multiplier, 512)
        self.assertEqual(self.i2c.registers[0x02], 0x20)
        output.set_volume(42)
        output.open()
        self.assertEqual(output.codec.dac_volume, 42)
        self.assertFalse(output.codec.dac_muted)
        self.assertEqual(FakePin.instances[53].state, 1)
        output.close()
        self.assertTrue(output.codec.dac_muted)
        self.assertEqual(FakePin.instances[53].state, 0)

    def test_default_ibuf_is_the_bring_up_value(self):
        # Ear-verified during bring-up; a latency profile must not move it.
        for latency in (None, "buffered"):
            device = self.board.audio_out(latency=latency)
            device.open()
            self.assertEqual(20000, device.transport.i2s.options["ibuf"])
            device.close()

    def test_low_latency_shortens_the_i2s_ring_buffer(self):
        device = self.board.audio_out(latency="low")
        device.open()
        # 100ms at 24kHz mono 16-bit.
        self.assertEqual(4800, device.transport.i2s.options["ibuf"])
        device.close()

        capture = self.board.audio_in(latency="low")
        capture.open()
        self.assertEqual(4800, capture.i2s.options["ibuf"])
        capture.close()

    def test_explicit_queue_ms_wins_but_cannot_starve_the_dma(self):
        device = self.board.audio_out(queue_ms=200)
        device.open()
        self.assertEqual(9600, device.transport.i2s.options["ibuf"])
        device.close()

        device = self.board.audio_out(queue_ms=1)
        device.open()
        self.assertEqual(self.board._MIN_IBUF, device.transport.i2s.options["ibuf"])
        device.close()

    def test_unusable_keywords_raise_instead_of_being_ignored(self):
        with self.assertRaises(ValueError):
            self.board.audio_out(latency="fast")
        # No software coalescing stage on this board, so silently accepting it
        # would promise latency tuning that does not happen.
        with self.assertRaises(TypeError):
            self.board.audio_out(coalesce_ms=20)

    def test_input_uses_es7210_codec_and_gain(self):
        capture = self.board.audio_in()
        capture.set_gain(35)
        capture.open()
        self.assertEqual(capture.codec.gain, 35)
        self.assertEqual(FakePWM.instances[-1].freq(), 24000 * 512)
        self.assertEqual(capture.i2s.options["sck"].number, 12)
        self.assertEqual(capture.i2s.options["ws"].number, 10)
        self.assertEqual(capture.i2s.options["sd"].number, 11)
        capture.close()
        self.assertFalse(capture.codec.enabled)


if __name__ == "__main__":
    unittest.main()
