"""Recording while playing: ``audiodev.pump.PumpPCMInput`` over the pump's RX.

On a board whose speaker and microphone share one I2S port, ``machine.I2S``
can only have one of them. The pump's driver opens the port as a TX/RX pair
and lets Python read the RX half; these tests hold ``PumpPCMInput`` and
``BusioDriver`` to that contract against a stand-in driver.
"""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401
from _duplex_fake import FakeDuplexDriver  # noqa: E402

from audiodev import AudioFormat, AudioSession, I2SWire  # noqa: E402
from audiodev import pump as pump_mod  # noqa: E402

FMT = AudioFormat(24000, 1, 16)
WIRE = I2SWire(0, sck=12, ws=10, sd=9, mck=13, mck_fs=256, sd_in=11)


class DriverFixture(unittest.TestCase):
    def setUp(self):
        self._saved = (pump_mod._driver, pump_mod._driver_looked)
        self.driver = FakeDuplexDriver()
        pump_mod._driver = self.driver
        pump_mod._driver_looked = True
        self.addCleanup(self._restore)

    def _restore(self):
        pump_mod._driver, pump_mod._driver_looked = self._saved


class TheFirmwareSaysWhetherItCanRecordWhilePlaying(DriverFixture):
    def test_a_driver_with_rx_open_is_duplex(self):
        self.assertTrue(pump_mod.duplex())

    def test_a_driver_without_it_is_not(self):
        class Old:
            def i2s_start(self, *args, **kwargs):
                pass

        pump_mod._driver = Old()
        self.assertFalse(pump_mod.duplex())
        self.assertFalse(pump_mod.clock_running())

    def test_no_driver_at_all_is_not(self):
        pump_mod._driver = None
        self.assertFalse(pump_mod.duplex())
        self.assertFalse(pump_mod.clock_running())

    def test_clock_running_follows_the_channel(self):
        self.assertFalse(pump_mod.clock_running())
        self.driver.output_opens()
        self.assertTrue(pump_mod.clock_running())
        self.driver.output_closes()
        self.assertFalse(pump_mod.clock_running())


class ReadingTheRxHalf(DriverFixture):
    def make(self, **kwargs):
        mic = pump_mod.PumpPCMInput(FMT, wire=WIRE, **kwargs)
        self.addCleanup(mic.close)
        return mic

    def test_open_names_the_speaker_pin_and_the_microphone_pin(self):
        """The pair is allocated together, so a recorder that never plays
        still names the speaker's pin: an output arriving later has to find
        its half already wired."""
        mic = self.make(ring_bytes=9600)
        mic.open()
        self.assertEqual(
            dict(port=0, bclk=12, ws=10, dout=9, din=11, rate=24000, mclk=13,
                 mclk_fs=256, ring=9600, take=2),
            self.driver.opened_with)

    def test_readinto_fills_the_whole_buffer_across_blocks(self):
        mic = self.make()
        mic.open()
        delivered = bytes(range(200)) * 4
        # The ring has some of it now; the rest arrives while readinto waits,
        # as DMA blocks do every 5 ms.
        self.driver.deliver(delivered[:300])
        later = [delivered[300:500], delivered[500:]]
        real_read = self.driver.rx_read

        def read(buf):
            n = real_read(buf)
            if n == 0 and later:
                self.driver.deliver(later.pop(0))
            return n

        self.driver.rx_read = read
        buf = bytearray(len(delivered))
        self.assertEqual(len(delivered), mic.readinto(buf))
        self.assertEqual(delivered, bytes(buf))

    def test_a_channel_that_never_clocks_is_an_error_not_a_hang(self):
        mic = self.make(timeout_ms=20)
        mic.open()
        with self.assertRaises(OSError) as ctx:
            mic.readinto(bytearray(64))
        self.assertIn("nothing", str(ctx.exception))

    def test_the_channel_opens_before_the_codec_is_brought_up(self):
        """The codec's setup must run with the channel's MCLK on its pin; a
        board that bootstrapped MCLK with PWM while the channel ran would
        take the pin from it."""
        order = []

        def codec():
            order.append("codec, holds=%d" % self.driver.holds)
            return object()

        mic = self.make(session=AudioSession(codec_factory=codec))
        mic.open()
        self.assertEqual(["codec, holds=2"], order)

    def test_a_codec_that_fails_gives_the_channel_back(self):
        def codec():
            raise OSError("no ES7210 on the bus")

        mic = self.make(session=AudioSession(codec_factory=codec))
        with self.assertRaises(OSError):
            mic.open()
        self.assertEqual(["rx_open", "rx_close"], self.driver.calls)
        self.assertFalse(mic.is_open)
        self.assertIsNone(self.driver.live)

    def test_close_gives_the_channel_back_once(self):
        mic = self.make()
        mic.open()
        mic.close()
        mic.close()
        self.assertEqual(["rx_open", "rx_close"], self.driver.calls)

    def test_before_open_can_refuse_and_nothing_is_opened(self):
        def refuse():
            raise OSError("I2S(0) is in use by speaker")

        mic = self.make(before_open=refuse)
        with self.assertRaises(OSError):
            mic.open()
        self.assertEqual([], self.driver.calls)

    def test_a_recorder_joins_the_output_at_its_rate(self):
        self.driver.output_opens(rate=24000)
        mic = self.make()
        mic.open()
        self.assertEqual(3, self.driver.holds)
        mic.close()
        self.assertEqual(1, self.driver.holds,
                         "closing the recorder took the speaker's channel")

    def test_a_recorder_at_another_rate_is_refused_by_name(self):
        self.driver.output_opens(rate=44100)
        mic = self.make()
        with self.assertRaises(ValueError) as ctx:
            mic.open()
        self.assertIn("44100", str(ctx.exception))
        self.assertFalse(mic.is_open)

    def test_stats_report_what_the_driver_counted(self):
        mic = self.make()
        mic.open()
        self.driver.deliver(bytes(10))
        self.driver.dropped = 3
        self.assertEqual({"captured": 5, "dropped": 3, "waiting": 10},
                         mic.stats())

    def test_take(self):
        self.assertEqual(0, self.make(take="left")._take)
        self.assertEqual(1, self.make(take="right")._take)
        self.assertEqual(2, self.make()._take)
        stereo = pump_mod.PumpPCMInput(AudioFormat(24000, 2, 16), wire=WIRE)
        self.assertEqual(3, stereo._take)
        with self.assertRaises(ValueError):
            self.make(take="both")

    def test_a_wire_without_a_microphone_pin_is_refused(self):
        with self.assertRaises(ValueError):
            pump_mod.PumpPCMInput(FMT, wire=I2SWire(0, sck=12, ws=10, sd=9))

    def test_only_signed_16_bit(self):
        with self.assertRaises(ValueError):
            pump_mod.PumpPCMInput(AudioFormat(24000, 1, 32), wire=WIRE)


class FakeI2SOut:
    built = []

    def __init__(self, *pins, **kwargs):
        self.pins = pins
        self.kwargs = kwargs
        FakeI2SOut.built.append(self)


class TheOutputOpensThePairWhenTheBoardPublishesAMicPin(DriverFixture):
    def setUp(self):
        super().setUp()
        self._saved_busio = (pump_mod._busio, pump_mod._busio_looked)
        pump_mod._busio = type("Busio", (), {"I2SOut": FakeI2SOut})()
        pump_mod._busio_looked = True
        FakeI2SOut.built = []
        self.addCleanup(self._put_back)

    def _put_back(self):
        pump_mod._busio, pump_mod._busio_looked = self._saved_busio

    def test_data_in_reaches_the_constructor(self):
        pump_mod.BusioDriver(WIRE, FMT).open()
        self.assertEqual(11, FakeI2SOut.built[-1].kwargs.get("data_in"))

    def test_not_on_firmware_that_cannot_read_rx(self):
        class Old:
            def i2s_start(self, *args, **kwargs):
                pass

        pump_mod._driver = Old()
        pump_mod.BusioDriver(WIRE, FMT).open()
        self.assertNotIn("data_in", FakeI2SOut.built[-1].kwargs)

    def test_not_for_a_wire_without_a_microphone(self):
        pump_mod.BusioDriver(I2SWire(0, sck=12, ws=10, sd=9), FMT).open()
        self.assertNotIn("data_in", FakeI2SOut.built[-1].kwargs)


if __name__ == "__main__":
    unittest.main()
