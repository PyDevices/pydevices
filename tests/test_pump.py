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
import struct
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
        """A root mixer SUMS its voices, and this one does too.

        It used to hand back the first voice that still had something, which
        is the *absence reads as agreement* trap arriving through a fixture:
        a second client that contributed nothing at all produced exactly the
        same bytes as a second client that was mixed in perfectly, so no test
        driving the live retarget could ever have caught a silent voice. That
        is the defect the fold found with a probe and nothing in here could
        see (``docs/spikes/live-audio-path-land3.md``).
        """
        blocks = []
        for sample, _voice, loop in self.played:
            block = sample.next_block()
            if block is None and loop:
                sample.reset()
                block = sample.next_block()
            if block is not None:
                blocks.append(block)
        if not blocks:
            return None
        width = max(len(block) for block in blocks)
        out = bytearray(width)
        for block in blocks:
            for index, value in enumerate(block):
                out[index] = (out[index] + value) & 0xFF
        return bytes(out)

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
        self.sample_rate = kwargs.get("sample_rate", RATE)
        self.channel_count = kwargs.get("channel_count", CHANNELS)
        self.bits_per_sample = 16
        self.max_buffer_length = (kwargs.get("frames", 256)
                                  * self.channel_count * 2)
        # A ring with room for `capacity` blocks and not a byte more. It was
        # 1 MB, which is not a ring at all: a whole file fitted in one pass,
        # so a producer that was never topped up again looked exactly like
        # one that was, and the plant for "nothing reads the file on this
        # path" came back green.
        self.room = int(kwargs.get("capacity", 6)) * self.max_buffer_length

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
        if self.alive:
            # The real engine's words, and the real engine's refusal: there is
            # one pump. A fake that quietly accepted a second spawn could not
            # show what a service tick landing inside a rearrangement does,
            # which is the whole of the P4's `Peripheral in use`.
            raise ValueError(
                "a pump is already spawned; call audiopump.shutdown() first")
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

    def retarget(self, sample, loop=None):
        # `loop=None` means "leave it as spawn() set it", which is what every
        # caller that predates the keyword wanted. A fake that does not take
        # it turns the live branch into a TypeError, `audiodev` reports "the
        # audio pump would not take this graph", and the file goes red in a
        # way that names the fake rather than the code.
        self.calls.append(("retarget", sample))
        self.spawned = sample
        if loop is not None:
            self.loop = bool(loop)

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


class FinishesUnwatched(FakeEngine):
    """The pump that does the whole job before the interpreter looks again.

    ``spawn()`` returns with the loop already over -- the status block says
    "the source ran out" and ``running()`` is False -- and the first drain
    still comes back empty, because the player looked before the bytes were
    there. The second hands the sample over.

    Those two looks are the whole of pydevices#52. Between them the player
    decides twice whether it has a pump and whether the sample is finished,
    and both readings used to be wrong.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.looks = 0

    def backpressure(self):
        # The ring paces the pump on this build, which is the only branch of
        # `RingDriver.spawn` that reads `running()` at all.
        return True

    def spawn(self, sample, blocks, status, ring=None, loop=False,
              timeout_ms=0):
        got = super().spawn(sample, blocks, status, ring=ring, loop=loop,
                            timeout_ms=timeout_ms)
        # Word 5 is the pump's own reason for leaving its loop, and 3 is "the
        # source ran out" -- the end of a short sample, not a failure.
        struct.pack_into("<Q", status, 5 * 8, 3)
        self.alive = False
        return got

    def drain(self, into):
        self.looks += 1
        if self.looks == 1:
            return 0
        self.alive = True
        try:
            return super().drain(into)
        finally:
            self.alive = False


class NeverStarts(FakeEngine):
    """A pump that really did not run: no blocks, no error, no trace at all.

    The other side of `FinishesUnwatched`, and the reason the two cannot be
    told apart by `running()` alone.
    """

    def backpressure(self):
        return True

    def spawn(self, sample, blocks, status, ring=None, loop=False,
              timeout_ms=0):
        got = super().spawn(sample, blocks, status, ring=ring, loop=loop,
                            timeout_ms=timeout_ms)
        self.alive = False
        return got


class FakeI2SOut:
    """``audiobusio.I2SOut``: the surface ``audiodev`` drives it through.

    The real one is C in the ``audiopump`` repo and it opens a real I2S
    channel on esp32. What matters here is the *contract* ``audiodev`` now
    depends on -- it is the only thing that opens the peripheral, it owns the
    pump's status block, it sizes the DMA descriptor itself, and it can swap
    the tail without stopping -- so this stands in for it and drives the same
    `FakeEngine` underneath, which is how ``audiopump.running()`` stays honest
    on both sides of the line.
    """

    #: every constructor, as the kwargs it was given, newest last
    built = []

    def __init__(self, bit_clock, word_select, data, *, main_clock=None,
                 port=None, sample_rate=48000, main_clock_fs=256, sink=None,
                 engine=None):
        if FakeI2SOut.live is not None:
            raise RuntimeError("Peripheral in use")
        self.pins = (bit_clock, word_select, data, main_clock)
        self.port = port
        self.sample_rate = sample_rate
        self.main_clock_fs = main_clock_fs
        self.sink = sink
        self.engine = engine if engine is not None else pump_mod.module()
        self.status = bytearray(STATUS_BYTES)
        self.deinited = False
        self.playing_ = False
        self.paused = False
        self.loop = False
        self.plays = 0
        self.retargets = []
        FakeI2SOut.built.append(self)
        FakeI2SOut.live = self

    live = None

    # --- CircuitPython's surface -----------------------------------------

    def play(self, sample, *, loop=False):
        self.stop()
        self.plays += 1
        self.loop = bool(loop)
        # The descriptor is sized in TIME by the real one (`rate / 200`), and
        # `audiodev` passes no size at all. Recording the rate is enough to
        # prove that the number is not `audiodev`'s any more.
        self.engine.spawn(sample, 1 << 31, self.status, loop=loop)
        self.playing_ = True

    def stop(self):
        if self.playing_:
            self.engine.shutdown()
        self.playing_ = False
        self.paused = False

    @property
    def playing(self):
        if self.playing_ and not self.engine.running():
            self.playing_ = False
        return self.playing_

    def pause(self):
        if not self.playing_:
            raise RuntimeError("Not playing")
        self.engine.park(200000)
        self.paused = True

    def resume(self):
        if self.paused:
            self.paused = False
            self.engine.unpark()

    def starved(self):
        return 7                       # a number only this object can know

    def deinit(self):
        self.stop()
        self.deinited = True
        if FakeI2SOut.live is self:
            FakeI2SOut.live = None

    # --- ours, not CircuitPython's ---------------------------------------

    def retarget(self, sample, *, loop=False):
        if not self.playing_:
            raise RuntimeError("Not playing")
        self.retargets.append((sample, loop))
        self.loop = bool(loop)
        self.engine.retarget(sample, loop=loop)


class FakeBusio:
    I2SOut = FakeI2SOut


class FakeWire:
    """A board's ``audiodev.I2SWire``, as ``board_peripherals`` publishes it."""

    #: 384 rather than the 256 every shipped board straps, on purpose: a
    #: number that matches the default cannot show that it travelled.
    def __init__(self, port=0, sck=12, ws=13, sd=14, mck=15, mck_fs=384):
        self.port = port
        self.sck = sck
        self.ws = ws
        self.sd = sd
        self.mck = mck
        self.mck_fs = mck_fs


class Recorder(PCMOutput):
    """A transport that keeps every byte it is handed."""

    def __init__(self, fmt=FMT, wire=None, power=False):
        super().__init__(fmt)
        self.data = bytearray()
        self.opened = 0
        #: writes that happened while something was rearranging the pump
        self.wrote_while_rearranging = 0
        #: every ``audio_power`` call, as ``(on, volume)``
        self.powered = []
        #: every ``hardware_live`` call
        self.live = []
        if wire is not None:
            self.wire = wire
            self.audio_power = self._power_role if power else None

    def _power_role(self, on, volume=None):
        self.powered.append((bool(on), volume))

    def hardware_live(self, value=True):
        self.live.append(bool(value))
        return super().hardware_live(value)

    def _open(self):
        self.opened += 1

    def _write(self, buf):
        # A write is what opens the peripheral. `PCMOutput.write()` opens the
        # transport on its first byte, and on a board that is `machine.I2S`
        # on the port the pump is holding -- which is the P4's own race, and
        # the one thing a tick must never do mid-rearrangement.
        if pump_mod.rearranging():
            self.wrote_while_rearranging += 1
        self.data.extend(buf)
        return len(buf)

    def _close(self):
        pass


class PumpFixture(unittest.TestCase):
    """Hands `audiodev.pump` a fake engine and puts everything back."""

    THREADS = True

    #: The engine this fixture installs. A subclass names another to stand for
    #: a build, or a moment, that the plain one cannot.
    ENGINE = FakeEngine

    def setUp(self):
        self.engine = self.ENGINE(threads=self.THREADS)
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


class AStartTheInterpreterMissedCostsNoAudio(PumpFixture):
    """pydevices#52: a pump can finish the job before the player looks.

    A short sample is one block. On a busy core the pump can spawn, pull the
    whole thing into the ring, reach the end of the source and leave its loop
    before the interpreter is scheduled again -- and then two readings look
    like failure and neither is one. `running()` is False when `spawn()`
    returns, and the player's first `produce()` comes back empty because the
    bytes had not landed when it looked.

    Measured on the unix port under seven busy loops sharing one core with
    the interpreter: tearing the pump down for the first reading lost it on 1
    to 2 rounds in 100, and calling the sample finished on the second wrote a
    round of silence once in ten runs of a hundred.
    """

    ENGINE = FinishesUnwatched

    def play(self, blocks):
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.play(FakeSample(blocks=blocks, block=1024))
        return out, transport, said.getvalue()

    def test_a_pump_that_had_already_finished_is_kept(self):
        # Eight blocks, so the sample outlives the first tick and "is this
        # player on the pump" is still a question worth asking afterwards.
        out, _transport, said = self.play(8)
        self.assertTrue(out.pumped,
                        "a pump that had done the whole job was torn down")
        self.assertNotIn("interpreter thread", said)

    def test_the_bytes_it_made_are_not_stranded_in_the_ring(self):
        # One block: the whole sample is in the ring at the moment the player
        # is deciding whether the sample is over.
        _out, transport, _said = self.play(1)
        self.assertEqual(bytes(transport.data), b"\x01" * 1024,
                         "the sample the pump had already pulled never "
                         "reached the transport")


class AStartThatReallyFailedIsNotSticky(PumpFixture):
    """The other half of pydevices#52, and why the two need telling apart.

    A pump that left no trace at all did not start, so the player falls back
    -- and the loss is this afternoon's CPU, not this graph, so it must not
    close the door on every later `play()` in the process.
    """

    ENGINE = NeverStarts

    def test_it_falls_back_says_so_and_tries_again_next_time(self):
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.play(FakeSample())

        self.assertFalse(out.pumped, "it thinks it is on the pump")
        self.assertTrue(transport.data, "the audio stopped as well")
        self.assertIn("would not start", said.getvalue())
        self.assertFalse(pump_mod.owner().blocked(),
                         "one lost race shut the pump for the process")
        self.assertIsNotNone(out.pump_refused,
                             "nothing a UI can show says why")

    def test_the_next_play_reaches_for_the_pump_again(self):
        out = self.player()
        with mock.patch("sys.stdout", io.StringIO()):
            out.play(FakeSample())
            out.play(FakeSample())
        spawns = [name for name, _ in self.engine.calls if name == "spawn"]
        self.assertGreaterEqual(len(spawns), 3,
                                "a later play() did not even try the pump")


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


class ATransportThatRefusesToOpenLeavesNothingBehind(PumpFixture):
    """``play()`` opens the transport LAST, and a refusal has to unwind.

    A browser ``AudioContext`` the visitor has not unlocked yet refuses
    ``open()``, and on a gallery page that is the ORDINARY first call, not an
    edge: the example opens its audio at import, before anybody has clicked.
    ``open()`` used to be the first line of ``play()``, where it could not
    leave anything behind; the pump moved it after ``_attach_pump`` so a
    board's transport can never open ``machine.I2S`` on the port the pump is
    holding. The cost of that move is this: when the refusal came out,
    ``_sample`` and the engine were already set, so the player read as
    healthy and every ``service()`` on the app's shared timer opened the
    transport again and raised the same error -- one traceback per tick, for
    as long as the page was open. Watched happening on the gallery's piano.
    """

    class Refuses(Recorder):
        def _open(self):
            raise RuntimeError("audio output is disabled")

    def refused(self):
        out = sample_out.AudioOut(self.Refuses(), chunk_ms=10)
        self.addCleanup(out.close)
        with self.assertRaises(RuntimeError):
            out.play(FakeSample())
        return out

    def test_the_player_is_not_playing_afterwards(self):
        out = self.refused()
        self.assertFalse(out.playing)

    def test_the_pump_is_not_left_holding_the_graph(self):
        out = self.refused()
        self.assertFalse(out.pumped)

    def test_a_tick_on_the_shared_timer_does_not_raise(self):
        out = self.refused()
        for _ in range(3):
            out.service()

    def test_the_pump_is_given_back_to_the_next_player(self):
        self.refused()
        self.assertEqual(pump_mod.owner().clients(), 0)


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


class TheBoardPlaysThroughAudiobusio(PumpFixture):
    """esp32: there is ONE way this firmware plays a sample, and it is
    ``audiobusio.I2SOut``.

    ``audiodev`` used to open the channel itself -- ``_audioif.i2s_start``
    with a ``dma_frame=128`` fixed at every rate -- and reimplement
    ``play``/``stop``/``pause``/``resume``/``playing`` in Python over it.
    That descriptor is the bug ``audiobusio`` measured on the P4: 67 starved
    blocks in two seconds at 8 kHz, nothing at 48 kHz, gone at ``rate / 200``.
    What is left here is the policy nothing below the line knows about -- the
    codec, the volume, two clients, the file -- which is what ``audiodev`` is
    for.
    """

    def setUp(self):
        super().setUp()

        class Driver:                     # `on_board()` asks for this name
            def i2s_start(self, *args, **kwargs):
                raise AssertionError(
                    "audiodev opened the I2S channel itself; audiobusio owns "
                    "the peripheral now")

        pump_mod._driver = Driver()
        pump_mod._driver_looked = True
        FakeI2SOut.built = []
        FakeI2SOut.live = None
        self._saved_busio = (pump_mod._busio, pump_mod._busio_looked)
        pump_mod._busio = FakeBusio()
        pump_mod._busio_looked = True
        self.addCleanup(self._put_busio_back)

    def _put_busio_back(self):
        pump_mod._busio, pump_mod._busio_looked = self._saved_busio
        FakeI2SOut.live = None

    def board(self, power=True, loop=False, sample=None, volume=40):
        transport = Recorder(wire=FakeWire(), power=power)
        transport.set_volume(volume)
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        out.play(FakeSample() if sample is None else sample, loop=loop)
        return out, transport

    def test_the_graph_goes_to_I2SOut_and_nothing_opens_the_channel(self):
        out, transport = self.board()
        self.assertTrue(out.pumped, "the board fell back to the old path")
        self.assertEqual(len(FakeI2SOut.built), 1,
                         "audiodev did not build an I2SOut")
        i2s = FakeI2SOut.built[0]
        self.assertEqual(i2s.plays, 1)
        self.assertEqual(transport.opened, 0,
                         "the transport was opened; on a board that is "
                         "machine.I2S on the port the pump is holding")

    def test_the_wire_reaches_the_constructor_whole(self):
        """Every number the board published, including the one that used to
        be dropped: ``mck_fs`` had nowhere to go in ``I2SOut`` and a silently
        wrong MCLK ratio is a bus that sounds like a bad cable."""
        self.board()
        i2s = FakeI2SOut.built[0]
        self.assertEqual(i2s.pins, (12, 13, 14, 15))
        self.assertEqual(i2s.port, 0)
        self.assertEqual(i2s.main_clock_fs, 384,
                         "the board's MCLK ratio was dropped on the floor")
        self.assertEqual(i2s.sample_rate, RATE)

    def test_audiodev_names_no_dma_size_at_all(self):
        """The descriptor is sized in TIME, by ``audiobusio``, at every rate.

        ``audiodev`` naming one was the whole defect: ``dma_frame=128`` is
        16 ms at 8 kHz and 2.7 ms at 48 kHz, and the low rates lost a block
        per descriptor. There is no such keyword to get wrong now.
        """
        _out, transport = self.board()
        driver = pump_mod.owner()._driver
        self.assertIsInstance(driver, pump_mod.BusioDriver)
        for gone in ("dma_frame", "dma_desc", "din", "cushion"):
            self.assertFalse(hasattr(driver, gone),
                             "audiodev still carries %s" % gone)
        self.assertNotIn("dma", repr(transport.wire.__dict__))

    def test_the_codec_comes_up_at_the_volume_asked_for(self):
        _out, transport = self.board(volume=40)
        self.assertEqual(transport.powered, [(True, 40)],
                         "the codec was not raised with this volume")
        self.assertEqual(transport.live, [True],
                         "the transport was never told its codec is live, so "
                         "set_volume() and mute() reach nothing")

    def test_a_board_whose_power_role_takes_no_keyword_still_comes_up(self):
        transport = Recorder(wire=FakeWire(), power=True)
        calls = []
        transport.audio_power = lambda on: calls.append(on)
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        out.play(FakeSample())
        self.assertTrue(out.pumped)
        self.assertEqual(calls, [True])

    def test_stop_gives_the_peripheral_and_the_codec_back(self):
        out, transport = self.board()
        i2s = FakeI2SOut.built[0]
        out.stop()
        self.assertTrue(i2s.deinited, "the channel was left open")
        self.assertEqual(transport.powered[-1], (False, None))
        self.assertEqual(transport.live[-1], False)
        self.assertIsNone(FakeI2SOut.live,
                          "a second I2SOut would be refused for ever")

    def test_play_stop_play_opens_a_fresh_output_every_time(self):
        """The shipped drum machine's KIT CHANGE, a hundred times over."""
        out, _transport = self.board()
        for _ in range(20):
            out.stop()
            out.play(FakeSample())
        self.assertTrue(out.pumped, "it fell off the pump on a kit change")
        self.assertEqual(pump_mod.owner().clients(), 1)

    def test_pause_and_resume_go_through_the_output(self):
        out, _transport = self.board()
        out.pause()
        self.assertTrue(self.engine.parked)
        out.resume()
        self.assertFalse(self.engine.parked)

    def test_the_fault_sentence_comes_from_the_outputs_own_status_block(self):
        """``I2SOut`` spawns with a status bytearray of its own.

        Reading the one ``Pump`` allocated instead reports every death as
        ``error 0, fault 0`` -- silence with a reassuring sentence on it.
        """
        out, _transport = self.board()
        i2s = FakeI2SOut.built[0]
        self.engine.alive = False
        i2s.status[24 * 8] = 2
        self.assertEqual(
            pump_mod.owner().died(),
            "something in the chain was released while it was playing")
        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out.service()
        self.assertIn("released while it was playing", said.getvalue())

    def test_starved_is_the_outputs_own_word(self):
        self.board()
        self.assertEqual(pump_mod.owner()._driver.starved(), 7)

    def test_a_file_still_goes_through_audiodevs_own_prefetch(self):
        """``I2SOut`` feeds only the TAIL, and ``audiodev`` mixes."""
        sample = FakeSample(blocks=3)
        sample.__class__ = type("WaveFile", (FakeSample,), {})
        out, _transport = self.board(sample=sample)
        self.assertTrue(out.pumped)
        self.assertIsNotNone(out._prefetch,
                             "the file was handed straight to I2SOut, which "
                             "cannot feed it once a second client arrives")
        self.assertIs(self.engine.spawned, out._prefetch.ring,
                      "the pump was pointed at the file, not at its ring")

    def test_a_file_ends_by_itself_on_this_path(self):
        """Nothing serviced the prefetcher on the sink path at all.

        ``_next_block`` reads the file, and a sinking player never reaches
        ``_next_block``: the ring was primed once by ``play()`` and topped up
        never again. The WAV played a fraction of a second of real audio and
        then silence, and ``playing`` stayed True for ever, because a ring is
        a source that does not end. No board had run it.
        """
        sample = FakeSample(blocks=4)
        sample.__class__ = type("WaveFile", (FakeSample,), {})
        out, _transport = self.board(sample=sample)
        prefetch = out._prefetch
        block = bytearray(1024)
        for _ in range(40):
            if not out.playing:
                break
            out.service()
            self.engine.drain(block)       # the pump's thread, on a board
        self.assertFalse(out.playing, "the file never ended")
        self.assertEqual(pump_mod.owner().clients(), 0)
        self.assertGreater(prefetch.wrote, 0)

    def test_the_whole_file_is_handed_over_not_a_fraction_of_it(self):
        """The half of the same defect that is not about ``playing``.

        Primed once and never topped up, the ring held whatever ``play()``
        could fit and the rest of the file was never read at all.
        """
        sample = FakeSample(blocks=40)
        sample.__class__ = type("WaveFile", (FakeSample,), {})
        out, _transport = self.board(sample=sample)
        prefetch = out._prefetch
        block = bytearray(1024)
        for _ in range(200):
            if not out.playing:
                break
            out.service()
            self.engine.drain(block)
        self.assertEqual(prefetch.wrote, 40 * 1024,
                         "the file stopped being read part way through")

    # --- a fault that has been torn down is over (pydevices#45) ----------

    def test_the_next_player_gets_the_pump_back_once_the_fault_is_torn_down(
            self):
        """The fault sentence used to outlive the repair, so every later
        `AudioOut` in that boot played on `machine.I2S` -- `pumped` False,
        the DMA counter still, and nothing anywhere saying why."""
        out, _transport = self.board()
        self.assertTrue(out.pumped, "the first player never got the pump")
        out.stop()
        engine = pump_mod.owner()
        engine.note_fault("something in the chain was released")  # the fault
        engine.shutdown()                                         # the repair
        self.assertIsNotNone(engine.fault(),
                             "the sentence went with the teardown")
        self.assertFalse(engine.blocked(),
                         "the teardown left the refusal behind it")

        out2, _ = self.board()
        self.assertTrue(out2.pumped, "the speaker came back on machine.I2S")
        self.assertIsNone(out2.pump_refused)

    def test_a_pump_still_holding_a_fault_refuses_and_says_so_once(self):
        """The control, and the reason `blocked()` is not just `fault()`:
        a fault that has NOT been torn down still turns players away -- but
        out loud, and only once for that fault."""
        del sample_out._SAID[:]
        engine = pump_mod.owner()
        engine.note_fault("a node was released while it was playing")

        said = io.StringIO()
        with mock.patch("sys.stdout", said):
            out, transport = self.board()
        self.assertFalse(out.pumped, "a blocked pump took a client")
        self.assertIn("the audio pump is still down", said.getvalue())
        self.assertEqual(out.pump_refused,
                         "a node was released while it was playing")
        self.assertTrue(transport.data, "the audio stopped as well")

        again = io.StringIO()
        with mock.patch("sys.stdout", again):
            out2, _ = self.board()
        self.assertFalse(out2.pumped)
        self.assertNotIn("still down", again.getvalue(),
                         "it said the same thing twice")

    # --- the refusal is an object, not a line of stdout (audioif#2) ------

    def test_a_caller_that_asked_for_the_pump_gets_the_refusal_itself(self):
        """`I2SOut.retarget` raises a `ValueError` naming WHICH refusal it
        is -- a rate change, or a sample that is not signed 16-bit -- and
        until `raises=` existed only its wording came out."""
        out, _transport = self.board()
        i2s = FakeI2SOut.built[-1]

        def refuse(sample, *, loop=False):
            raise ValueError(
                "retarget cannot retune the bus; call play() instead")

        i2s.retarget = refuse
        engine = pump_mod.owner()
        with self.assertRaises(ValueError) as caught:
            engine.play(object(), FakeSample(), raises=True)
        self.assertIn("retune the bus", str(caught.exception))
        self.assertIs(engine.refusal(), caught.exception,
                      "the exception itself was thrown away")
        self.assertEqual(engine.clients(), 1,
                         "the client that could not sound was kept")

    def test_the_default_caller_still_gets_False_and_the_sentence(self):
        """The control for the one above: a player that never asked for the
        pump must not be handed the pump's exceptions."""
        out, _transport = self.board()
        i2s = FakeI2SOut.built[-1]

        def refuse(sample, *, loop=False):
            raise ValueError("retarget takes a signed 16-bit sample")

        i2s.retarget = refuse
        engine = pump_mod.owner()
        self.assertFalse(engine.play(object(), FakeSample()))
        self.assertIn("signed 16-bit", engine.fault())
        self.assertIsInstance(engine.refusal(), ValueError)


class ASecondClientJoinsAPumpThatIsSTILLRUNNING(PumpFixture):
    """`Pump._retarget()`'s live branch, which had no test of its own.

    Two branches leave this method and only one of them had ever been driven
    by a test. A pump that has already stopped -- which a looping player's
    first lap used to cause, and which
    ``docs/spikes/live-audio-path-land3.md`` records as the reason the gate
    was green -- goes down the ``shutdown()`` + ``spawn()`` path, and that
    path works. Fix the pump so it is still alive when the second client
    arrives and the other branch runs, for the first time, with nothing
    watching it.

    What the live branch has to do: swap the tail with no gap and no
    re-open, put BOTH clients on the root, and carry the loop flag with the
    tail it is swapping to.
    """

    def live_player(self, loop=False):
        """A player on a pump that is genuinely running when the next
        client arrives -- which is the whole point of this class."""
        out = self.player(loop=loop)
        self.assertTrue(self.engine.running(),
                        "the pump was already dead; this is the OTHER branch")
        return out

    def stream(self, fill=0x10, blocks=4):
        stream = pump_mod.attach_stream(FMT)
        self.addCleanup(stream.deinit)
        stream.write(bytes([fill]) * (1024 * blocks))
        return stream

    def test_the_audio_is_not_torn_down_to_let_a_client_in(self):
        self.live_player()
        before = len(self.engine.calls)
        self.stream()
        after = [name for name, _sample in self.engine.calls[before:]]
        self.assertIn("retarget", after,
                      "a live pump was not retargeted")
        self.assertNotIn("shutdown", after,
                         "the audio was stopped to let a second client in; "
                         "on a board that is a codec power cycle mid-note")

    def test_both_clients_are_on_the_root_the_pump_is_pulling(self):
        out = self.live_player()
        stream = self.stream()
        mixer = self.audiomixer.built[-1]
        self.assertIs(self.engine.spawned, mixer,
                      "the pump is still pulling the first client alone")
        self.assertEqual([sample for sample, _v, _l in mixer.played],
                         [out._engine._clients[0].sample, stream.ring])

    def test_the_second_clients_bytes_actually_come_out(self):
        """The one the probe found and no unit test could see.

        A pushed stream joining a live ``AudioOut`` contributed **nothing**
        to the sum for a whole afternoon, and the check that should have
        caught it was measuring its own window. Bytes, not calls: the block
        after the join has to be louder than the block before it.
        """
        clock = [0]
        transport = Recorder()
        out = sample_out.AudioOut(transport, chunk_ms=10)
        self.addCleanup(out.close)
        # A player whose own blocks are all zero, so every non-zero byte
        # downstream came from the client that joined and from nothing else.
        silent = FakeSample(blocks=256, block=1024)
        silent._blocks = [bytes(1024)] * 256
        with mock.patch.object(sample_out, "ticks_ms", lambda: clock[0]):
            out.play(silent)
            clock[0] += 20
            out.service()
            mark = len(transport.data)
            self.assertTrue(mark, "the first client made no sound either")

            self.stream(fill=0x10)
            for _ in range(4):
                clock[0] += 20
                out.service()
        mixed = bytes(transport.data[mark:])
        self.assertTrue(mixed, "nothing came out after the join at all")
        self.assertIn(
            0x10, mixed,
            "the stream that joined a live pump is silent in the mix")

    def test_a_looping_client_left_alone_on_a_live_pump_goes_on_looping(self):
        """The loop belongs to the TAIL, and the live branch swaps the tail.

        ``spawn()`` set the flag once, for the graph it was given. Swap that
        graph for a different one and the flag is still the old tail's: a
        player that was looping, left alone when the other client stops,
        stopped at the end of its first lap with nothing reporting it. It is
        the same defect ``_tail()`` had with mixer voices, one branch further
        in, and `audiopump.retarget()` had no way to say so until it grew a
        ``loop=`` of its own.
        """
        plain = self.player(sample=FakeSample())
        self.player(sample=FakeSample(), loop=True)
        self.assertFalse(self.engine.loop,
                         "the engine was looping before the swap, so this "
                         "row cannot tell the difference")
        plain.stop()
        self.assertEqual(pump_mod.owner().clients(), 1)
        self.assertEqual([name for name, _s in self.engine.calls][-1],
                         "retarget", "this went down the dead-pump branch")
        self.assertTrue(
            self.engine.loop,
            "the survivor was left on the pump with the OTHER tail's loop "
            "flag and stops at the end of its lap")

    def test_the_old_root_is_still_retired_one_generation_late(self):
        self.live_player()
        self.stream()
        first_root = self.audiomixer.built[-1]
        self.player()
        self.assertFalse(first_root.deinited,
                         "the pump may still have been inside it")

    def test_a_client_leaving_a_live_pump_leaves_the_others_sounding(self):
        one = self.live_player()
        two = self.player()
        self.stream()
        one.stop()
        self.assertEqual(pump_mod.owner().clients(), 2)
        self.assertTrue(self.engine.alive,
                        "one client leaving took the audio down")
        self.assertEqual(len(self.audiomixer.built[-1].voice), 2)
        two.stop()


class ATickInsideAnyOfThem(PumpFixture):
    """A service tick delivered at every step of a foreground call.

    On a board the tick rides the app's shared timer and arrives through
    ``micropython.schedule`` -- between the interpreter's own bytecodes -- so
    it lands wherever it lands. The P4 found one instance of that on
    2026-09-21: a tick inside `AudioOut.stop` saw a player that read exactly
    like a healthy old-path player, pulled a block, wrote it, and opened
    ``machine.I2S`` on the port the pump had just released. `_pumping` closed
    that one. It closes it for **one player's own** methods, and the thing
    being rearranged is global -- one pump, one graph, one peripheral -- so a
    tick servicing player B while player A is inside `Pump._retarget` walks
    into the same C module through a different Python object.

    This is `test_sequencer.ATickInsideAnotherOne`'s shape, with the line
    tracer of `test_scheduling_seam.ArmingNests`: deliver the tick at line 1,
    then line 2, then line 3 of the foreground call, and assert that what
    came out of the speaker is what came out with no tick at all.

    ``sys.settrace`` is CPython-only. What it proves is that the *code* has
    no window, not that a board's scheduler reaches any particular one.
    """

    #: Lines to inject at. Through `audiodev` alone, one `play()` on a live
    #: player is 427 lines, `close()` 90, `stream()` 91, `stop()` 72 and
    #: `pause()` 43 -- so this covers every line of every one of them. Past
    #: the end of a call the injection never fires, which the run asserts
    #: rather than assumes.
    POINTS = 430

    #: Matched on the MODULE name, not the filename: this file is called
    #: `test_pump.py`, which `endswith("pump.py")` cheerfully accepts, and
    #: the first draft of this class traced seventeen thousand lines of its
    #: own fixtures and injected the tick into `FakeSample.__init__`.
    AUDIODEV = ("audiodev.pump", "audiodev.sample_out")

    def fresh(self):
        """A world of its own: two players, both sounding through the pump."""
        pump_mod.forget()
        self.engine = FakeEngine()
        self.audiomixer = FakeAudiomixer()
        pump_mod._audiopump = self.engine
        pump_mod._looked = True
        pump_mod._owner = None
        sys.modules["audiomixer"] = self.audiomixer
        clock = [0]
        first = sample_out.AudioOut(Recorder(), chunk_ms=10)
        # The victim is an OLD-PATH player, which is the P4's own shape: the
        # firmware has a pump, one player is on it, and something else is
        # still pulling a graph on the interpreter and pushing it at the
        # transport. Its every tick writes, so a tick that is allowed to run
        # mid-rearrangement WRITES mid-rearrangement -- and a write is what
        # opens `machine.I2S` on the port the pump is holding.
        second = sample_out.AudioOut(Recorder(), chunk_ms=10, pump=False)
        with mock.patch.object(sample_out, "ticks_ms", lambda: clock[0]):
            first.play(FakeSample(blocks=256, block=1024))
            second.play(FakeSample(blocks=256, block=1024))
        return first, second, clock

    def inject(self, action, victim, clock, at):
        """Run *action* with one ``victim.service()`` at the *at*-th line.

        Lines executed by the tick itself are not counted, so ``at`` is an
        index into the FOREGROUND call and means the same thing whether the
        tick did anything or not.
        """
        seen = [0]
        fired = [0]
        inside = [False]

        def local(frame, event, _arg):
            if event != "line" or inside[0]:
                return local
            seen[0] += 1
            if seen[0] == at:
                inside[0] = True
                try:
                    fired[0] += 1
                    victim.service()
                finally:
                    inside[0] = False
            return local

        def tracer(frame, event, _arg):
            if (event == "call"
                    and frame.f_globals.get("__name__") in self.AUDIODEV):
                return local
            return None

        sys.settrace(tracer)
        try:
            action()
        finally:
            sys.settrace(None)
        return seen[0], fired[0]

    def outcome(self, at, what):
        """What a listener got, with the tick at *at* (None for no tick)."""
        first, second, clock = self.fresh()
        mark = len(second.transport.data)
        if what == "play":
            action = lambda: first.play(FakeSample(blocks=256,  # noqa: E731
                                                   block=1024))
        elif what == "stop":
            action = first.stop
        elif what == "close":
            action = first.close
        elif what == "pause":
            action = first.pause
        elif what == "stream":
            action = lambda: pump_mod.attach_stream(FMT)        # noqa: E731
        else:
            raise AssertionError(what)
        raised = None
        fired = 0
        with mock.patch.object(sample_out, "ticks_ms", lambda: clock[0]):
            # The victim is already behind its own schedule when the call
            # starts, so a tick landing inside it has real work to do. A tick
            # with nothing to pull cannot tell a latch from a coincidence.
            clock[0] += 60
            try:
                if at is None:
                    action()
                else:
                    _seen, fired = self.inject(action, second, clock, at)
            except Exception as exc:              # noqa: BLE001 - recorded
                raised = "%s: %s" % (type(exc).__name__, exc)
            # The same four ticks either way, AFTER the call: a tick turned
            # away is never a hole, it is a tick that does its work on the
            # next one, so the bytes have to be the same by the end.
            for _ in range(4):
                clock[0] += 20
                second.service()
        heard = bytes(second.transport.data[mark:])
        state = (raised, pump_mod.owner().clients(), second.playing,
                 self.engine.alive, second.transport.wrote_while_rearranging)
        first.close()
        second.close()
        return state, heard, fired

    def test_every_step_of_every_rearranging_method(self):
        """The same outcome, wherever the tick lands.

        Not the same bytes, and that is worth being precise about: a tick is
        TIME PASSING. One that lands before `stop()` hears two players and
        one that lands after hears one, and neither is wrong. What has to
        hold at every single line is this -- nothing raises, the arbitration
        ends where it would have ended, **no byte is written while the pump
        is being rearranged** (a write is what opens the peripheral, and on
        a board that is `machine.I2S` on the port the pump is holding), and
        the run is never more than one tick's worth of audio away from the
        uninterrupted one.
        """
        for what in ("play", "stop", "close", "pause", "stream"):
            with self.subTest(method=what):
                quiet, want, _ = self.outcome(None, what)
                self.assertIsNone(quiet[0], "the uninterrupted call raised")
                self.assertTrue(want, "the uninterrupted run made no sound")
                landed = 0
                for at in range(1, self.POINTS + 1):
                    state, heard, fired = self.outcome(at, what)
                    landed += fired
                    where = "a tick delivered at line %d of %s()" % (at, what)
                    self.assertEqual(state, quiet,
                                     "%s changed the outcome" % where)
                    self.assertLessEqual(
                        abs(len(heard) - len(want)), 4 * 1024,
                        "%s moved more than one tick's worth of audio"
                        % where)
                self.assertGreaterEqual(
                    landed, 5,
                    "the interrupt landed %d times in %s(), so this row is "
                    "not testing anything" % (landed, what))

    def test_a_turned_away_tick_is_counted(self):
        """The refusal has to be visible, and it has to be free.

        A counter that climbs is the app's sign that its timer is firing
        inside its own rearrangements. It is never a hole -- the buffer under
        it is hundreds of milliseconds deep and the next tick does the work.
        """
        before = pump_mod.reentered()
        for at in range(1, self.POINTS + 1):
            self.outcome(at, "play")
        self.assertGreater(pump_mod.reentered(), before,
                           "no tick was ever refused, so the latch is not "
                           "being held across anything")

    def test_health_carries_the_counter_that_had_no_reader(self):
        """`reentered()` was a number nothing surfaced (pydevices#38).

        Same answer audiocomponents#97 reached one layer up: not dropped, and
        not shown as a missed step either -- a refused tick costs nothing --
        but put on one health dict beside the counter that IS bad news, with
        each entry's meaning on the docstring so a reader does not have to
        guess which of them to worry about.
        """
        engine = pump_mod.owner()
        before = engine.health()
        for key in ("clients", "reentered", "dropped", "waited", "waited_us",
                    "blocks", "bytes", "running", "ahead_ms", "fault",
                    "blocked"):
            self.assertIn(key, before, "health() lost " + key)
        for at in range(1, self.POINTS + 1):
            self.outcome(at, "play")
        after = pump_mod.owner().health()
        self.assertGreater(after["reentered"], before["reentered"],
                           "the counter moved and health() did not carry it")
        self.assertEqual(after["dropped"], 0,
                         "a turned-away tick is not a dropped block, and "
                         "health() must not let them look the same")

    def test_health_never_raises_on_a_pump_that_has_nothing(self):
        """A status screen asks unconditionally, so this has to answer."""
        pump_mod.forget()
        report = pump_mod.owner().health()
        self.assertEqual(report["clients"], 0)
        self.assertFalse(report["running"])
        self.assertIsNone(report["fault"])

    def test_the_latch_unwinds_even_when_the_call_raises(self):
        """A rearrangement that throws must not leave the audio latched off.

        Every one of these is a try/finally for that reason: the latch left
        set is a player that never pulls another block, which is silence with
        no error anywhere.
        """
        out = self.player()
        self.engine._spawn_error = "the pump would not start"
        with mock.patch("sys.stdout", io.StringIO()):
            out.play(FakeSample())
        self.assertFalse(pump_mod.rearranging(),
                         "the latch was left holding after a failed play()")
        with self.assertRaises(ValueError):
            out.play(FakeSample(channel_count=1))     # _check_format raises
        self.assertFalse(pump_mod.rearranging(),
                         "the latch was left holding after a raise")

    def test_a_prefetcher_is_not_read_twice_over(self):
        """`Prefetch.service()` holds a block between calls.

        A second call arriving in the middle pulls the NEXT block over the
        top of the held one and the frames in between are gone -- a gap in
        the file that `wrote` never counts, because `wrote` only knows about
        what reached the ring.
        """
        sample = FakeSample(blocks=16, block=1024)
        sample.__class__ = type("WaveFile", (FakeSample,), {})
        prefetch = pump_mod.Prefetch(sample, frames=256)
        self.addCleanup(prefetch.deinit)

        reentered = []
        real = prefetch._service

        def nested(limit=None):
            if not reentered:
                reentered.append(prefetch.service())     # the tick
            return real(limit)

        prefetch._service = nested
        for _ in range(32):
            prefetch.service()
            if prefetch.fed():
                break
            prefetch.ring.next_block()
        self.assertEqual(reentered, [0],
                         "the re-entrant call read the file as well")
        self.assertEqual(prefetch.wrote, 16 * 1024,
                         "a block of the file went missing at the seam")

    def test_a_closed_stream_writes_nothing_rather_than_raising(self):
        """A tick can land between `deinit()`'s first two lines."""
        stream = pump_mod.attach_stream(FMT)
        stream.deinit()
        self.assertEqual(stream.write(b"\x00" * 64), 0)
        self.assertEqual(stream.space(), 0)
        self.assertEqual(stream.level(), 0)


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
        # Draining a block a round, because the pump does: a ring with room
        # for six blocks cannot hold eight, and a fixture whose ring was a
        # megabyte could not tell a producer that keeps reading from one that
        # stopped after the first pass.
        for _ in range(64):
            prefetch.service()
            if prefetch.fed():
                break
            prefetch.ring.next_block()
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
