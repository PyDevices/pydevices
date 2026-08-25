"""Host simulation of the M5Stack Tab5 board audio wiring.

Both panel variants ship the same audio hardware and the same role code, so
every test runs against both board configs; they must not drift apart.
"""

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
BOARDS = ("m5stack_tab5_st7123", "m5stack_tab5_ili9881c")


class FakeI2C:
    """Registers are shared per address, enough for the codec and IO expander."""

    def __init__(self):
        self.registers = {}

    def writeto_mem(self, address, register, data):
        self.registers[(address, register)] = data[0]

    def readfrom_mem(self, address, register, length):
        return bytes([self.registers.get((address, register), 0)] * length)

    def readfrom_mem_into(self, address, register, target):
        target[0] = self.registers.get((address, register), 0)


class FakePin:
    OUT = 1

    def __init__(self, number, mode=None, value=None):
        self.number = number
        self.state = value

    def value(self, value=None):
        if value is not None:
            self.state = value
        return self.state


class FakeI2C_Type:
    """Stand-in for ``machine.I2C``, which drivers import only to annotate."""


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


def load_board(name):
    saved = {key: sys.modules.get(key) for key in ("audiocore", "board_config", "boarddev", "machine")}
    i2c = FakeI2C()
    sys.modules["board_config"] = types.SimpleNamespace(i2c=i2c)
    sys.modules["boarddev"] = types.SimpleNamespace(bind_lazy=lambda *args: None)
    sys.modules["machine"] = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin, I2C=FakeI2C_Type)
    sys.modules["audiocore"] = types.SimpleNamespace()
    try:
        path = ROOT / "board_configs" / "fbdisplay" / name / "board_peripherals.py"
        spec = importlib.util.spec_from_file_location("tab5_%s" % name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, i2c
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


class Tab5AudioTests(unittest.TestCase):
    def boards(self):
        """Yield each variant, with ``machine`` faked for the duration."""
        for name in BOARDS:
            module, i2c = load_board(name)
            saved = {key: sys.modules.get(key) for key in ("audiocore", "board_config", "machine")}
            sys.modules["board_config"] = types.SimpleNamespace(i2c=i2c)
            sys.modules["machine"] = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin, I2C=FakeI2C_Type)
            sys.modules["audiocore"] = types.SimpleNamespace()
            try:
                module._SESSION._owners[:] = []
                yield name, module
            finally:
                module._SESSION._owners[:] = []
                for key, value in saved.items():
                    if value is None:
                        sys.modules.pop(key, None)
                    else:
                        sys.modules[key] = value

    def ibuf(self, device):
        # audio_out() now returns an AudioOut wrapping the I2SPCMOutput
        # transport, whose raw i2s stream lives on .transport; audio_in()
        # still returns the raw I2SPCMInput directly (capture is unchanged).
        device.open()
        try:
            transport = getattr(device, "transport", device)
            return transport.i2s.options["ibuf"]
        finally:
            device.close()

    def test_output_is_16khz_stereo_pcm(self):
        from audiodev import AudioFormat

        for name, board in self.boards():
            with self.subTest(board=name):
                self.assertEqual(AudioFormat(16000, 2, 16), board.audio_out().format)

    def test_default_ibuf_is_the_bring_up_value(self):
        for name, board in self.boards():
            with self.subTest(board=name):
                self.assertEqual(20000, self.ibuf(board.audio_out()))
                self.assertEqual(20000, self.ibuf(board.audio_out(latency="buffered")))

    def test_low_latency_shortens_the_i2s_ring_buffer(self):
        # 100ms at 16kHz stereo 16-bit.
        for name, board in self.boards():
            with self.subTest(board=name):
                self.assertEqual(6400, self.ibuf(board.audio_out(latency="low")))
                self.assertEqual(6400, self.ibuf(board.audio_in(latency="low")))

    def test_explicit_queue_ms_wins_but_cannot_starve_the_dma(self):
        for name, board in self.boards():
            with self.subTest(board=name):
                self.assertEqual(12800, self.ibuf(board.audio_out(queue_ms=200)))
                self.assertEqual(board._MIN_IBUF, self.ibuf(board.audio_out(queue_ms=1)))

    def test_unusable_keywords_raise_instead_of_being_ignored(self):
        for name, board in self.boards():
            with self.subTest(board=name):
                with self.assertRaises(ValueError):
                    board.audio_out(latency="fast")
                with self.assertRaises(TypeError):
                    board.audio_out(coalesce_ms=20)

    def test_amplifier_follows_the_device_lifecycle(self):
        for name, board in self.boards():
            with self.subTest(board=name):
                # Imported inside the loop: pi4ioe5v needs the faked ``machine``,
                # which only exists while the generator is suspended here.
                from pi4ioe5v import TAB5_PI4IOE1_ADDR, TAB5_SPK_EN_BIT, _REG_OUT_SET

                i2c = sys.modules["board_config"].i2c
                register = (TAB5_PI4IOE1_ADDR, _REG_OUT_SET)
                device = board.audio_out()
                device.open()
                self.assertTrue(i2c.registers[register] & (1 << TAB5_SPK_EN_BIT))
                device.close()
                self.assertFalse(i2c.registers[register] & (1 << TAB5_SPK_EN_BIT))


if __name__ == "__main__":
    unittest.main()
