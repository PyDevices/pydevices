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
DEV_KIT = ROOT / "board_configs" / "nodisplay" / "esp32-p4-wifi6-dev-kit"


class FakeI2C:
    instances = []

    def __init__(self, port=None, scl=None, sda=None, freq=None):
        self.port = port
        self.scl = scl
        self.sda = sda
        self.freq = freq
        self.registers = {}
        self.instances.append(self)

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
    constructed = []

    def __init__(self, number, **kwargs):
        self.number = number
        self.options = kwargs
        self.closed = False
        FakeI2S.constructed.append(self)

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


class P4BoardFixture(unittest.TestCase):
    """Loads the panel's board_peripherals against fake machine and codecs."""

    BOARD_DIR = BOARD

    @classmethod
    def setUpClass(cls):
        cls.saved_modules = {
            name: sys.modules.get(name) for name in ("audiocore", "board_config", "boarddev", "machine")
        }
        sys.modules["audiocore"] = types.SimpleNamespace()
        cls.i2c = FakeI2C()
        sys.modules["board_config"] = types.SimpleNamespace(i2c=cls.i2c)
        sys.modules["boarddev"] = types.SimpleNamespace(bind_lazy=lambda *args: None)
        sys.modules["machine"] = types.SimpleNamespace(
            I2S=FakeI2S, Pin=FakePin, PWM=FakePWM, I2C=FakeI2C
        )
        spec = importlib.util.spec_from_file_location(
            "p4_board_peripherals_" + cls.BOARD_DIR.name, cls.BOARD_DIR / "board_peripherals.py"
        )
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
        sys.modules["board_config"] = types.SimpleNamespace(i2c=self.i2c)
        self.i2c.registers.clear()
        FakePin.instances.clear()
        FakePWM.instances.clear()
        FakeI2C.instances.clear()
        # Class-level, so it accumulates across tests and leaks into whatever
        # runs next in the same process unless it is cleared here.
        FakeI2S.constructed.clear()
        self.board._pa = None
        self.board._mclk = None
        self.board._mclk_rate = self.board._RATE
        self.board._i2c_own = None


class ESP32P4AudioTests(P4BoardFixture):
    def test_output_format_is_24khz_mono_pcm(self):
        from audiodev import AudioFormat

        output = self.board.audio_out()
        self.assertEqual(output.format, AudioFormat(24000, 1, 16))

    def test_capability_is_discoverable_without_opening(self):
        """A caller asks what the board takes; it does not open to find out.

        ``channels`` is what the WIRE opens, ``native_channels`` is what
        reaches a speaker. They differ here, and that is the point: the
        ES8311 clocks two slots into one speaker, so stereo content needs no
        mixdown. The previous shape had a single ``max_channels = 1`` beside
        an ``audio_out`` that accepted 2 -- it could not express this board.
        """
        FakeI2S.constructed.clear()
        cap = self.board.pcm_out.capability
        self.assertEqual((1, 2), cap.channels)
        self.assertEqual(1, cap.native_channels)
        self.assertIs(cap, self.board.AUDIO_OUT)
        self.assertEqual([], FakeI2S.constructed)

    def test_capability_publishes_the_wire_for_a_c_pump(self):
        """usbif's C pump opens I2S itself and wants only the pin numbers."""
        FakeI2S.constructed.clear()
        wire = self.board.AUDIO_OUT.wire
        self.assertEqual(12, wire.sck)
        self.assertEqual(10, wire.ws)
        self.assertEqual(9, wire.sd)
        self.assertEqual(13, wire.mck)
        self.assertEqual([], FakeI2S.constructed)

    def test_input_refuses_stereo_that_output_accepts(self):
        """Not a contradiction any more: the capabilities differ and say so.

        Before, ``_MAX_CHANNELS = 1`` sat beside an ``audio_out`` accepting 2
        while ``audio_in`` raised on the same request, from one constant.
        """
        from audiodev import AudioFormat

        self.board.pcm_out(AudioFormat(44100, 2, 16))
        with self.assertRaises(ValueError):
            self.board.pcm_in(AudioFormat(44100, 2, 16))

    def test_output_has_codec_controls_and_amplifier_lifecycle(self):
        output = self.board.audio_out()
        self.assertIsNotNone(output.codec)
        self.assertEqual(output.codec.mclk_multiplier, 256)
        self.assertEqual(self.i2c.registers[0x02], 0x00)
        self.assertEqual(self.i2c.registers[0x06], 7)
        output.set_volume(42)
        output.open()
        self.assertEqual(output.codec.dac_volume, 42)
        self.assertFalse(output.codec.dac_muted)
        self.assertEqual(FakePin.instances[53].state, 1)
        self.assertTrue(FakePWM.instances[-1].closed)
        self.assertEqual(output.transport.i2s.options["mck"].number, 13)
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

    def test_low_latency_shortens_the_input_ring_but_not_the_output_ring(self):
        # This asserted 4800 for BOTH directions until 5f52477. On the output
        # side that is retired, and deliberately: the ring is a physical
        # ceiling, not the latency governor. I2SPCMOutput now reports
        # queued_size() over the DMA's exactly-realtime drain, so the pump's
        # lookahead governs note-to-sound latency and a full-size ring only
        # guarantees writes never block. Shrinking it for latency="low" made
        # every service call block against the DMA (88-160 ms per call) and
        # wedged the device outright, because the ring fell below the pump's
        # own queue target. latency="low" now means a 10 ms chunk with a
        # 4-chunk (~50 ms) schedule, against a measured 28 ms worst stall.
        device = self.board.audio_out(latency="low")
        device.open()
        self.assertEqual(20000, device.transport.i2s.options["ibuf"])
        device.close()

        # The input side is unchanged and still shortens: capture has no pump
        # to govern latency, so its ring IS the latency. Kept rather than
        # dropped with the output assertion -- 5f52477 touched audio_out only,
        # and deleting this half would retire a contract nothing changed.
        capture = self.board.pcm_in(latency="low")
        capture.open()
        self.assertEqual(4800, capture.i2s.options["ibuf"])  # 100ms @ 24kHz mono 16-bit
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

    def test_microphone_is_refused_while_the_speaker_holds_i2s0(self):
        """pydevices#23: a second I2S(0) used to take the first one over silently.

        On esp32, constructing I2S(0) again deinitialises the live instance,
        so opening the microphone stopped the speaker with no error. The
        board refuses the second direction instead, and opens nothing.
        """
        output = self.board.pcm_out()
        output.open()
        self.assertEqual(1, len(FakeI2S.constructed))
        capture = self.board.pcm_in()
        with self.assertRaises(OSError) as ctx:
            capture.open()
        self.assertIn("I2S(0)", str(ctx.exception))
        self.assertIn("speaker", str(ctx.exception))
        self.assertEqual(1, len(FakeI2S.constructed))
        self.assertFalse(capture.is_open)
        self.assertEqual([], self.board._INPUT_SESSION._owners)
        output.close()
        capture.open()
        self.assertEqual(FakeI2S.RX, capture.i2s.options["mode"])
        capture.close()

    def test_speaker_is_refused_while_the_microphone_holds_i2s0(self):
        capture = self.board.pcm_in()
        capture.open()
        output = self.board.pcm_out()
        with self.assertRaises(OSError) as ctx:
            output.open()
        self.assertIn("microphone", str(ctx.exception))
        self.assertEqual(1, len(FakeI2S.constructed))
        self.assertEqual([], self.board._SESSION._owners)
        capture.close()
        output.open()
        output.close()

    def test_input_uses_es7210_codec_and_gain(self):
        capture = self.board.pcm_in()
        capture.set_gain(35)
        capture.open()
        self.assertEqual(capture.codec.gain, 35)
        self.assertTrue(FakePWM.instances[-1].closed)
        self.assertEqual(capture.i2s.options["mck"].number, 13)
        self.assertEqual(capture.i2s.options["sck"].number, 12)
        self.assertEqual(capture.i2s.options["ws"].number, 10)
        self.assertEqual(capture.i2s.options["sd"].number, 11)
        capture.close()
        self.assertFalse(capture.codec.enabled)

    def test_factory_opens_app_chosen_rate_and_retunes_mclk(self):
        from audiodev import AudioFormat

        fmt = AudioFormat(44100, 1, 16)
        output = self.board.audio_out(fmt)
        self.assertEqual(output.format, fmt)
        output.open()
        self.assertEqual(output.transport.i2s.options["rate"], 44100)
        self.assertEqual(output.transport.i2s.options["format"], FakeI2S.MONO)
        self.assertTrue(FakePWM.instances[-1].closed)
        self.assertEqual(output.transport.i2s.options["mck"].number, 13)
        output.close()

    def test_stereo_opens_i2s_stereo_slots(self):
        from audiodev import AudioFormat

        fmt = AudioFormat(44100, 2, 16)
        output = self.board.audio_out(fmt)
        self.assertEqual(output.format, fmt)
        output.open()
        self.assertEqual(output.transport.i2s.options["rate"], 44100)
        self.assertEqual(output.transport.i2s.options["format"], FakeI2S.STEREO)
        self.assertTrue(FakePWM.instances[-1].closed)
        self.assertEqual(output.transport.i2s.options["mck"].number, 13)
        output.close()

    def test_non_16bit_still_raises(self):
        from audiodev import AudioFormat

        with self.assertRaises(ValueError):
            self.board.audio_out(AudioFormat(44100, 1, 32))

    def test_headless_factory_opens_panel_i2c_without_board_config(self):
        from audiodev import AudioFormat

        saved = sys.modules.pop("board_config")
        try:
            output = self.board.audio_out(AudioFormat(44100, 1, 16))
            output.open()
            self.assertEqual(1, len(FakeI2C.instances))
            bus = FakeI2C.instances[0]
            self.assertEqual(bus.port, 1)
            self.assertEqual(bus.scl.number, 8)
            self.assertEqual(bus.sda.number, 7)
            output.close()
        finally:
            sys.modules["board_config"] = saved


class PanelRecordsWhilePlaying(P4BoardFixture):
    """With the audio pump, pcm_in reads the RX half of the pump's channel.

    The ES8311 and the ES7210 share I2S0's clocks, so machine.I2S can have one
    of them at a time (pydevices#23). The pump's driver opens the port as a
    TX/RX pair instead; the board publishes the microphone's pin on its wire
    and builds a PumpPCMInput, so audio_out plays while pcm_in records.
    """

    def setUp(self):
        from _duplex_fake import FakeDuplexDriver
        from audiodev import pump

        self.pump = pump
        self._saved_driver = (pump._driver, pump._driver_looked)
        self.driver = FakeDuplexDriver()
        pump._driver = self.driver
        pump._driver_looked = True

    def tearDown(self):
        self.pump._driver, self.pump._driver_looked = self._saved_driver
        super().tearDown()

    def test_the_wire_publishes_the_microphone_pin(self):
        self.assertEqual(11, self.board.AUDIO_OUT.wire.sd_in)

    def test_pcm_in_reads_the_pump_channel(self):
        capture = self.board.pcm_in()
        self.assertIsInstance(capture, self.pump.PumpPCMInput)
        capture.set_gain(35)
        capture.open()
        opened = self.driver.opened_with
        self.assertEqual((0, 12, 10, 9, 11, 24000, 13, 256),
                         (opened["port"], opened["bclk"], opened["ws"],
                          opened["dout"], opened["din"], opened["rate"],
                          opened["mclk"], opened["mclk_fs"]))
        self.assertEqual(2, opened["take"], "the two microphones are averaged")
        self.assertEqual(20000, opened["ring"])
        self.assertEqual(35, capture.codec.gain)
        self.assertEqual([], FakeI2S.constructed, "machine.I2S was opened")
        capture.close()
        self.assertEqual(["rx_open", "rx_close"], self.driver.calls)
        self.assertFalse(capture.codec.enabled)

    def test_no_pwm_clock_while_the_channel_drives_gpio13(self):
        """A PWM started on GPIO13 while the channel runs takes the pin from
        it, and both codecs lose their clock mid-stream."""
        self.driver.output_opens()
        capture = self.board.pcm_in()
        capture.open()
        self.board.audio_power(True)
        self.assertEqual([], FakePWM.instances)
        capture.close()

    def test_a_running_pwm_is_released_when_the_channel_is_up(self):
        self.board._ensure_mclk()
        pwm = FakePWM.instances[-1]
        self.driver.output_opens()
        self.board._ensure_mclk()
        self.assertTrue(pwm.closed)
        self.assertIsNone(self.board._mclk)

    def test_pcm_out_still_refuses_alongside_a_recording(self):
        """pcm_out is machine.I2S whatever the firmware."""
        capture = self.board.pcm_in()
        capture.open()
        output = self.board.pcm_out()
        with self.assertRaises(OSError) as ctx:
            output.open()
        self.assertIn("audio_out", str(ctx.exception))
        self.assertEqual([], FakeI2S.constructed)
        capture.close()

    def test_a_recording_is_refused_while_pcm_out_holds_the_port(self):
        output = self.board.pcm_out()
        output.open()
        capture = self.board.pcm_in()
        with self.assertRaises(OSError):
            capture.open()
        self.assertEqual([], self.driver.calls, "the channel was opened anyway")
        output.close()


class DevKitRecordsWhilePlaying(P4BoardFixture):
    """The DEV-KIT's microphone is the ES8311's own ADC on the same port."""

    BOARD_DIR = DEV_KIT

    def setUp(self):
        from _duplex_fake import FakeDuplexDriver
        from audiodev import pump

        self.pump = pump
        self._saved_driver = (pump._driver, pump._driver_looked)
        self.driver = FakeDuplexDriver()
        pump._driver = self.driver
        pump._driver_looked = True

    def tearDown(self):
        self.pump._driver, self.pump._driver_looked = self._saved_driver
        self.board._es8311 = None
        super().tearDown()

    def test_pcm_in_reads_the_pump_channel_one_slot(self):
        self.assertEqual(11, self.board.AUDIO_OUT.wire.sd_in)
        capture = self.board.pcm_in()
        self.assertIsInstance(capture, self.pump.PumpPCMInput)
        capture.open()
        opened = self.driver.opened_with
        self.assertEqual((9, 11, 0), (opened["dout"], opened["din"], opened["take"]))
        self.assertEqual([], FakeI2S.constructed)
        self.assertEqual([], FakePWM.instances, "a PWM clock started on the running channel")
        capture.close()
        self.assertEqual(["rx_open", "rx_close"], self.driver.calls)

    def test_pcm_out_still_refuses_alongside_a_recording(self):
        capture = self.board.pcm_in()
        capture.open()
        with self.assertRaises(OSError):
            self.board.pcm_out().open()
        capture.close()


if __name__ == "__main__":
    unittest.main()
