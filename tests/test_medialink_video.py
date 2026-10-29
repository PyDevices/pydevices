# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""medialink's pictures: frames cut to the packet size and put back, a lost
packet costing one picture, sound going out between a picture's packets,
and the screen and the stand-in camera that the video examples use.
"""

import os
import tempfile
import time
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

import medialink
from medialink import packet
from test_medialink import FakeMic, FakeSpeaker, Format, Network, Pipe, Serve, pair, tone


def picture(size, seed=1):
    return bytes((seed * 31 + n * 7) & 0xFF for n in range(size))


def links(mtu=200):
    network = Network()
    a = medialink.Link(Pipe(network, "a", mtu=mtu))
    b = medialink.Link(Pipe(network, "b", mtu=mtu))
    a.peer = "b"
    return network, a, b


def send_whole(video, payload):
    """Send one picture and service until it has all gone."""
    assert video.send(payload)
    for _ in range(10000):
        if video.ready:
            return
        video.service()
        time.sleep(0.0005)
    raise AssertionError("the picture never finished sending")


class Pictures(unittest.TestCase):
    def test_a_picture_arrives_byte_for_byte(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=50_000_000)
        receiver = medialink.Video(b)
        jpeg = picture(5000)
        send_whole(sender, jpeg)
        frame = receiver.receive()
        self.assertEqual(frame.payload, jpeg)
        self.assertEqual(frame.codec, medialink.JPEG)
        self.assertEqual(sender.stats["sent"], 1)
        self.assertEqual(receiver.stats["received"], 1)

    def test_a_lost_packet_drops_that_picture_not_the_stream(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=50_000_000, burst=1)
        receiver = medialink.Video(b)
        first, second, third = picture(900, 1), picture(900, 2), picture(900, 3)
        send_whole(sender, first)
        # The second picture loses its third packet on the way.
        self.assertTrue(sender.send(second))
        sender.service()
        network.down = True
        while sender._frag < 3:
            sender.service()
        network.down = False
        while not sender.ready:
            sender.service()
        send_whole(sender, third)
        got = b.frames(packet.VIDEO)
        self.assertEqual([f.payload for f in got], [first, third])
        self.assertEqual(b.stats["incomplete"], 1)
        self.assertEqual(b.stats["lost"], 1)
        self.assertIsNone(receiver.receive())

    def test_packets_out_of_order_still_make_the_picture(self):
        network, a, b = links()
        jpeg = picture(1000)
        a.send_video(jpeg)
        b.transport.queue.reverse()  # the last packet first
        self.assertEqual(b.frames(packet.VIDEO)[0].payload, jpeg)

    def test_only_the_newest_picture_waits(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=50_000_000)
        receiver = medialink.Video(b)
        for seed in range(5):
            send_whole(sender, picture(300, seed))
        frame = receiver.receive()
        self.assertEqual(frame.payload, picture(300, 4))
        self.assertEqual(receiver.stats["replaced"], 1)  # the inbox keeps two
        self.assertEqual(b.stats["dropped"], 3)

    def test_a_new_picture_waits_for_the_last_to_go(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=8000, burst=1)  # a kilobyte a second
        self.assertTrue(sender.send(picture(2000)))
        self.assertFalse(sender.ready)
        self.assertFalse(sender.send(picture(2000)))
        self.assertEqual(sender.stats["skipped"], 1)

    def test_the_pace_holds_to_the_bandwidth(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=400_000, burst=2)  # 50 kB/s
        start = time.monotonic()
        send_whole(sender, picture(10000))
        seconds = time.monotonic() - start
        # 10 kB at 50 kB/s is 0.2 s, less the first burst.
        self.assertGreater(seconds, 0.12)
        self.assertLess(seconds, 1.0)

    def test_no_peer_sends_nothing(self):
        network = Network()
        a = medialink.Link(Pipe(network, "a"))
        sender = medialink.Video(a)
        self.assertFalse(sender.send(picture(100)))


class SoundFirst(unittest.TestCase):
    def test_sound_goes_out_between_a_pictures_packets(self):
        network, a, b = links()
        sender = medialink.Video(a, bandwidth=50_000_000, burst=2)
        self.assertTrue(sender.send(picture(2000)))  # 11 packets; 2 have gone
        a.send_audio(b"voice")
        while not sender.ready:
            sender.service()
        kinds = [packet.unpack(data, len(data))[0] for data, _source in b.transport.queue]
        self.assertEqual(kinds[2], packet.AUDIO)
        self.assertEqual(kinds.count(packet.VIDEO), 11)

    def test_the_intercom_leaves_pictures_for_the_screen(self):
        fmt = Format(16000, 1)
        network, a, b = links(mtu=1400)
        speaker = FakeSpeaker(fmt)
        listener = medialink.Intercom(b, None, speaker, prebuffer=1)
        receiver = medialink.Video(b)
        a.send_audio(b"\x01\x00" * 320, flags=packet.START)
        a.send_video(picture(3000))
        a.send_audio(b"\x02\x00" * 320, flags=packet.END)
        listener.service()
        # Both sound frames played (a speaker may get silence after them).
        self.assertEqual(bytes(speaker.got[:1280]), b"\x01\x00" * 320 + b"\x02\x00" * 320)
        frame = receiver.receive()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.payload, picture(3000))

    def test_pictures_alone_do_not_hold_the_floor(self):
        network, a, b = pair(floor_timeout_ms=60)
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(a.request_floor())
        serve.stop()
        b.poll()
        self.assertEqual(b.floor, medialink.LISTENING)
        # The talker goes quiet but its camera keeps sending.
        for _ in range(8):
            a.send_video(picture(100))
            b.poll()
            time.sleep(0.015)
        self.assertEqual(b.floor, medialink.IDLE)


class ARestartedPeer(unittest.TestCase):
    def test_a_talker_asks_again_after_the_listener_restarts(self):
        network, a, b = pair()
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(a.request_floor())
        serve.stop()
        # The listener restarts: a new link at the same address says hello.
        del network.ends["b"]
        b2 = medialink.Link(Pipe(network, "b"))
        serve = Serve(a)
        try:
            b2.connect("a")
        finally:
            serve.stop()
        self.assertEqual(a.floor, medialink.IDLE)

    def test_the_talker_keeps_the_floor_when_the_listener_first_speaks_up(self):
        network, a, b = pair()
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(a.request_floor())
        serve.stop()
        serve = Serve(a)
        try:
            self.assertFalse(b.request_floor())
        finally:
            serve.stop()
        self.assertEqual(a.floor, medialink.TALKING)


class ATalkerWithNoSpeaker(unittest.TestCase):
    def test_it_talks_and_closes(self):
        fmt = Format(16000, 1)
        network, a, b = pair()
        talker = medialink.Intercom(a, FakeMic(fmt, tone(3200)), None)
        serve = Serve(b)
        try:
            a.connect("b")
            self.assertTrue(talker.press())
            for _ in range(20):
                talker.service()
            talker.close()
        finally:
            serve.stop()
        self.assertGreaterEqual(talker.stats["sent"], 5)


class Display:
    """A displaydev-shaped display that remembers what was put on it."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.blits = []
        self.shown = 0

    def fill_rect(self, x, y, w, h, c):
        pass

    def blit_rect(self, buf, x, y, w, h):
        self.blits.append((x, y, w, h, bytes(buf)))

    def show(self):
        self.shown += 1


def jpeg_of(width, height):
    import jpegio

    pixels = bytearray(width * height * 2)
    for n in range(0, len(pixels), 2):
        pixels[n] = n & 0xFF
    return jpegio.JpegEncoder(quality=90).encode(pixels, width, height)


try:
    import PIL  # noqa: F401  (jpegio on CPython decodes with Pillow)

    HAVE_PILLOW = True
except ImportError:
    HAVE_PILLOW = False


@unittest.skipUnless(HAVE_PILLOW, "jpegio on CPython needs Pillow")
class TheScreen(unittest.TestCase):
    def test_a_small_picture_is_centred(self):
        display = Display(320, 240)
        screen = medialink.Screen(display)
        self.assertEqual(screen.show(jpeg_of(160, 120)), (160, 120))
        x, y, w, h, pixels = display.blits[-1]
        self.assertEqual((x, y, w, h), (80, 60, 160, 120))
        self.assertEqual(len(pixels), 160 * 120 * 2)
        self.assertGreaterEqual(display.shown, 1)

    def test_a_big_picture_is_halved_until_it_fits(self):
        display = Display(320, 240)
        screen = medialink.Screen(display)
        self.assertEqual(screen.show(jpeg_of(640, 480)), (320, 240))
        self.assertEqual(screen.show(jpeg_of(1280, 400)), (320, 100))

    def test_a_picture_it_cannot_read_is_counted_not_raised(self):
        display = Display(320, 240)
        screen = medialink.Screen(display)
        self.assertIsNone(screen.show(b"not a picture"))
        self.assertEqual(screen.errors, 1)
        self.assertEqual(screen.show(jpeg_of(160, 120)), (160, 120))


class TheFileCamera(unittest.TestCase):
    def test_it_hands_out_the_pictures_in_order_round_and_round(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, data in (("b.jpg", b"two"), ("a.jpg", b"one"), ("notes.txt", b"x")):
                with open(os.path.join(folder, name), "wb") as file:
                    file.write(data)
            camera = medialink.FileCamera(folder)
            self.assertEqual([camera.take() for _ in range(3)], [b"one", b"two", b"one"])

    def test_an_empty_folder_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                medialink.FileCamera(folder)


if __name__ == "__main__":
    unittest.main()
