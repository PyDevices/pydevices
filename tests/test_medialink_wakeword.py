"""medialink.WakeWord: a wake word opens the hands-free floor.

The model and the feature frontend are stand-ins here, since tflite and
audiofeatures are firmware modules; what is tested is when the floor opens
and closes, and the detector's sliding window, which follows ESPHome's
micro_wake_word.
"""

import json
import os
import tempfile
import threading
import time
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

import medialink
from medialink import codec
from test_medialink import FakeMic, FakeSpeaker, Format, Serve, pair, tone
from test_medialink_voice import FRAME, hiss

RATE = 16000
FRAME_MS = 20


class Spotter:
    """Hears the wake word in the frames whose numbers it is given."""

    name = "hey_jarvis"

    def __init__(self, at=()):
        self.at = set(at)
        self.frame = 0
        self.resets = 0

    def feed(self, pcm, rate, channels):
        self.frame += 1
        return self.frame in self.at

    def reset(self):
        self.resets += 1


class Voice:
    """Speaking in the frames whose numbers it is given."""

    level = 0
    detector = "fake"

    def __init__(self, at=()):
        self.at = set(at)
        self.frame = 0

    def feed(self, pcm):
        self.frame += 1
        return self.frame in self.at

    def reset(self):
        pass


def run(wake, count):
    """Feed ``count`` frames; the numbers of those that said send."""
    return [n for n in range(1, count + 1) if wake.feed(bytes(FRAME))]


class Gate(unittest.TestCase):
    def test_speech_without_the_wake_word_sends_nothing(self):
        wake = medialink.WakeWord(spotter=Spotter(), voice=Voice(range(1, 50)))
        self.assertEqual(run(wake, 60), [])

    def test_the_wake_word_opens_and_silence_after_the_listen_time_closes(self):
        # The word at frame 10; 100 ms to start speaking (5 frames); then
        # speech from 12 to 30.
        wake = medialink.WakeWord(spotter=Spotter([10]), voice=Voice(range(12, 31)), listen_ms=100)
        self.assertEqual(run(wake, 60), list(range(10, 31)))
        self.assertEqual(wake.heard, 1)

    def test_no_speech_after_the_word_closes_after_the_listen_time(self):
        wake = medialink.WakeWord(spotter=Spotter([10]), voice=Voice(), listen_ms=100)
        self.assertEqual(run(wake, 60), list(range(10, 15)))

    def test_speech_after_the_turn_needs_the_word_again(self):
        wake = medialink.WakeWord(spotter=Spotter([5, 40]), voice=Voice(list(range(5, 15)) + list(range(25, 50))), listen_ms=60)
        self.assertEqual(run(wake, 60), list(range(5, 15)) + list(range(40, 50)))

    def test_reset_closes_the_floor_and_forgets(self):
        spotter = Spotter([3])
        wake = medialink.WakeWord(spotter=spotter, voice=Voice(range(1, 100)))
        run(wake, 5)
        self.assertTrue(wake.speaking)
        wake.reset()
        self.assertFalse(wake.speaking)
        self.assertEqual(spotter.resets, 1)
        self.assertEqual(run(wake, 5), [])

    def test_it_names_the_word(self):
        wake = medialink.WakeWord(spotter=Spotter(), voice=Voice())
        self.assertEqual(wake.detector, "wake word hey_jarvis")


class Model:
    """A model whose probability is given by the call, a uint8 like microWakeWord's."""

    input_shape = [(1, 3, 40)]

    def __init__(self, probabilities):
        self.probabilities = list(probabilities)
        self.calls = 0
        self.inputs = []

    def predict(self, fills):
        buffer = bytearray(3 * 40)
        fills[0](buffer, None, None)
        self.inputs.append(bytes(buffer))
        p = self.probabilities[self.calls] if self.calls < len(self.probabilities) else 0
        self.calls += 1
        return [[[p]]]


class Frontend:
    """One 10 ms slice per 160 samples, its bytes the slice's number."""

    FEATURE_SIZE = 40

    def __init__(self):
        self.pending = 0
        self.made = 0

    def feed(self, pcm, rate, channels):
        self.pending += len(pcm) // 2 // 160

    def readinto(self, buf):
        count = min(self.pending, len(buf) // 40)
        for i in range(count):
            self.made += 1
            buf[i * 40:(i + 1) * 40] = bytes([self.made % 256]) * 40
        self.pending -= count
        return count

    def reset(self):
        self.pending = 0


def manifest(folder, cutoff=0.5, window=3):
    path = os.path.join(folder, "word.json")
    with open(path, "w") as f:
        json.dump({"wake_word": "Hey Jarvis", "model": "word.tflite",
                   "micro": {"probability_cutoff": cutoff, "sliding_window_size": window}}, f)
    return path


class MicroWakeWord(unittest.TestCase):
    def spot(self, probabilities, frames, warm_up=0):
        with tempfile.TemporaryDirectory() as folder:
            spotter = medialink.MicroWakeWord(manifest(folder), model=Model(probabilities),
                                              frontend=Frontend(), warm_up=warm_up)
        # Each 20 ms frame is two slices; every three slices run the model.
        return spotter, [n for n in range(1, frames + 1) if spotter.feed(bytes(FRAME), RATE, 1)]

    def test_it_reads_the_manifest(self):
        spotter, _ = self.spot([], 0)
        self.assertEqual(spotter.name, "Hey Jarvis")
        self.assertEqual(spotter.cutoff, 127)
        self.assertEqual(spotter.window, 3)
        self.assertEqual(spotter.stride, 3)

    def test_the_model_sees_stride_slices_in_order(self):
        spotter, _ = self.spot([], 3)
        self.assertEqual(spotter.model.calls, 2)
        self.assertEqual(spotter.model.inputs[0], bytes([1]) * 40 + bytes([2]) * 40 + bytes([3]) * 40)
        self.assertEqual(spotter.model.inputs[1], bytes([4]) * 40 + bytes([5]) * 40 + bytes([6]) * 40)

    def test_one_high_probability_is_not_enough(self):
        _, fired = self.spot([0, 0, 255, 0, 0, 0], 12)
        self.assertEqual(fired, [])

    def test_the_window_mean_over_the_cutoff_fires_once(self):
        # The model runs every third slice, and a frame is two slices. Calls
        # 3 to 8 are over the cutoff; the window's mean passes it at call 5,
        # slice 15, which is in frame 8. It stays high, but fires again only
        # after six slices below the cutoff.
        _, fired = self.spot([0, 0] + [150] * 6 + [0, 0], 20, warm_up=6)
        self.assertEqual(fired, [8])

    def test_it_fires_again_after_falling_and_warming_up(self):
        # The window fills at call 6 (slice 18, frame 9), and again at call
        # 12 (slice 36, frame 18) after the quiet between.
        probabilities = [0] * 3 + [150] * 3 + [0] * 3 + [150] * 3
        _, fired = self.spot(probabilities, 20, warm_up=6)
        self.assertEqual(fired, [9, 18])

    def test_nothing_fires_in_the_warm_up(self):
        _, fired = self.spot([200] * 10, 20, warm_up=100)
        self.assertEqual(fired, [])


class HandsFree(unittest.TestCase):
    def test_the_wake_word_opens_the_floor_and_speech_before_it_is_not_sent(self):
        fmt = Format(RATE, 1)
        # Speech with no wake word, quiet, the word and speech, then quiet.
        sound = hiss(8000) + tone(16000, freq=300) + hiss(16000, seed=2) + tone(16000) + hiss(32000, seed=3)
        word_frame = 40000 // (FRAME // 2) + 1  # the first frame of the second tone
        network, a, b = pair()
        mic = FakeMic(fmt, sound)
        heard = FakeSpeaker(fmt)
        voice = medialink.VoiceActivity(detector="level", hold_ms=40)
        wake = medialink.WakeWord(spotter=Spotter([word_frame]), voice=voice, listen_ms=40)
        talker = medialink.Intercom(a, mic, FakeSpeaker(fmt), voice=wake, codec=codec.PCM16)
        listener = medialink.Intercom(b, None, heard, prebuffer=2)
        serve = Serve(b)
        a.connect("b")
        serve.stop()
        running = [True]

        def listen():
            while running[0]:
                listener.service()
                time.sleep(0.001)

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        try:
            while mic.at < len(sound):
                talker.service()
                time.sleep(0.001)
            for _ in range(200):
                talker.service()
                time.sleep(0.001)
        finally:
            running[0] = False
            thread.join()
        got = bytes(heard.got)
        self.assertEqual(talker.stats["voice_turns"], 1)
        self.assertEqual(listener.stats["spurts"], 1)
        self.assertFalse(talker.talking)
        self.assertIn(tone(16000)[FRAME * 10:FRAME * 14], got)
        self.assertNotIn(tone(16000, freq=300)[FRAME * 10:FRAME * 14], got)


if __name__ == "__main__":
    unittest.main()
