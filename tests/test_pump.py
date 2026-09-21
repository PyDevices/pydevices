# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``audiodev.pump`` on an interpreter that has no pump.

Nine hundred lines of arbitration -- who is sounding, what the root of the
graph is, what happens when one player leaves and what happens when the pump
dies under them -- and until this file existed CI's only contact with it was
a layering rule and one line in a generated TOML.

Everything here runs under CPython with three stand-ins: the ``audiopump``
engine, the ``audiomixer`` root and the ``audiocore`` pull. That is enough
for all of the arbitration, because none of it is C: `Pump` decides, and the
module it decides *with* is fetched through :func:`audiodev.pump.module`,
which a test can hand anything.

**What it cannot show** is that the pump actually pulls, that the bytes come
out identical, or that a block lands on time -- those want the real engine on
a real interpreter, and they are ``tests/pump_probes/`` run by
``test_pump_interpreter.py``.
"""

from pathlib import Path
import io
import sys
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import AudioFormat, PCMOutput            # noqa: E402
from audiodev import pump as pump_mod                  # noqa: E402
from audiodev import sample_out                        # noqa: E402

RATE = 48000
CHANNELS = 2
FMT = AudioFormat(RATE, CHANNELS, 16)

STATUS_WORDS = 32
STATUS_BYTES = STATUS_WORDS * 8


# --- the three stand-ins ---------------------------------------------------


class FakeSample:
    """An audiosample-shaped source: a fixed number of identical blocks."""

    bits_per_sample = 16

    def __init__(self, blocks=8, block=1024, channel_count=CHANNELS,
                 sample_rate=RATE, name=None):
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.max_buffer_length = block
        self._blocks = [bytes([(index + 1) % 251]) * block
                        for index in range(blocks)]
        self._at = 0
        if name is not None:
            self.__class__ = type(name, (FakeSample,), {})

    def reset(self):
        self._at = 0

    def next_block(self):
        if self._at >= len(self._blocks):
            return None
        block = self._blocks[self._at]
        self._at += 1
        return block


class FakeAudiocore:
    GET_BUFFER_DONE = 0
    GET_BUFFER_MORE_DATA = 1

    def get_buffer(self, sample):
        block = sample.next_block()
        if block is None:
            return (self.GET_BUFFER_DONE, b"")
        more = sample._at < len(sample._blocks)
        return (self.GET_BUFFER_MORE_DATA if more
                else self.GET_BUFFER_DONE, block)

    def reset_buffer(self, sample):
        sample.reset()


class FakeVoice:
    def __init__(self):
        self.level = None


class FakeMixer:
    """``audiomixer.Mixer``: what the pump builds for a second client."""

    bits_per_sample = 16

    def __init__(self, *, voice_count, sample_rate, channel_count,
                 bits_per_sample, samples_signed, buffer_size):
        self.voice_count = voice_count
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.buffer_size = buffer_size
        self.voice = [FakeVoice() for _ in range(voice_count)]
        #: every ``play()``, as ``(sample, voice, loop)``
        self.played = []
        self.deinited = False

    def play(self, sample, *, voice=0, loop=False):
        self.played.append((sample, voice, loop))

    def next_block(self):
        """A root mixer sums its voices; a fake hands back the first one that
        still has something, which is enough to make the bytes flow."""
        for sample, _voice, loop in self.played:
            block = sample.next_block()
            if block is None and loop:
                sample.reset()
                block = sample.next_block()
            if block is not None:
                return block
        return None

    def deinit(self):
        self.deinited = True


class FakeAudiomixer:
    def __init__(self):
        self.built = []

    def Mixer(self, **kwargs):                          # noqa: N802 - a class
        mixer = FakeMixer(**kwargs)
        self.built.append(mixer)
        return mixer


class FakeRing:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.data = bytearray()
        self.room = 1 << 20
        self.sample_rate = kwargs.get("sample_rate", RATE)
        self.channel_count = kwargs.get("channel_count", CHANNELS)
        self.bits_per_sample = 16
        self.max_buffer_length = (kwargs.get("frames", 256)
                                  * self.channel_count * 2)

    def write(self, view):
        took = min(len(view), self.room - len(self.data))
        self.data.extend(bytes(view[:took]))
        return took

    def level(self):
        return len(self.data)

    def next_block(self):
        """What the pump pulls out of it: whole blocks only, as the C ring
        does -- anything shorter stays put."""
        block = self.max_buffer_length
        if len(self.data) < block:
            return None
        out = bytes(self.data[:block])
        del self.data[:block]
        return out

    def deinit(self):
        pass


class FakeEngine:
    """``audiopump``: the names `audiodev.pump` requires, and a log."""

    STATUS_WORDS = STATUS_WORDS
    STATUS_BYTES = STATUS_BYTES

    def __init__(self, *, threads=True, spawn_error=None):
        # An instance attribute, so a test can `del engine.Ring` and stand
        # for a build that shipped the engine without one.
        self.Ring = FakeRing
        self.calls = []
        self.spawned = None
        self.alive = False
        self.parked = False
        self._threads = threads
        self._spawn_error = spawn_error
        self.frame = 0
        self.loop = False

    # the six names module() insists on
    def spawn(self, sample, blocks, status, ring=None, loop=False,
              timeout_ms=0):
        # `loop` is the engine's since the split: the pump IS the output, so
        # the flag sits on it the way CircuitPython puts it on `I2SOut.play`.
        # A fake that does not take it turns every caller into "the audio
        # pump would not take this graph" and the whole file goes red at once.
        if self._spawn_error is not None:
            raise RuntimeError(self._spawn_error)
        self.calls.append(("spawn", sample))
        self.spawned = sample
        self.loop = bool(loop)
        self.alive = True
        return True

    def shutdown(self):
        self.calls.append(("shutdown", None))
        self.alive = False

    def running(self):
        return self.alive

    def retarget(self, sample):
        self.calls.append(("retarget", sample))
        self.spawned = sample

    def drain(self, into):
        """Hand back one block of whatever the pump is pointed at.

        The real engine pulls the graph on its own thread and writes into a
        ring this copies out of. Here the pull happens inside the drain,
        which is the same bytes in the same order without a thread.
        """
        if self.spawned is None or not self.alive:
            return 0
        block = self.spawned.next_block()
        if block is None:
            self.alive = False       # the source ran out: the pump stops
            return 0
        count = min(len(block), len(into))
        into[:count] = block[:count]
        self.frame += count // (CHANNELS * 2)
        return count

    def park(self, timeout_us=0):
        self.parked = True
        return True

    # the optional ones
    def unpark(self):
        self.parked = False

    def threaded(self):
        return self._threads

    def driver(self):
        return "pthread" if self._threads else "none"

    def now(self):
        return self.frame

    def info(self, sample):
        return (sample.sample_rate, sample.channel_count, 16,
                getattr(sample, "max_buffer_length", 1024))

    def targets(self):
        """Every root the pump has been pointed at, in order."""
        return [sample for name, sample in self.calls
                if name in ("spawn", "retarget")]


class Recorder(PCMOutput):
    """A transport that keeps every byte it is handed."""

    def __init__(self, fmt=FMT, wire=None):
        super().__init__(fmt)
        self.data = bytearray()
        self.opened = 0
        if wire is not None:
            self.wire = wire
            self.audio_power = None

    def _open(self):
        self.opened += 1

    def _write(self, buf):
        self.data.extend(buf)
        return len(buf)

    def _close(self):
        pass


class PumpFixture(unittest.TestCase):
    """Hands `audiodev.pump` a fake engine and puts everything back."""

    THREADS = True

    def setUp(self):
        self.engine = FakeEngine(threads=self.THREADS)
        self.audiomixer = FakeAudiomixer()
        self.audiocore = FakeAudiocore()
        self._install(self.engine)
        self._modules = {}
        for name, module in (("audiomixer", self.audiomixer),
                             ("audiocore", self.audiocore)):
            self._modules[name] = sys.modules.get(name)
            sys.modules[name] = module
        self.addCleanup(self._restore)

    def _install(self, engine, driver=None):
        self._saved = (pump_mod._audiopump, pump_mod._looked,
                       pump_mod._driver, pump_mod._driver_looked,
                       pump_mod._owner)
        pump_mod._audiopump = engine
        pump_mod._looked = True
        pump_mod._driver = driver
        pump_mod._driver_looked = True
        pump_mod._owner = None

    def _restore(self):
        pump_mod.forget()
        (pump_mod._audiopump, pump_mod._looked, pump_mod._driver,
         pump_mod._driver_looked, pump_mod._owner) = self._saved
        for name, module in self._modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def player(self, transport=None, loop=False, sample=None, chunk_ms=10):
        """An `AudioOut` on the pump, already playing."""
        transport = Recorder() if transport is None else transport
        out = sample_out.AudioOut(transport, chunk_ms=chunk_ms)
        out.play(FakeSample() if sample is None else sample, loop=loop)
        self.addCleanup(out.close)
        return out


# --- what the module will accept ------------------------------------------


class TheEngineIsCheckedNotJustImported(unittest.TestCase):
    """MicroPython's unix port puts the working directory on ``sys.path``, so
    ``import audiopump`` in the workspace root finds the *checkout* as a
    namespace package and succeeds. Importability is not the test."""

    def setUp(self):
        self._saved = (pump_mod._audiopump, pump_mod._looked)
        self.addCleanup(self._put_back)

    def _put_back(self):
        pump_mod._audiopump, pump_mod._looked = self._saved

    def test_a_module_without_spawn_is_not_the_pump(self):
        class NotThePump:
            pass

        pump_mod._audiopump = None
        pump_mod._looked = False
        with mock.patch.dict(sys.modules, {"audiopump": NotThePump()}):
            self.assertIsNone(pump_mod.module())
            self.assertFalse(pump_mod.available())

    def test_every_required_name_is_required(self):
        for missing in pump_mod._REQUIRED:
            stub = mock.Mock(spec=[name for name in pump_mod._REQUIRED
                                   if name != missing])
            pump_mod._audiopump = None
            pump_mod._looked = False
            with mock.patch.dict(sys.modules, {"audiopump": stub}):
                self.assertIsNone(pump_mod.module(),
                                  "a module missing %s passed" % missing)


# --- one client, then two --------------------------------------------------


class OneClientIsTheTail(PumpFixture):

    def test_a_single_player_is_pulled_with_nothing_in_the_way(self):
        sample = FakeSample()
        out = self.player(sample=sample)
        self.assertTrue(out.pumped)
        self.assertIs(self.engine.spawned, sample,
                      "a single player got something other than its own graph")
        self.assertEqual(self.audiomixer.built, [],
                         "one client built a root mixer it does not need")
        self.assertEqual(pump_mod.owner().clients(), 1)


class ASecondClientGetsARootMixer(PumpFixture):

    def two(self):
        first = FakeSample()
        second = FakeSample()
        self.player(sample=first)
        self.player(sample=second)
        return first, second

    def test_both_are_on_it_at_full_level(self):
        first, second = self.two()
        self.assertEqual(len(self.audiomixer.built), 1,
                         "a second client did not build a root mixer")
        mixer = self.audiomixer.built[0]
        self.assertEqual(mixer.voice_count, 2)
        self.assertEqual([voice.level for voice in mixer.voice], [1.0, 1.0],
                         "a client was quietly halved")
        self.assertEqual([(sample, voice) for sample, voice, _loop
                          in mixer.played], [(first, 0), (second, 1)])
        self.assertIs(self.engine.spawned, mixer,
                      "the pump was not retargeted onto the root")

    def test_the_mixer_carries_the_graph_format(self):
        self.two()
        mixer = self.audiomixer.built[0]
        self.assertEqual(mixer.sample_rate, RATE)
        self.assertEqual(mixer.channel_count, CHANNELS)

    def test_a_looping_client_goes_on_looping(self):
        """Written red, against a real defect, and green since the fix.

        `Pump._tail()` used to mix every client with ``loop=False``. A player
        that was looping on its own -- which is the whole of what an
        `AudioOut` playing ``loop=True`` was doing a moment earlier -- stopped
        at the end of its first lap as soon as anything else started
        sounding. Nothing reported it: the voice simply went quiet.

        The loop belongs to the client now. Put ``loop=False`` back in
        `_tail()` and this row fails again.
        """
        looping = FakeSample()
        self.player(sample=looping, loop=True)
        self.player(sample=FakeSample())

        mixer = self.audiomixer.built[0]
        played = {sample: loop for sample, _voice, loop in mixer.played}
        self.assertTrue(
            played[looping],
            "the looping player was mixed with loop=False and stops at the "
            "end of its first lap")

    def test_a_third_client_widens_the_root(self):
        self.two()
        self.player(sample=FakeSample())
        self.assertEqual(self.audiomixer.built[-1].voice_count, 3)

    def test_the_old_root_is_retired_one_generation_late(self):
        """Deinit-ing straight after the retarget is a race the P4 caught,
        with fault=deinited: the pump may still be inside the old graph."""
        self.two()
        first_root = self.audiomixer.built[0]
        self.player(sample=FakeSample())
        self.assertFalse(first_root.deinited,
                         "the old root was deinited while the pump may still "
                         "have been in it")
        self.player(sample=FakeSample())
        self.assertTrue(first_root.deinited, "a retired root was never freed")


class StopTakesOneClientAway(PumpFixture):

    def test_stopping_one_leaves_the_other_sounding(self):
        first = FakeSample()
        second = FakeSample()
        one = self.player(sample=first)
        self.player(sample=second)

        one.stop()
        self.assertEqual(pump_mod.owner().clients(), 1)
        self.assertIs(self.engine.spawned, second,
                      "the survivor is not what the pump is pulling")
        self.assertTrue(self.engine.alive, "one player leaving killed the pump")

    def test_stopping_the_last_one_gives_the_pump_back(self):
        out = self.player()
        out.stop()
        self.assertEqual(pump_mod.owner().clients(), 0)
        self.assertFalse(self.engine.alive,
                         "the pump is still running with nobody on it")

    def test_a_hundred_play_stop_rounds_leave_nothing_behind(self):
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        for _ in range(100):
            out.play(FakeSample())
            out.stop()
        self.assertEqual(pump_mod.owner().clients(), 0,
                         "a client was left on the pump")


class PauseParksTheThread(PumpFixture):

    def test_pause_parks_and_resume_unparks(self):
        out = self.player()
        out.pause()
        self.assertTrue(self.engine.parked, "a paused player left it running")
        out.resume()
        self.assertFalse(self.engine.parked, "resume did not unpark")

    def test_one_of_two_pausing_leaves_the_pump_running(self):
        one = self.player()
        self.player()
        one.pause()
        self.assertFalse(pump_mod.owner().paused(),
                         "one player pausing silenced the other")


# --- when it goes wrong ----------------------------------------------------


class AFaultIsASentence(PumpFixture):
    """A fault in the pump is a sentence, not a traceback and not a dead
    speaker: the player says what happened and carries on pulling the graph
    on its own thread."""

    def refuse(self):
        pump_mod.owner()          # build it before breaking the engine
        self.engine._spawn_error = "the pump would not start"

    def test_the_player_falls_back_and_says_so(self):
        self.refuse()
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)

        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.play(FakeSample())

        self.assertFalse(out.pumped, "it thinks it is on the pump")
        self.assertIn("pump", said.getvalue().lower())
        self.assertIn("interpreter thread", said.getvalue())
        self.assertTrue(transport.data, "the audio stopped as well")

    def test_the_fault_is_remembered_for_the_process(self):
        self.refuse()
        with mock.patch("sys.stdout", io.StringIO()):
            self.player()
        self.assertIsNotNone(pump_mod.owner().fault())
        self.assertFalse(pump_mod.owner().play(object(), FakeSample()),
                         "a faulted pump took another client")

    def test_nothing_raises_out_of_play(self):
        self.refuse()
        out = sample_out.AudioOut(Recorder(), chunk_ms=10)
        self.addCleanup(out.close)
        with mock.patch("sys.stdout", io.StringIO()):
            out.play(FakeSample())          # must not raise

    def test_the_pump_answers_a_refusal_with_False_not_a_traceback(self):
        """`Pump.play` catches its own exception, so a refusal can never
        reach an app that did not ask for the pump."""
        self.refuse()
        owner = pump_mod.owner()
        self.assertFalse(owner.play(object(), FakeSample()))
        self.assertEqual(owner.clients(), 0,
                         "the client that could not sound was kept")
        self.assertIn("would not start", owner.fault())

    def test_a_prefetch_that_cannot_be_built_is_a_sentence(self):
        """The other half of the fallback: the failure happens in
        `audiodev`'s own code, before the engine is ever asked."""
        engine = FakeEngine()
        del engine.Ring
        pump_mod._audiopump = engine
        sample = FakeSample()
        sample.__class__ = type("WaveFile", (FakeSample,), {})

        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.play(sample)                # must not raise

        self.assertIn("audiopump.Ring", said.getvalue())
        self.assertIn("interpreter thread", said.getvalue())
        self.assertFalse(out.pumped)
        self.assertTrue(transport.data, "the audio stopped with the pump")

    def test_died_turns_the_status_words_into_a_sentence(self):
        owner = pump_mod.owner()
        owner.play(object(), FakeSample())
        self.engine.alive = False
        owner.status()[5 * 8] = 3           # "the source ran out"
        self.assertEqual(owner.died(), "the source ran out")
        owner.status()[24 * 8] = 2          # a fault outranks an error
        self.assertEqual(
            owner.died(),
            "something in the chain was released while it was playing")

    def test_an_unknown_reason_still_says_something(self):
        owner = pump_mod.owner()
        owner.play(object(), FakeSample())
        self.engine.alive = False
        owner.status()[5 * 8] = 99
        self.assertIn("error 99", owner.died())


class TheSinkPathReportsItsFaultsToo(PumpFixture):
    """esp32: the pump owns the I2S channel outright, so the fallback has a
    different driver under it and the same contract on top."""

    def setUp(self):
        super().setUp()

        class Driver:
            def i2s_start(self, *args, **kwargs):
                raise RuntimeError("no I2S channel here")

        pump_mod._driver = Driver()
        pump_mod._driver_looked = True

    def test_a_board_whose_transport_has_no_wire_says_so_once(self):
        del sample_out._WARNED[:]
        said = io.StringIO()
        out = sample_out.AudioOut(Recorder(), chunk_ms=10)
        self.addCleanup(out.close)
        with mock.patch("sys.stdout", said):
            out.play(FakeSample())
        self.assertFalse(out.pumped)
        self.assertIn("board's board_peripherals publishes no `wire=`",
                      said.getvalue())
        self.assertTrue(out.playing or out.transport.data,
                        "the old path did not take over")

    def test_a_sink_driver_that_will_not_open_falls_back(self):
        said = io.StringIO()
        transport = Recorder(wire=object())
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        with mock.patch("sys.stdout", said):
            out.play(FakeSample())
        self.assertFalse(out.pumped)
        self.assertIn("interpreter thread", said.getvalue())
        self.assertTrue(transport.data, "the audio stopped with the pump")


class WithoutAPumpNothingChanges(unittest.TestCase):
    """A build with no ``audiopump`` must behave exactly as it did before the
    pump existed -- no import, no branch, no mention of it."""

    def setUp(self):
        self._saved = (pump_mod._audiopump, pump_mod._looked,
                       pump_mod._driver, pump_mod._driver_looked,
                       pump_mod._owner)
        pump_mod._audiopump = None
        pump_mod._looked = True
        pump_mod._driver = None
        pump_mod._driver_looked = True
        pump_mod._owner = None
        self._audiocore = sys.modules.get("audiocore")
        sys.modules["audiocore"] = FakeAudiocore()
        self.addCleanup(self._restore)

    def _restore(self):
        pump_mod.forget()
        (pump_mod._audiopump, pump_mod._looked, pump_mod._driver,
         pump_mod._driver_looked, pump_mod._owner) = self._saved
        if self._audiocore is None:
            sys.modules.pop("audiocore", None)
        else:
            sys.modules["audiocore"] = self._audiocore

    def test_the_player_never_mentions_it(self):
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.play(FakeSample())
        self.assertFalse(out.pumped)
        self.assertEqual(said.getvalue(), "",
                         "a build with no pump talked about one")
        self.assertTrue(transport.data, "nothing was played")

    def test_the_module_answers_every_question_with_a_no(self):
        self.assertFalse(pump_mod.available())
        self.assertFalse(pump_mod.on_board())
        self.assertEqual(pump_mod.driver_name(), "none")
        self.assertEqual(pump_mod.now(), 0)
        self.assertIsNone(pump_mod.events())
        self.assertEqual(pump_mod.block_size(FakeSample()), 0)

    def test_a_pump_less_build_still_plays_to_the_end(self):
        clock = [0]
        saved = (sample_out.ticks_ms, sample_out.ticks_diff)
        sample_out.ticks_ms = lambda: clock[0]
        sample_out.ticks_diff = lambda a, b: a - b
        self.addCleanup(lambda: setattr(sample_out, "ticks_diff", saved[1]))
        self.addCleanup(lambda: setattr(sample_out, "ticks_ms", saved[0]))

        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        out.play(FakeSample(blocks=8, block=1024))
        for _ in range(50):
            clock[0] += 10
            out.service()
        self.assertEqual(len(transport.data), 8 * 1024,
                         "the old path did not play the sample out")
        self.assertFalse(out.playing)


# --- the file-backed path --------------------------------------------------


class AFileGoesThroughPrefetch(PumpFixture):
    """A file-backed source reads the VFS inside its own ``get_buffer`` and
    the pump's thread has no interpreter to do that on, so it becomes a
    producer into a ring instead."""

    def wave(self, blocks=8, block=1024):
        sample = FakeSample(blocks=blocks, block=block)
        sample.__class__ = type("WaveFile", (FakeSample,), {})
        return sample

    def test_the_pump_refuses_a_file_and_takes_its_ring(self):
        self.assertFalse(pump_mod.pumpable(self.wave()))
        out = self.player(sample=self.wave())
        self.assertIsNotNone(out._prefetch, "no Prefetch was built")
        self.assertIs(self.engine.spawned, out._prefetch.ring,
                      "the pump was handed the file, not the ring")

    def test_every_byte_of_the_file_reaches_the_ring(self):
        prefetch = pump_mod.Prefetch(self.wave(blocks=8, block=1024),
                                     frames=256)
        self.addCleanup(prefetch.deinit)
        while not prefetch.fed():
            if prefetch.service() == 0 and prefetch.done:
                break
        self.assertTrue(prefetch.done)
        self.assertGreaterEqual(prefetch.wrote, 8 * 1024)

    def test_the_last_partial_block_is_padded_out(self):
        """The ring hands the pump whole blocks and holds anything shorter,
        so a file that is not a whole number of blocks left its final frames
        in the ring for ever. A 1.0 s file lost its last 512 bytes."""
        block = 256 * CHANNELS * 2
        sample = self.wave(blocks=1, block=block + 512)
        prefetch = pump_mod.Prefetch(sample, frames=256)
        self.addCleanup(prefetch.deinit)
        for _ in range(10):
            prefetch.service()
        self.assertEqual(prefetch.ring.level() % prefetch.block, 0,
                         "a partial block is stuck in the ring")
        self.assertGreater(prefetch.ring.level(), block)

    def test_a_looping_file_is_read_again_at_the_end(self):
        sample = self.wave(blocks=2, block=512)
        prefetch = pump_mod.Prefetch(sample, frames=128, loop=True)
        self.addCleanup(prefetch.deinit)
        for _ in range(6):
            prefetch.service()
        self.assertFalse(prefetch.done, "a looping file reported end of file")
        self.assertGreater(prefetch.wrote, 2 * 512,
                           "the loop never came round")

    def test_a_build_with_no_ring_says_so(self):
        """An older pump, or one built without the ring: a file-backed source
        has nowhere to go and must say which name is missing."""
        engine = FakeEngine()
        del engine.Ring
        pump_mod._audiopump = engine
        with self.assertRaises(RuntimeError) as caught:
            pump_mod.Prefetch(self.wave())
        self.assertIn("audiopump.Ring", str(caught.exception))


# --- the clock -------------------------------------------------------------


class TheQueueBelongsToThePump(PumpFixture):

    def test_a_build_with_no_events_answers_none(self):
        self.assertIsNone(pump_mod.events())

    def test_the_queue_is_reattached_after_a_teardown(self):
        """``audiopump.shutdown()`` drops the queue with the thread, and a
        player calling play() a second time goes through a shutdown. An app
        that attached its own would find it quietly stopped being applied."""
        attached = []

        class Queue:
            def clear(self):
                pass

        engine = self.engine
        engine.Events = lambda capacity=96: Queue()
        engine.events = attached.append

        queue = pump_mod.events()
        self.assertIsNotNone(queue)
        self.assertEqual(attached, [queue])

        out = self.player()
        out.stop()
        self.player()
        self.assertGreater(len(attached), 1,
                           "the queue was not handed back after the restart")
        self.assertIs(attached[-1], queue, "the app's queue was replaced")


if __name__ == "__main__":
    unittest.main()
