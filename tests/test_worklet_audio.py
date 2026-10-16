# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``audiodev.worklet_audio`` against a fake MessagePort and fake JS types."""

import asyncio
import struct
import unittest
from array import array
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401

from audiodev import AudioFormat, PCMOutput, worklet_audio

BLOCK = worklet_audio.BLOCK_FRAMES


class FakeBuffer:
    def __init__(self, data):
        self.data = bytes(data)
        self.byteLength = len(self.data)


class FakeUint8Array:
    def __init__(self, data):
        self.buffer = FakeBuffer(data)
        self.byteOffset = 0
        self.byteLength = len(self.buffer.data)


class FakeInt16Array:
    @classmethod
    def new(cls, buffer, offset, length):
        obj = cls()
        obj.buffer = buffer
        obj.samples = list(array("h", buffer.data[offset : offset + 2 * length]))
        return obj


class FakeObject:
    @staticmethod
    def new():
        return SimpleNamespace()


class FakeArray(list):
    @classmethod
    def new(cls):
        return cls()

    def push(self, item):
        self.append(item)


class FakePort:
    def __init__(self):
        self.onmessage = None
        self.posted = []

    def postMessage(self, message, transfer):
        self.posted.append((message, transfer))

    def send(self, **data):
        self.onmessage(SimpleNamespace(data=data))

    def ask(self, need, asked=0):
        self.send(need=need, asked=asked)
        message, transfer = self.posted[-1]
        self._check(message, transfer)
        return message.pcm.samples, message.asked

    def _check(self, message, transfer):
        # The reply's own buffer is the one transferred, so nothing is copied.
        assert list(transfer) == [message.pcm.buffer], transfer


def _pcm(values):
    return struct.pack(f"<{len(values)}h", *values)


class WorkletTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(
            worklet_audio,
            to_js=FakeUint8Array,
            Int16Array=FakeInt16Array,
            Object=FakeObject,
            Array=FakeArray,
            create_proxy=None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.port = FakePort()


class TestPullMode(WorkletTestCase):
    def test_listens_on_the_port(self):
        out = worklet_audio.WorkletOutput(self.port)
        self.assertIsNotNone(self.port.onmessage)
        out.close()
        self.assertIsNone(self.port.onmessage)

    def test_silence_without_a_source(self):
        worklet_audio.WorkletOutput(self.port)
        samples, asked = self.port.ask(2, asked=512)
        self.assertEqual([0] * (2 * BLOCK), samples)
        self.assertEqual(512, asked)

    def test_source_called_once_per_request_with_block_count(self):
        out = worklet_audio.WorkletOutput(self.port, channels=1)
        calls = []

        def render(blocks):
            calls.append(blocks)
            return _pcm([n % 1000 for n in range(blocks * BLOCK)])

        out.source = render
        samples, asked = self.port.ask(3, asked=7)
        self.assertEqual([3], calls)
        self.assertEqual([n % 1000 for n in range(3 * BLOCK)], samples)
        self.assertEqual(7, asked)
        self.assertEqual(1, len(self.port.posted))
        self.assertEqual(3 * BLOCK, out.frames)
        self.assertEqual(7, out.asked)
        self.assertEqual(0, out.starved)

    def test_stereo_stays_interleaved(self):
        out = worklet_audio.WorkletOutput(self.port, channels=2)
        frames = [(n, -n - 1) for n in range(BLOCK)]
        out.source = lambda blocks: _pcm([s for frame in frames for s in frame])
        samples, _ = self.port.ask(1)
        self.assertEqual(2 * BLOCK, len(samples))
        self.assertEqual(list(range(BLOCK)), samples[0::2])
        self.assertEqual([-n - 1 for n in range(BLOCK)], samples[1::2])

    def test_typed_memoryview_source(self):
        out = worklet_audio.WorkletOutput(self.port)
        out.source = lambda blocks: memoryview(array("h", range(blocks * BLOCK)))
        samples, _ = self.port.ask(1)
        self.assertEqual(list(range(BLOCK)), samples)

    def test_short_source_padded_and_counted(self):
        out = worklet_audio.WorkletOutput(self.port)
        out.source = lambda blocks: _pcm([5] * 10)
        samples, _ = self.port.ask(1)
        self.assertEqual([5] * 10 + [0] * (BLOCK - 10), samples)
        self.assertEqual(1, out.starved)

    def test_long_source_truncated(self):
        out = worklet_audio.WorkletOutput(self.port)
        out.source = lambda blocks: _pcm([1] * (BLOCK + 50))
        samples, _ = self.port.ask(1)
        self.assertEqual([1] * BLOCK, samples)

    def test_failing_source_still_replies(self):
        out = worklet_audio.WorkletOutput(self.port)

        def broken(blocks):
            raise RuntimeError("engine fault")

        out.source = broken
        with self.assertRaises(RuntimeError):
            self.port.send(need=1, asked=3)
        message, _ = self.port.posted[-1]
        self.assertEqual([0] * BLOCK, message.pcm.samples)
        self.assertEqual(3, message.asked)

    def test_offset_and_underruns(self):
        out = worklet_audio.WorkletOutput(self.port)
        self.assertIsNone(out.offset)
        self.port.send(offset=1234)
        self.assertEqual(1234, out.offset)
        self.port.send(offset=1500)
        self.assertEqual(1500, out.offset)
        self.port.send(underrun=2)
        self.port.send(underrun=1)
        self.assertEqual(3, out.underruns)
        self.assertEqual([], self.port.posted)

    def test_handle_without_listening(self):
        out = worklet_audio.WorkletOutput(self.port, listen=False)
        self.assertIsNone(self.port.onmessage)
        self.assertFalse(out.handle({"other": 1}))
        self.assertTrue(out.handle({"offset": 9}))
        self.assertEqual(9, out.offset)

    def test_rejects_three_channels(self):
        with self.assertRaises(ValueError):
            worklet_audio.WorkletOutput(self.port, channels=3)


class TestPCMOut(WorkletTestCase):
    def make(self, channels=1, **kwargs):
        return worklet_audio.pcm_out(AudioFormat(48000, channels, 16), port=self.port, **kwargs)

    def test_is_a_pcm_output(self):
        pcm = self.make()
        self.assertIsInstance(pcm, PCMOutput)
        self.assertEqual(AudioFormat(48000, 1, 16), worklet_audio.pcm_out(port=FakePort()).format)

    def test_format_checks(self):
        with self.assertRaises(ValueError):
            worklet_audio.pcm_out(AudioFormat(48000, 1, 8), port=self.port)
        with self.assertRaises(ValueError):
            worklet_audio.pcm_out(AudioFormat(48000, 1, 16, byteorder="big"), port=self.port)
        with self.assertRaises(ValueError):
            worklet_audio.pcm_out(AudioFormat(48000, 4, 16), port=self.port)
        with self.assertRaises(ValueError):
            self.make(latency="fast")
        with self.assertRaises(ValueError):
            self.make().write(b"\x00")  # half a frame

    def test_write_then_need_drains_in_order(self):
        pcm = self.make()
        pcm.write(_pcm(range(2 * BLOCK)))
        self.assertEqual(2 * BLOCK * 2, pcm.queued_size())
        self.assertTrue(pcm.is_active())
        first, _ = self.port.ask(1)
        second, _ = self.port.ask(1)
        self.assertEqual(list(range(BLOCK)), first)
        self.assertEqual(list(range(BLOCK, 2 * BLOCK)), second)
        self.assertEqual(0, pcm.queued_size())
        self.assertEqual(0, pcm.starved)
        self.assertEqual(2 * BLOCK, pcm.frames)

    def test_starvation_padded_with_silence(self):
        pcm = self.make()
        pcm.write(_pcm([9] * 100))
        samples, _ = self.port.ask(1)
        self.assertEqual([9] * 100 + [0] * (BLOCK - 100), samples)
        self.assertEqual(1, pcm.starved)
        samples, _ = self.port.ask(1)
        self.assertEqual([0] * BLOCK, samples)
        self.assertEqual(2, pcm.starved)

    def test_silence_before_first_write_is_not_starvation(self):
        pcm = self.make()
        samples, _ = self.port.ask(2)
        self.assertEqual([0] * (2 * BLOCK), samples)
        self.assertEqual(0, pcm.starved)

    def test_stereo_ring(self):
        pcm = self.make(channels=2)
        values = [s for n in range(BLOCK) for s in (n, -n)]
        pcm.write(_pcm(values))
        samples, _ = self.port.ask(1)
        self.assertEqual(values, samples)

    def test_volume_applies(self):
        pcm = self.make()
        pcm.set_volume(50)
        pcm.write(_pcm([1000] * BLOCK))
        samples, _ = self.port.ask(1)
        self.assertTrue(all(0 < s < 1000 for s in samples), samples[:4])

    def test_queue_depth_follows_latency(self):
        frame = 2
        self.assertEqual(48000 * frame // 2, self.make().space())
        self.assertEqual(48000 * frame // 10, self.make(latency="low").space())
        self.assertEqual(48000 * frame * 200 // 1000, self.make(queue_ms=200).space())
        # Never below eight blocks.
        self.assertEqual(8 * BLOCK * frame, self.make(queue_ms=1).space())

    def test_try_write_takes_only_what_fits(self):
        pcm = self.make(queue_ms=1)  # 8 blocks
        room = pcm.space()
        data = _pcm([3] * (room // 2 + 100))
        self.assertEqual(room, pcm.try_write(data))
        self.assertEqual(0, pcm.space())
        self.assertEqual(0, pcm.try_write(_pcm([1])))
        self.assertEqual(0, pcm.dropped)

    def test_write_when_full_drops_oldest(self):
        pcm = self.make(queue_ms=1)
        room = pcm.space() // 2
        pcm.write(_pcm([1] * room))
        pcm.write(_pcm([2] * 10))
        self.assertEqual(20, pcm.dropped)
        samples, _ = self.port.ask(8)
        self.assertEqual([1] * (room - 10) + [2] * 10, samples)

    def test_awrite_waits_for_room(self):
        pcm = self.make(queue_ms=1)
        room = pcm.space() // 2

        async def run():
            task = asyncio.ensure_future(pcm.awrite(_pcm([4] * (room + BLOCK))))
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            self.port.ask(1)
            await asyncio.wait_for(task, 1.0)

        asyncio.run(run())
        self.assertEqual(0, pcm.dropped)
        self.assertEqual(room * 2, pcm.queued_size())

    def test_adrain_returns_once_drained(self):
        pcm = self.make()
        pcm.write(_pcm([1] * BLOCK))

        async def run():
            task = asyncio.ensure_future(pcm.adrain())
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            self.port.ask(1)
            await asyncio.wait_for(task, 1.0)

        asyncio.run(run())

    def test_clear_and_close(self):
        pcm = self.make()
        pcm.write(_pcm([1] * BLOCK))
        pcm.clear()
        self.assertEqual(0, pcm.queued_size())
        pcm.write(_pcm([1] * BLOCK))
        pcm.close()
        self.assertEqual(0, pcm.queued_size())
        pcm.deinit()
        self.assertIsNone(self.port.onmessage)

    def test_offset_and_underruns_forwarded(self):
        pcm = self.make()
        self.port.send(offset=4096)
        self.port.send(underrun=1)
        self.assertEqual(4096, pcm.offset)
        self.assertEqual(1, pcm.underruns)


if __name__ == "__main__":
    unittest.main()
