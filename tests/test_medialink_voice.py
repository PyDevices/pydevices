# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""medialink's hands-free pieces: voice activity, an intercom that takes the
floor when someone speaks, one that only listens or only sends, and events
such as a doorbell's ring."""

import random
import struct
import threading
import time
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

import medialink
from medialink import codec
from test_medialink import FakeMic, FakeSpeaker, Format, Serve, pair, tone

try:
    import audiofeatures

    HAVE_FEATURES = hasattr(audiofeatures.Frontend(), "speaking")
except ImportError:
    HAVE_FEATURES = False

FRAME = 640  # 20 ms at 16 kHz, mono 16-bit


def hiss(samples, level=30, seed=1):
    rng = random.Random(seed)
    return struct.pack("<%dh" % samples, *(rng.randint(-level, level) for _ in range(samples)))


def frames(pcm):
    return [pcm[i:i + FRAME] for i in range(0, len(pcm), FRAME)]


class Level(unittest.TestCase):
    def test_quiet_then_a_tone_then_quiet(self):
        voice = medialink.VoiceActivity(detector="level", hold_ms=50)
        self.assertEqual(voice.detector, "level")
        heard = [voice.feed(f) for f in frames(hiss(16000))]
        self.assertFalse(any(heard))
        heard = [voice.feed(f) for f in frames(tone(8000))]
        self.assertTrue(all(heard[1:]))
        time.sleep(0.06)
        self.assertFalse(voice.feed(hiss(320, seed=2)))

    def test_a_steady_noise_becomes_the_floor(self):
        voice = medialink.VoiceActivity(detector="level", hold_ms=0)
        loud = hiss(16000 * 5, level=3000)
        heard = [voice.feed(f) for f in frames(loud)]
        self.assertFalse(any(heard[-50:]))

    @unittest.skipUnless(HAVE_FEATURES, "needs audiofeatures with voice activity")
    def test_audiofeatures_is_the_default_where_there_is_one(self):
        voice = medialink.VoiceActivity(hold_ms=0)
        self.assertEqual(voice.detector, "audiofeatures")
        heard = [voice.feed(f) for f in frames(hiss(16000))]
        self.assertFalse(any(heard))


class Events(unittest.TestCase):
    def test_an_event_arrives_once(self):
        network, a, b = pair()
        serve = Serve(b)
        try:
            a.connect("b")
            a.send_event("ring")
            a.send_event(b"\x01\x02")
        finally:
            serve.stop()
        self.assertEqual(b.events(), [b"ring", b"\x01\x02"])
        self.assertEqual(b.events(), [])

    def test_an_event_to_nobody_fails(self):
        network, a, b = pair()
        a.peer = "nobody"
        with self.assertRaises(medialink.PeerUnreachable):
            a.send_event("ring")


class HandsFree(unittest.TestCase):
    def test_speech_takes_the_floor_and_silence_gives_it_back(self):
        fmt = Format(16000, 1)
        # Half a second of room, half a second of "speech", two of room.
        sound = hiss(8000) + tone(8000) + hiss(32000, seed=3)
        network, a, b = pair()
        mic = FakeMic(fmt, sound)
        heard = FakeSpeaker(fmt)
        voice = medialink.VoiceActivity(detector="level", hold_ms=40)
        talker = medialink.Intercom(a, mic, FakeSpeaker(fmt), voice=voice, codec=codec.PCM16)
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
        self.assertEqual(talker.stats["voice_turns"], 1)
        self.assertFalse(talker.talking)
        self.assertEqual(a.floor, medialink.IDLE)
        self.assertEqual(listener.stats["spurts"], 1)
        # The tone arrived, from a little before it was first heard.
        self.assertIn(tone(8000)[:FRAME * 4], bytes(heard.got))

    def test_no_voice_means_no_microphone(self):
        fmt = Format(16000, 1)
        network, a, b = pair()
        mic = FakeMic(fmt, tone(1600))
        intercom = medialink.Intercom(a, mic, FakeSpeaker(fmt))
        for _ in range(5):
            intercom.service()
        self.assertEqual(mic.opened, 0)

    def test_a_listener_without_a_microphone_and_a_sender_without_a_speaker(self):
        fmt = Format(16000, 1)
        network, a, b = pair()
        mic = FakeMic(fmt, tone(3200))
        heard = FakeSpeaker(fmt)
        sender = medialink.Intercom(a, mic, None, codec=codec.PCM16)
        listener = medialink.Intercom(b, None, heard, prebuffer=1)
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(sender.press())
        serve.stop()
        while mic.at < 3200 * 2:
            sender.service()
            listener.service()
        sender.release()
        for _ in range(5):
            sender.service()
            listener.service()
        # The turn plays out with a tenth of a second of silence after it.
        got = bytes(heard.got)
        self.assertEqual(got[:6400], tone(3200))
        self.assertEqual(got[6400:], bytes(len(got) - 6400))
        sender.close()
        listener.close()

    def test_a_chime_plays_and_holds_back_listening(self):
        fmt = Format(16000, 1)
        network, a, b = pair()
        mic = FakeMic(fmt, tone(3200))
        heard = FakeSpeaker(fmt)
        voice = medialink.VoiceActivity(detector="level")
        intercom = medialink.Intercom(a, mic, heard, voice=voice)
        intercom.play(b"\x01\x00" * 800)
        self.assertTrue(intercom._pending)
        intercom._listen_step()
        self.assertEqual(mic.opened, 0)  # the chime is still to play
        intercom.service()
        # The chime plays out with silence after it, like a turn.
        got = bytes(heard.got)
        self.assertEqual(got[:1600], b"\x01\x00" * 800)
        self.assertEqual(got[1600:], bytes(len(got) - 1600))
        intercom.service()
        self.assertEqual(mic.opened, 1)
        intercom.close()


if __name__ == "__main__":
    unittest.main()
