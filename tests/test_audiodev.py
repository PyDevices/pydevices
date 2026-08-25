import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import (  # noqa: E402
    AudioFormat,
    AudioSession,
    PCMInput,
    PCMOutput,
    ToneOutput,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput  # noqa: E402
from audiodev.pwm_tone import PWMToneOutput  # noqa: E402


class FakePCMOutput(PCMOutput):
    def __init__(self, fmt, *, partial=None, **kwargs):
        super().__init__(fmt, **kwargs)
        self.data = bytearray()
        self.partial = partial
        self.open_count = 0
        self.close_count = 0
        self.drained = False

    def _open(self):
        self.open_count += 1

    def _write(self, buf):
        count = len(buf) if self.partial is None else min(self.partial, len(buf))
        self.data.extend(buf[:count])
        return count

    async def _awrite(self, buf):
        await asyncio.sleep(0)
        return self._write(buf)

    def _drain(self):
        self.drained = True

    async def _adrain(self):
        await asyncio.sleep(0)
        self.drained = True

    def _close(self):
        self.close_count += 1


class FakePCMInput(PCMInput):
    def __init__(self, fmt, data, **kwargs):
        super().__init__(fmt, **kwargs)
        self._source = bytes(data)
        self.closed = False

    def _readinto(self, buf):
        count = min(len(buf), len(self._source))
        buf[:count] = self._source[:count]
        return count

    async def _areadinto(self, buf):
        await asyncio.sleep(0)
        return self._readinto(buf)

    def _close(self):
        self.closed = True


class FakeTone:
    def __init__(self):
        self.frequency = None
        self.level = None
        self.stopped = False

    def play(self, frequency, level):
        self.frequency = frequency
        self.level = level
        self.stopped = False

    def stop(self):
        self.stopped = True

    def close(self):
        pass


class AudioFormatTests(unittest.TestCase):
    def test_format(self):
        fmt = AudioFormat(16000, 2, 16)
        self.assertEqual(fmt.frame_size, 4)
        self.assertEqual(fmt, AudioFormat(16000, 2, 16))

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            AudioFormat(0, 2, 16)
        with self.assertRaises(ValueError):
            AudioFormat(16000, 2, 24)


class PCMOutputTests(unittest.TestCase):
    def setUp(self):
        self.fmt = AudioFormat(16000, 1, 16)

    def test_partial_writes_and_lifecycle(self):
        output = FakePCMOutput(self.fmt, partial=2)
        self.assertEqual(output.write(b"\x01\x00\x02\x00"), 4)
        self.assertEqual(output.data, b"\x01\x00\x02\x00")
        output.open()
        self.assertEqual(output.open_count, 1)
        output.close()
        output.close()
        self.assertEqual(output.close_count, 1)

    def test_software_volume_and_mute(self):
        output = FakePCMOutput(self.fmt)
        output.set_volume(50)
        output.write((1000).to_bytes(2, "little", signed=True))
        self.assertEqual(int.from_bytes(output.data, "little", signed=True), 500)
        output.data.clear()
        output.mute()
        output.write((1000).to_bytes(2, "little", signed=True))
        self.assertEqual(output.data, b"\0\0")
        self.assertEqual(output.volume, 50)

    def test_hardware_controls(self):
        calls = []
        output = FakePCMOutput(
            self.fmt,
            set_hardware_volume=lambda value: calls.append(("volume", value)),
            set_hardware_mute=lambda value: calls.append(("mute", value)),
        )
        output.set_volume(30)
        output.open()
        output.mute(True)
        self.assertIn(("volume", 30), calls)
        self.assertIn(("mute", True), calls)

    def test_frame_validation(self):
        with self.assertRaises(ValueError):
            FakePCMOutput(self.fmt).write(b"x")

    def test_queue_helpers_exist_on_the_device(self):
        output = FakePCMOutput(self.fmt)
        self.assertEqual(output.service(), None)
        self.assertEqual(output.queued_size(), 0)
        self.assertFalse(output.is_active())
        self.assertEqual(output.clear(), None)

    def test_async_output(self):
        async def run():
            output = FakePCMOutput(self.fmt, partial=1)
            self.assertEqual(await output.awrite(b"\x01\x00"), 2)
            self.assertEqual(output.data, b"\x01\x00")
            await output.adrain()
            self.assertTrue(output.drained)

        asyncio.run(run())


class PCMInputTests(unittest.TestCase):
    def setUp(self):
        self.fmt = AudioFormat(16000, 1, 16)

    def test_capture_gain_and_mute(self):
        source = (1000).to_bytes(2, "little", signed=True)
        capture = FakePCMInput(self.fmt, source)
        capture.set_gain(50)
        buf = bytearray(2)
        self.assertEqual(capture.readinto(buf), 2)
        self.assertEqual(int.from_bytes(buf, "little", signed=True), 500)
        capture.mute()
        capture.readinto(buf)
        self.assertEqual(buf, b"\0\0")

    def test_async_capture(self):
        async def run():
            capture = FakePCMInput(self.fmt, b"\x01\0")
            buf = bytearray(2)
            self.assertEqual(await capture.areadinto(buf), 2)
            self.assertEqual(buf, b"\x01\0")

        asyncio.run(run())


class SessionTests(unittest.TestCase):
    def test_half_duplex_conflict_and_shared_codec(self):
        codec = object()
        session = AudioSession(lambda: codec, duplex=False)
        output = FakePCMOutput(AudioFormat(16000, 1, 16), session=session)
        capture = FakePCMInput(AudioFormat(16000, 1, 16), b"\0\0", session=session)
        output.open()
        self.assertIs(output.codec, codec)
        with self.assertRaises(OSError):
            capture.open()
        output.close()
        capture.open()
        self.assertIs(capture.codec, codec)


class FakeI2S:
    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data):
        self.written.extend(data)
        return len(data)

    def readinto(self, buf):
        buf[:] = b"\x01\x00" * (len(buf) // 2)
        return len(buf)

    def deinit(self):
        self.closed = True


class I2SAdapterTests(unittest.TestCase):
    def test_output_and_input_wrap_machine_i2s(self):
        fmt = AudioFormat(16000, 1, 16)
        i2s = FakeI2S()
        out = I2SPCMOutput(i2s, fmt)
        self.assertIsInstance(out, PCMOutput)
        self.assertEqual(out.write(b"\x02\x00\x03\x00"), 4)
        self.assertEqual(bytes(i2s.written), b"\x02\x00\x03\x00")
        self.assertEqual(out.service(), None)
        self.assertEqual(out.queued_size(), 0)
        out.close()
        self.assertTrue(i2s.closed)

        capture = FakeI2S()
        inp = I2SPCMInput(capture, fmt)
        self.assertIsInstance(inp, PCMInput)
        buf = bytearray(2)
        self.assertEqual(inp.readinto(buf), 2)
        inp.close()
        self.assertTrue(capture.closed)


class FakeSample:
    """Minimal audiosample-shaped fake: a fixed list of PCM chunks, replayable
    via reset(). Stands in for a synthio.Synthesizer/audiomixer.Mixer/
    audiocore.RawSample for AudioOut's own logic tests -- see
    tests/test_audio_playback_golden.py for the real-usermod version."""

    def __init__(self, chunks, *, bits_per_sample=16, channel_count=1):
        self.bits_per_sample = bits_per_sample
        self.channel_count = channel_count
        self._chunks = [bytes(c) for c in chunks]
        self._pos = 0

    def reset(self):
        self._pos = 0

    def next_chunk(self):
        if self._pos >= len(self._chunks):
            return None
        chunk = self._chunks[self._pos]
        self._pos += 1
        return chunk


class FakeAudiocore:
    """Stands in for the ``audiocore`` usermod. Injected as ``sys.modules
    ["audiocore"]`` so AudioOut's ``import audiocore`` (deferred to
    play()/service(), per its module docstring) finds this instead of
    needing the real usermod."""

    GET_BUFFER_DONE = 0
    GET_BUFFER_MORE_DATA = 1
    GET_BUFFER_ERROR = 2

    def __init__(self):
        self.reset_calls = 0

    def get_buffer(self, sample):
        chunk = sample.next_chunk()
        if chunk is None:
            return (self.GET_BUFFER_DONE, b"")
        more = sample._pos < len(sample._chunks)
        return (self.GET_BUFFER_MORE_DATA if more else self.GET_BUFFER_DONE, chunk)

    def reset_buffer(self, sample):
        sample.reset()
        self.reset_calls += 1


class _FakeClock:
    """Manually-advanced ticks_ms()/ticks_diff(), so tests control AudioOut's
    lookahead schedule instead of depending on real wall-clock timing."""

    def __init__(self):
        self.now = 0

    def ms(self):
        return self.now

    def diff(self, a, b):
        return a - b

    def advance(self, ms):
        self.now += ms


class AudioOutTests(unittest.TestCase):
    def setUp(self):
        from audiodev import sample_out

        self.sample_out = sample_out
        self.fake_audiocore = FakeAudiocore()
        self._orig_audiocore = sys.modules.get("audiocore")
        sys.modules["audiocore"] = self.fake_audiocore
        self.clock = _FakeClock()
        self._orig_ticks_ms = sample_out.ticks_ms
        self._orig_ticks_diff = sample_out.ticks_diff
        sample_out.ticks_ms = self.clock.ms
        sample_out.ticks_diff = self.clock.diff
        self.fmt = AudioFormat(8000, 1, 16)
        self.transport = FakePCMOutput(self.fmt)

    def tearDown(self):
        if self._orig_audiocore is None:
            sys.modules.pop("audiocore", None)
        else:
            sys.modules["audiocore"] = self._orig_audiocore
        self.sample_out.ticks_ms = self._orig_ticks_ms
        self.sample_out.ticks_diff = self._orig_ticks_diff

    def test_play_pulls_immediately(self):
        # chunk_ms=40, lookahead_chunks=2 @ 8kHz -> 640 frames = 1280 bytes
        # wanted on the very first play(); each fake chunk is 200 bytes, so
        # several are needed and the sample isn't drained by one call.
        chunks = [bytes(200) for _ in range(20)]
        sample = FakeSample(chunks)
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40, lookahead_chunks=2)
        out.play(sample)
        self.assertEqual(self.fake_audiocore.reset_calls, 1)
        self.assertGreater(len(self.transport.data), 0)
        self.assertTrue(out.playing)

    def test_constructor_retains_audiocore(self):
        out = self.sample_out.AudioOut(self.transport)
        self.assertIs(out._audiocore, self.fake_audiocore)

    def test_cpython_missing_package_error_has_exact_install_command(self):
        from audiodev import sample_out

        real_import = __import__

        def import_without_audiocore(name, *args, **kwargs):
            if name == "audiocore":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=import_without_audiocore):
            with self.assertRaisesRegex(
                ImportError,
                r"python -m pip install --index-url https://test\.pypi\.org/simple/ pydevices-audioif",
            ):
                sample_out.AudioOut(FakePCMOutput(AudioFormat(8000, 1, 16)))

    def test_micropython_missing_module_error_names_audioif_usermod(self):
        from audiodev import sample_out

        real_import = __import__

        def import_without_audiocore(name, *args, **kwargs):
            if name == "audiocore":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=import_without_audiocore), mock.patch.object(
            sys, "implementation", SimpleNamespace(name="micropython")
        ):
            with self.assertRaisesRegex(ImportError, "audioif MicroPython usermod"):
                sample_out.AudioOut(FakePCMOutput(AudioFormat(8000, 1, 16)))

    def test_stop_halts_playback(self):
        sample = FakeSample([bytes(200) for _ in range(50)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample)
        out.stop()
        self.assertFalse(out.playing)
        written_before = len(self.transport.data)
        self.clock.advance(1000)
        out.service()
        self.assertEqual(len(self.transport.data), written_before)

    def test_pause_resume(self):
        sample = FakeSample([bytes(200) for _ in range(50)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample)
        written_at_play = len(self.transport.data)
        out.pause()
        self.assertTrue(out.paused)
        self.clock.advance(1000)
        out.service()
        self.assertEqual(len(self.transport.data), written_at_play)  # no growth while paused
        out.resume()
        self.assertFalse(out.paused)
        self.clock.advance(200)
        out.service()
        self.assertGreater(len(self.transport.data), written_at_play)

    def test_loop_reaches_completion_and_resets(self):
        # A short sample fully drains inside the first play()'s lookahead
        # pull; looping means it keeps going rather than stopping.
        sample = FakeSample([bytes(64), bytes(64)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample, loop=True)
        self.assertGreater(self.fake_audiocore.reset_calls, 1)
        self.assertTrue(out.playing)

    def test_no_loop_stops_at_completion(self):
        sample = FakeSample([bytes(64), bytes(64)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample, loop=False)
        self.assertFalse(out.playing)

    def test_format_mismatch_raises(self):
        sample = FakeSample([bytes(64)], bits_per_sample=8, channel_count=2)
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        with self.assertRaises(ValueError):
            out.play(sample)

    def test_sample_rate_mismatch_does_not_raise(self):
        # No resampling: bits/channels must match, but a different
        # sample_rate on the source object (not consulted by AudioOut at
        # all) is not an error -- see sample_out.py's module docstring.
        sample = FakeSample([bytes(64)])  # bits/channels match self.fmt
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample)  # must not raise
        self.assertTrue(True)

    def test_volume_and_codec_forward_to_transport(self):
        out = self.sample_out.AudioOut(self.transport)
        out.set_volume(42)
        self.assertEqual(out.volume, 42)
        self.assertEqual(out.volume, self.transport.volume)
        out.mute(True)
        self.assertTrue(out.muted)

    def test_close_stops_and_closes_transport(self):
        sample = FakeSample([bytes(200) for _ in range(50)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample)
        out.close()
        self.assertFalse(out.playing)
        self.assertEqual(self.transport.close_count, 1)

    def test_typed_memoryview_chunks_do_not_double_production(self):
        # The real audioif usermod's get_buffer() once returned typed ('h')
        # memoryviews whose len() is the SAMPLE count, not bytes; trusting
        # len(buf) made the pump under-count 16-bit PCM by 2x and produce at
        # twice realtime, saturating the transport (500ms blocking writes,
        # stall recycles -- the desktop "intermittent/laggy piano"). The pump
        # now calibrates bytes-per-len-unit from the first chunk; a synth-like
        # endless source in each unit must pace at ~realtime either way.
        for kind in ("typed", "bytes"):

            class EndlessSample:
                bits_per_sample = 16
                channel_count = 1

                def reset(self_inner):
                    pass

                def next_chunk(self_inner):
                    raw = bytes(256)
                    if kind == "typed":
                        return memoryview(raw).cast("h")  # len() == 128 samples
                    return raw  # len() == 256 bytes

            sample = EndlessSample()
            sample._pos = 0
            sample._chunks = [None, None]  # keep FakeAudiocore reporting MORE_DATA
            with self.subTest(kind=kind):
                transport = FakePCMOutput(self.fmt)
                out = self.sample_out.AudioOut(transport, chunk_ms=40, lookahead_chunks=2)
                out.play(sample)
                for _ in range(25):
                    self.clock.advance(40)
                    out.service()
                # 1000ms elapsed + 80ms lookahead at 8kHz mono 16-bit
                expected = (1000 + 80) * 16
                written = len(transport.data)
                self.assertLess(abs(written - expected), 600,
                                "pump wrote %d bytes, expected ~%d" % (written, expected))

    def test_backpressure_skips_pull_and_drains_backlog(self):
        # A transport backlog (priming, stall catch-up) must drain back to
        # the lookahead level instead of riding ahead of every note forever:
        # when queued_size() exceeds lookahead+1 chunks, the pump skips the
        # pull (marking the schedule consumed, so resuming is per-tick, not
        # a catch-up burst that would re-flood the queue).
        class BackloggedTransport(FakePCMOutput):
            def __init__(self, fmt):
                super().__init__(fmt)
                self.backlog = 0

            def queued_size(self):
                return self.backlog

        transport = BackloggedTransport(self.fmt)
        sample = FakeSample([bytes(200) for _ in range(200)])
        out = self.sample_out.AudioOut(transport, chunk_ms=40, lookahead_chunks=2)
        out.play(sample)
        written_at_play = len(transport.data)

        # cap = (2+1) chunks * 40ms * 16 B/ms = 5760 bytes; report more
        transport.backlog = 8000
        for _ in range(5):
            self.clock.advance(40)
            out.service()
        self.assertEqual(len(transport.data), written_at_play,
                         "pump pulled against a saturated transport")
        self.assertTrue(out.playing)

        # backlog cleared: per-tick pulls resume, without a catch-up burst
        transport.backlog = 0
        self.clock.advance(40)
        out.service()
        resumed = len(transport.data) - written_at_play
        self.assertGreater(resumed, 0)
        self.assertLessEqual(resumed, 3 * 40 * 16,
                             "resume pulled a catch-up burst, not per-tick chunks")

    def test_backpressure_cap_clears_the_priming_threshold(self):
        # A transport with a prebuffer above the lookahead cap must still be
        # fed: a freshly primed device stays paused (consuming nothing) until
        # _prebuffer_bytes are queued, so a cap below that deadlocks in
        # silence -- pump waiting on drain, device waiting on bytes.
        class PrimingTransport(FakePCMOutput):
            _prebuffer_bytes = 4000  # > (2+1) chunks * 40ms * 16B/ms = 1920

            def queued_size(self):
                # everything written and nothing consumed: still priming
                return len(self.data)

        transport = PrimingTransport(self.fmt)
        sample = FakeSample([bytes(200) for _ in range(200)])
        out = self.sample_out.AudioOut(transport, chunk_ms=40, lookahead_chunks=2)
        out.play(sample)
        for _ in range(10):
            self.clock.advance(40)
            out.service()
        self.assertGreater(
            len(transport.data), transport._prebuffer_bytes,
            "pump stopped feeding a still-priming transport (deadlock)")

    def test_attach_callback_tolerates_timer_arg(self):
        # appdev.App._dispatch_tick always calls a subscribed callback with
        # one positional arg (the timer object) -- attach() must adapt
        # service() (a plain zero-arg method, like every sibling
        # PCMOutput.service()) to that convention, not assume the app never
        # passes one.
        sample = FakeSample([bytes(200) for _ in range(50)])
        out = self.sample_out.AudioOut(self.transport, chunk_ms=40)
        out.play(sample)
        app = FakeApp()
        out.attach(app)
        app.fire(object())  # simulates _dispatch_tick(timer_obj)


class FakeApp:
    """Minimal app.every()-shaped double, matching appdev.App's contract."""

    def __init__(self):
        self._callback = None

    def every(self, _ms, callback):
        self._callback = callback
        return _FakeTimerSubscription()

    def fire(self, timer_obj):
        self._callback(timer_obj)


class _FakeTimerSubscription:
    def cancel(self):
        pass


class ToneTests(unittest.TestCase):
    def test_tone_and_async_stop(self):
        async def run():
            stream = FakeTone()
            power = []
            tone = PWMToneOutput(stream, power=power.append)
            self.assertIsInstance(tone, ToneOutput)
            tone.set_volume(25)
            tone.play(440)
            self.assertEqual((stream.frequency, stream.level), (440, 25))
            await tone.aplay(880, 1)
            self.assertTrue(stream.stopped)
            tone.close()
            self.assertEqual(power, [True, False])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
