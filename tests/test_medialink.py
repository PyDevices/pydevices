# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""medialink: the packet, the codecs, the link's control channel and floor,
and a press-to-talk exchange between two intercoms.

Two links in one process need somebody to answer while the other waits for
an acknowledgement, so the far side runs its loop on a thread. The links
talk over :class:`Pipe`, an in-memory transport that can lose the network
and move a peer to a new address, and over real UDP on localhost.
"""

import math
import struct
import threading
import time
import unittest

import _env  # noqa: F401  (puts lib/ on sys.path)

import medialink
from medialink import codec, packet
from medialink.transport import Transport, UDPTransport


class Pipe(Transport):
    """One end of an in-memory network. ``down`` drops every datagram."""

    def __init__(self, network, address, mtu=1400):
        self.network = network
        self.address = address
        self.mtu = mtu
        self.queue = []
        network.ends[address] = self

    def send(self, data, address):
        if self.network.down:
            raise OSError(101, "network unreachable")
        far = self.network.ends.get(address)
        if far is not None:
            with self.network.lock:
                far.queue.append((bytes(data), self.address))

    def recv_into(self, buf):
        with self.network.lock:
            if not self.queue:
                return 0, None
            data, source = self.queue.pop(0)
        buf[: len(data)] = data
        return len(data), source

    def move(self, address):
        del self.network.ends[self.address]
        self.address = address
        self.network.ends[address] = self


class Network:
    def __init__(self):
        self.ends = {}
        self.down = False
        self.lock = threading.Lock()


class Serve:
    """Run ``link.poll()`` on a thread until stopped."""

    def __init__(self, link):
        self.link = link
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            self.link.poll()
            time.sleep(0.001)

    def stop(self):
        self.running = False
        self.thread.join(2)


def pair(**kwargs):
    network = Network()
    a = medialink.Link(Pipe(network, "a"), **kwargs)
    b = medialink.Link(Pipe(network, "b"), **kwargs)
    return network, a, b


def tone(samples, rate=16000, freq=440, level=8000):
    return struct.pack(
        "<%dh" % samples,
        *(int(level * math.sin(2 * math.pi * freq * n / rate)) for n in range(samples)),
    )


class TheClock(unittest.TestCase):
    def test_circuitpython_clock_keeps_the_common_period_across_its_wrap(self):
        # CircuitPython's supervisor.ticks_ms wraps at 2**29; medialink's
        # ticks run on 2**30 like MicroPython's, so a peer on either reads
        # the same differences.
        import importlib
        import sys
        import types

        raw = [(1 << 29) - 30]
        fake = types.ModuleType("supervisor")
        fake.ticks_ms = lambda: raw[0]
        # Other tests may have given the time module MicroPython's ticks;
        # CircuitPython's has none, so hide them while _compat loads.
        hidden = {}
        for name in ("ticks_ms", "sleep_ms"):
            if hasattr(time, name):
                hidden[name] = getattr(time, name)
                delattr(time, name)
        sys.modules["supervisor"] = fake
        try:
            compat = importlib.reload(importlib.import_module("medialink._compat"))
            before = compat.ticks_ms()
            raw[0] = 20  # 50 ms later, past the wrap
            after = compat.ticks_ms()
            self.assertEqual(compat.ticks_diff(after, before), 50)
            self.assertEqual(after, 1 << 29 | 20)
            raw[0] = (1 << 29) - 1
            self.assertEqual(compat.ticks_ms(), (1 << 30) - 1)
            raw[0] = 5  # the second wrap returns to the bottom of 2**30
            self.assertEqual(compat.ticks_ms(), 5)
        finally:
            del sys.modules["supervisor"]
            for name, value in hidden.items():
                setattr(time, name, value)
            importlib.reload(importlib.import_module("medialink._compat"))


class ThePacket(unittest.TestCase):
    def test_round_trip(self):
        data = packet.pack(packet.AUDIO, 1, packet.START, 2, 3, 0x1234, 0xDEADBEEF, b"xy")
        self.assertEqual(len(data), packet.HEADER_SIZE + 2)
        self.assertEqual(
            packet.unpack(data, len(data)),
            (packet.AUDIO, 1, packet.START, 2, 3, 0x1234, 0xDEADBEEF),
        )

    def test_strangers_are_ignored(self):
        self.assertIsNone(packet.unpack(b"GET / HTTP/1.0\r\n", 16))
        self.assertIsNone(packet.unpack(b"ML", 2))


class TheCodecs(unittest.TestCase):
    def test_pcm_is_untouched(self):
        pcm = tone(320)
        self.assertEqual(codec.PCM16.decode(codec.PCM16.encode(pcm)), pcm)

    def test_adpcm_is_a_quarter_and_close(self):
        pcm = tone(640)
        encoder = codec.ADPCM.__class__()
        encoder.encode(pcm[:640])
        payload = encoder.encode(pcm[640:])  # the second frame of a stream
        pcm = pcm[640:]
        self.assertEqual(len(payload), 4 + 160)
        back = codec.ADPCM.decode(payload)
        self.assertEqual(len(back), len(pcm))
        a = struct.unpack("<320h", pcm)
        b = struct.unpack("<320h", back)
        noise = sum((x - y) ** 2 for x, y in zip(a, b))
        signal = sum(x * x for x in a)
        self.assertGreater(10 * math.log10(signal / noise), 20)  # dB

    def test_choose_fits_the_link(self):
        self.assertIs(codec.choose(2000000, 16000), codec.PCM16)
        self.assertIs(codec.choose(100000, 16000), codec.ADPCM)
        with self.assertRaises(ValueError):
            codec.choose(20000, 16000)


class APeerThatIsNotThere(unittest.TestCase):
    def test_fails_at_once_by_default(self):
        network = Network()
        link = medialink.Link(Pipe(network, "a"), ack_timeout_ms=50)
        sent = []
        original = link.transport.send
        link.transport.send = lambda data, address: (sent.append(data), original(data, address))
        start = time.monotonic()
        with self.assertRaises(medialink.PeerUnreachable):
            link.connect("nobody")
        self.assertEqual(len(sent), 1)
        self.assertLess(time.monotonic() - start, 0.5)

    def test_retries_n_times_then_fails(self):
        network = Network()
        link = medialink.Link(Pipe(network, "a"), ack_timeout_ms=30, retries=3)
        sent = []
        original = link.transport.send
        link.transport.send = lambda data, address: (sent.append(data), original(data, address))
        with self.assertRaises(medialink.PeerUnreachable):
            link.connect("nobody")
        self.assertEqual(len(sent), 4)
        self.assertEqual(link.stats["retries"], 3)

    def test_a_down_network_is_a_failed_send_not_a_crash(self):
        network, a, b = pair(ack_timeout_ms=30)
        network.down = True
        with self.assertRaises(medialink.PeerUnreachable):
            a.connect("b")
        self.assertGreater(a.stats["send_errors"], 0)


class TheFloor(unittest.TestCase):
    def setUp(self):
        self.network, self.a, self.b = pair(floor_timeout_ms=200)
        self.serve = Serve(self.b)
        self.a.connect("b")

    def tearDown(self):
        self.serve.stop()

    def test_granted_then_released(self):
        self.assertTrue(self.a.request_floor())
        self.assertEqual(self.a.floor, medialink.TALKING)
        time.sleep(0.02)
        self.assertEqual(self.b.floor, medialink.LISTENING)
        self.a.release_floor()
        time.sleep(0.02)
        self.assertEqual(self.b.floor, medialink.IDLE)

    def test_the_listener_is_refused(self):
        self.assertTrue(self.a.request_floor())
        time.sleep(0.02)
        self.serve.stop()
        self.assertFalse(self.b.request_floor())
        self.assertEqual(self.b.stats["denied"], 1)
        self.serve = Serve(self.b)

    def test_a_silent_talker_loses_the_floor(self):
        self.assertTrue(self.a.request_floor())
        time.sleep(0.02)
        self.assertEqual(self.b.floor, medialink.LISTENING)
        time.sleep(0.3)
        self.assertEqual(self.b.floor, medialink.IDLE)
        self.assertEqual(self.b.stats["floor_timeouts"], 1)

    def test_both_at_once_one_wins(self):
        self.serve.stop()
        results = {}

        def ask(name, link):
            results[name] = link.request_floor()

        # Each side asks while the other is asking. Whoever's request lands
        # first, or the lower token in a dead heat, gets it; never both.
        threads = [threading.Thread(target=ask, args=(n, l)) for n, l in (("a", self.a), ("b", self.b))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertEqual(sorted(results.values()), [False, True], results)
        winner, loser = (self.a, self.b) if results["a"] else (self.b, self.a)
        loser.poll()
        self.assertEqual(winner.floor, medialink.TALKING)
        self.assertEqual(loser.floor, medialink.LISTENING)
        self.serve = Serve(self.b)

    def test_a_dead_heat_goes_to_the_lower_token(self):
        self.serve.stop()
        # b is mid-request when a's request arrives.
        self.b.token = self.a.token - 1
        self.b._pending_take = True
        self.serve = Serve(self.b)
        self.assertFalse(self.a.request_floor())
        self.serve.stop()
        self.b._pending_take = False
        self.assertNotEqual(self.b.floor, medialink.LISTENING)
        self.serve = Serve(self.b)


class Media(unittest.TestCase):
    def test_frames_arrive_in_order_with_an_age(self):
        network, a, b = pair(keepalive_ms=10)
        serve = Serve(b)
        a.connect("b")
        serve.stop()
        b.poll()
        time.sleep(0.03)
        b.poll()  # b pings a; a answers when it next polls
        a.poll()
        time.sleep(0.01)
        b.poll()
        for index in range(5):
            a.send_audio(bytes([index]) * 64)
        frames = b.frames()
        self.assertEqual([f.payload[0] for f in frames], [0, 1, 2, 3, 4])
        self.assertIsNotNone(b.offset_ms)
        # One clock here, so the true age is about 0; the offset is good to
        # half a round trip.
        for frame in frames:
            self.assertLessEqual(abs(frame.age), b.best_rtt_ms // 2 + 2)

    def test_a_big_frame_is_cut_and_rejoined(self):
        network = Network()
        a = medialink.Link(Pipe(network, "a", mtu=200))
        b = medialink.Link(Pipe(network, "b", mtu=200))
        a.peer = "b"
        picture = bytes(range(256)) * 20
        a.send_video(picture)
        frames = b.frames()
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].kind, packet.VIDEO)
        self.assertEqual(frames[0].payload, picture)

    def test_loss_is_counted(self):
        network = Network()
        a = medialink.Link(Pipe(network, "a"))
        b = medialink.Link(Pipe(network, "b"))
        a.peer = "b"
        a.send_audio(b"one")
        network.down = True
        a.send_audio(b"lost")
        a.send_audio(b"lost")
        network.down = False
        a.send_audio(b"four")
        self.assertEqual([f.payload for f in b.frames()], [b"one", b"four"])
        self.assertEqual(b.stats["lost"], 2)


class Recovery(unittest.TestCase):
    def test_a_peer_at_a_new_address_is_found_again(self):
        network, a, b = pair(keepalive_ms=20, dead_ms=100)
        serve = Serve(b)
        a.connect("b")
        time.sleep(0.05)
        a.poll()
        self.assertTrue(a.alive)
        # The network drops, and a comes back at a new address.
        network.down = True
        time.sleep(0.2)
        a.poll()
        self.assertFalse(a.alive)
        a.transport.move("a2")
        network.down = False
        for _ in range(20):
            a.poll()
            time.sleep(0.02)
        serve.stop()
        self.assertTrue(a.alive)
        self.assertEqual(b.peer, "a2")
        self.assertGreaterEqual(b.stats["reconnects"], 1)


class Strangers(unittest.TestCase):
    def test_a_ping_does_not_steal_a_peer_we_asked_for(self):
        network = Network()
        a = medialink.Link(Pipe(network, "a"), ack_timeout_ms=50)
        stranger = medialink.Link(Pipe(network, "s"), "a")
        stranger.poll()  # pings a
        with self.assertRaises(medialink.PeerUnreachable):
            a.connect("absent")
        self.assertEqual(a.peer, "absent")


class FakeMic:
    def __init__(self, fmt, pcm):
        self.format = fmt
        self.pcm = pcm
        self.at = 0
        self.opened = 0

    def open(self):
        self.opened += 1

    def close(self):
        pass

    def readinto(self, buf):
        count = min(len(buf), len(self.pcm) - self.at, 640)
        buf[:count] = self.pcm[self.at:self.at + count]
        self.at += count
        return count


class FakeSpeaker:
    def __init__(self, fmt):
        self.format = fmt
        self.got = bytearray()

    def try_write(self, data):
        self.got += data
        return len(data)

    def queued_size(self):
        return 0

    def close(self):
        pass


class Format:
    def __init__(self, rate, channels):
        self.rate = rate
        self.channels = channels


class PressToTalk(unittest.TestCase):
    def run_exchange(self, codec_choice):
        fmt = Format(16000, 1)
        speech = tone(16000 // 2)  # half a second
        network, a, b = pair()
        mic = FakeMic(fmt, speech)
        speaker = FakeSpeaker(fmt)
        talker = medialink.Intercom(a, mic, FakeSpeaker(fmt), codec=codec_choice)
        listener = medialink.Intercom(b, FakeMic(fmt, b""), speaker, prebuffer=2)
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(talker.press())
        serve.stop()
        while mic.at < len(speech):
            talker.service()
            listener.service()
        b.poll()
        talker.release()
        for _ in range(5):
            listener.service()
        # After the turn, the listener pads its speaker with a tenth of a
        # second of silence.
        self.assertEqual(len(speaker.got), len(speech) + 3200)
        heard = speaker.got[:len(speech)]
        self.assertFalse(any(speaker.got[len(speech):]))
        return speech, heard, talker, listener

    def test_pcm_arrives_exactly(self):
        speech, heard, talker, listener = self.run_exchange(codec.PCM16)
        self.assertEqual(bytes(heard), speech)
        self.assertEqual(listener.stats["spurts"], 1)
        self.assertEqual(talker.stats["sent"], 26)  # 25 frames and the end mark

    def test_adpcm_arrives_whole(self):
        speech, heard, talker, listener = self.run_exchange(codec.ADPCM)
        self.assertEqual(len(heard), len(speech))


class OnePort:
    """A board's I2S port: a speaker and a microphone on it, one at a time."""

    def __init__(self):
        self.holder = None

    def take(self, who):
        if self.holder not in (None, who):
            raise OSError("I2S(0) is in use by the %s" % self.holder)
        self.holder = who

    def give(self, who):
        if self.holder == who:
            self.holder = None


class PortMic(FakeMic):
    def __init__(self, fmt, pcm, port):
        super().__init__(fmt, pcm)
        self.port = port

    def open(self):
        self.port.take("microphone")
        super().open()

    def close(self):
        self.port.give("microphone")


class PortSpeaker(FakeSpeaker):
    def __init__(self, fmt, port):
        super().__init__(fmt)
        self.port = port
        self.is_open = False

    def try_write(self, data):
        self.port.take("speaker")
        self.is_open = True
        return super().try_write(data)

    def close(self):
        self.port.give("speaker")
        self.is_open = False


class SharedPort(unittest.TestCase):
    """A board whose speaker and microphone share one I2S port."""

    def test_it_answers_after_it_has_listened(self):
        fmt = Format(16000, 1)
        speech = tone(16000 // 4)
        network, a, b = pair()
        port = OnePort()
        speaker = PortSpeaker(fmt, port)
        talker = medialink.Intercom(a, FakeMic(fmt, speech), FakeSpeaker(fmt))
        board = medialink.Intercom(b, PortMic(fmt, speech, port), speaker, prebuffer=2)
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(talker.press())
        serve.stop()
        while talker.mic.at < len(speech):
            talker.service()
            board.service()
        talker.release()
        for _ in range(5):
            board.service()
        self.assertTrue(speaker.got)
        serve = Serve(a)
        try:
            self.assertTrue(board.press())
        finally:
            serve.stop()
        self.assertEqual(port.holder, "microphone")
        self.assertEqual(b.floor, medialink.TALKING)

    def test_the_speaker_is_let_go_once_the_turn_has_played(self):
        # Some boards' Wi-Fi sends badly while their I2S runs, so a speaker
        # left open after a turn keeps the board from asking for the floor.
        fmt = Format(16000, 1)
        speech = tone(16000 // 4)
        network, a, b = pair()
        port = OnePort()
        speaker = PortSpeaker(fmt, port)
        talker = medialink.Intercom(a, FakeMic(fmt, speech), FakeSpeaker(fmt), codec=codec.PCM16)
        board = medialink.Intercom(b, PortMic(fmt, b"", port), speaker, prebuffer=2)
        serve = Serve(b)
        a.connect("b")
        self.assertTrue(talker.press())
        serve.stop()
        opened_mid_turn = False
        while talker.mic.at < len(speech):
            talker.service()
            board.service()
            opened_mid_turn = opened_mid_turn or speaker.is_open
        self.assertTrue(opened_mid_turn)
        talker.release()
        deadline = time.monotonic() + 1
        while speaker.is_open and time.monotonic() < deadline:
            board.service()
            time.sleep(0.005)
        # All of the turn, then the silence that carried its end out.
        self.assertEqual(bytes(speaker.got[:len(speech)]), speech)
        self.assertFalse(any(speaker.got[len(speech):]))
        self.assertFalse(speaker.is_open)
        self.assertIsNone(port.holder)

    def test_a_microphone_that_will_not_open_gives_the_floor_back(self):
        fmt = Format(16000, 1)
        network, a, b = pair()
        port = OnePort()
        port.take("someone else")
        board = medialink.Intercom(a, PortMic(fmt, b"", port), FakeSpeaker(fmt))
        serve = Serve(b)
        try:
            a.connect("b")
            with self.assertRaises(OSError):
                board.press()
            self.assertFalse(board.talking)
            self.assertEqual(a.floor, medialink.IDLE)
            time.sleep(0.05)
            self.assertEqual(b.floor, medialink.IDLE)
        finally:
            serve.stop()


class OverUDP(unittest.TestCase):
    def test_hello_and_a_frame_on_localhost(self):
        a = medialink.Link(UDPTransport(0))
        b = medialink.Link(UDPTransport(0))
        try:
            serve = Serve(b)
            a.connect(("127.0.0.1", b.transport.port))
            a.send_audio(b"hello")
            time.sleep(0.05)
            serve.stop()
            self.assertEqual([f.payload for f in b.frames()], [b"hello"])
            self.assertEqual(b.peer, ("127.0.0.1", a.transport.port))
        finally:
            a.close()
            b.close()

    def test_nobody_listening_fails(self):
        a = medialink.Link(UDPTransport(0), ack_timeout_ms=50)
        try:
            with self.assertRaises(medialink.PeerUnreachable):
                a.connect(("127.0.0.1", 9))
        finally:
            a.transport.close()


if __name__ == "__main__":
    unittest.main()
