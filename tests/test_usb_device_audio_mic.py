# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""usb.device.audio's microphone and headset: the descriptors the computer
reads, the streams started when it records, and its volume and mute.

The module's own file runs against the fake controller of
test_usb_device_audio_speed, so these check the bytes on the wire and the
calls to machine.USBDevice, never a real link.
"""

import struct
import sys
import time
import unittest

from test_usb_device_audio_speed import (
    FULL,
    HIGH,
    Descriptor,
    FakeDevice,
    FakeUSBDevice,
    _endpoints,
    _load,
)

_SETUP, _ACK = 1, 3


def _walk(blob):
    """(length, type, subtype or None, bytes) for each descriptor."""
    i = 0
    while i < len(blob) and blob[i]:
        yield blob[i], blob[i + 1], (blob[i + 2] if blob[i + 1] in (0x24, 0x25) else None), blob[i : i + blob[i]]
        i += blob[i]


class MicrophoneTests(unittest.TestCase):
    def setUp(self):
        self.audio, self.mp, self.usbdev, self._saved = _load()
        FakeUSBDevice.fastest, FakeUSBDevice.link, FakeUSBDevice.mounted = FULL, FULL, False
        FakeUSBDevice.streams = []
        self.usbdev.dev = FakeDevice()
        self.sleeps = []
        self._sleep = getattr(time, "sleep_ms", None)
        time.sleep_ms = self.sleeps.append

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
        if self._sleep is None:
            del time.sleep_ms
        else:
            time.sleep_ms = self._sleep

    def build(self, itf, itf_num=0, ep_num=3):
        dummy = Descriptor(None)
        itf.desc_cfg(dummy, itf_num, ep_num, [])
        desc = Descriptor(bytearray(dummy.o))
        itf.desc_cfg(desc, itf_num, ep_num, [])
        return desc.b

    def request(self, itf, kind, bRequest, wValue, wIndex, data=b"", to_host=True, stage=_SETUP):
        bm = (0x80 if to_host else 0) | (kind << 5) | 1
        return itf.on_interface_control_xfer(stage, struct.pack("BBHHH", bm, bRequest, wValue, wIndex, len(data)))

    # -- the three shapes

    def test_a_microphone_is_one_iso_in_endpoint_and_two_interfaces(self):
        mic = self.audio.MicrophoneInterface()
        blob = self.build(mic, ep_num=3)
        self.assertEqual((mic.num_itfs(), mic.num_eps()), (2, 1))
        self.assertEqual(_endpoints(blob), [(0x83, 0x05, 196, 1)])
        iad = next(d for d in _walk(blob) if d[1] == 0x0B)[3]
        self.assertEqual(iad[3], 2, "the association covers both interfaces")
        out_terminals = [d for d in _walk(blob) if d[1] == 0x24 and d[2] == 0x03]
        self.assertEqual([struct.unpack("<H", d[3][4:6])[0] for d in out_terminals], [0x0101])
        in_terminals = [d for d in _walk(blob) if d[1] == 0x24 and d[2] == 0x02 and d[0] == 17]
        self.assertEqual([struct.unpack("<H", d[3][4:6])[0] for d in in_terminals], [0x0201], "a microphone terminal")

    def test_a_headset_adds_the_speakers_pair_and_takes_two_in_endpoints(self):
        hs = self.audio.HeadsetInterface()
        blob = self.build(hs, ep_num=3)
        self.assertEqual((hs.num_itfs(), hs.num_eps()), (3, 2))
        self.assertEqual(_endpoints(blob), [(0x03, 0x05, 196, 1), (0x83, 0x11, 3, 1), (0x84, 0x05, 196, 1)])
        in_endpoints = [e[0] for e in _endpoints(blob) if e[0] & 0x80]
        self.assertEqual(len(set(in_endpoints)), 2)
        interfaces = [(d[3][2], d[3][3]) for d in _walk(blob) if d[1] == 0x04]
        self.assertEqual(interfaces, [(0, 0), (1, 0), (1, 1), (2, 0), (2, 1)])

    def test_the_configuration_total_length_matches_the_audio_control_header(self):
        for cls in (self.audio.MicrophoneInterface, self.audio.HeadsetInterface):
            blob = self.build(cls())
            header = next(d for d in _walk(blob) if d[1] == 0x24 and d[2] == 0x01 and d[0] == 9)[3]
            declared = struct.unpack("<H", header[6:8])[0]
            start = blob.index(header)
            end = start
            for length, kind, subtype, raw in _walk(blob[start:]):
                if kind == 0x04 and raw[5] == 0x01 and raw[6] == 0x02:
                    break
                end += length
            self.assertEqual(declared, end - start, cls.__name__)

    def test_the_speaker_alone_is_what_it_was(self):
        spk = self.audio.SpeakerInterface()
        blob = self.build(spk)
        self.assertEqual((spk.num_itfs(), spk.num_eps()), (2, 1))
        self.assertEqual(_endpoints(blob), [(0x03, 0x05, 196, 1), (0x83, 0x11, 3, 1)])

    # -- recording

    def test_selecting_the_alternate_starts_the_stream_and_deselecting_stops_it(self):
        mic = self.audio.MicrophoneInterface()
        self.build(mic, ep_num=3)
        FakeUSBDevice.link, FakeUSBDevice.mounted = FULL, True
        mic.on_open()
        self.assertTrue(self.request(mic, 0, 0x0B, 1, 1, to_host=False))
        self.assertTrue(mic.recording)
        self.assertEqual(FakeUSBDevice.streams, [(0x83, 192)], "one frame's worth, the endpoint's slack unused")
        self.request(mic, 0, 0x0B, 0, 1, to_host=False)
        self.assertFalse(mic.recording)

    def test_a_headset_streams_each_direction_from_its_own_interface(self):
        hs = self.audio.HeadsetInterface()
        self.build(hs, ep_num=3)
        FakeUSBDevice.link, FakeUSBDevice.mounted = FULL, True
        hs.on_open()
        self.request(hs, 0, 0x0B, 1, 2, to_host=False)  # the microphone's interface
        self.assertEqual((hs.alt, hs.mic_alt), (0, 1))
        self.request(hs, 0, 0x0B, 1, 1, to_host=False)  # the speaker's
        self.assertEqual((hs.alt, hs.mic_alt), (1, 1))
        self.assertEqual(sorted(s[0] for s in FakeUSBDevice.streams), [0x03, 0x84])
        self.assertEqual(self.request(hs, 0, 0x0A, 0, 2), bytes((1,)))

    def test_the_microphone_packet_follows_the_link(self):
        FakeUSBDevice.fastest = HIGH
        mic = self.audio.MicrophoneInterface()
        blob = self.build(mic)
        self.assertEqual(_endpoints(blob)[0][2], 28)
        FakeUSBDevice.link, FakeUSBDevice.mounted = FULL, True
        mic.on_open()
        self.request(mic, 0, 0x0B, 1, 1, to_host=False)  # the computer is full speed
        self.assertEqual(_endpoints(blob)[0][2], 196, "the endpoint the computer re-reads")
        self.assertEqual(len(self.mp.scheduled), 1)
        self.assertEqual(FakeUSBDevice.streams, [], "it streams after the re-enumeration")
        self.mp.scheduled[0][0](None)
        self.request(mic, 0, 0x0B, 1, 1, to_host=False)
        self.assertEqual(FakeUSBDevice.streams, [(0x83, 192)])

    def test_a_headset_rewrites_both_directions_for_a_full_speed_link(self):
        FakeUSBDevice.fastest = HIGH
        hs = self.audio.HeadsetInterface()
        blob = self.build(hs)
        self.assertEqual([e[2] for e in _endpoints(blob)], [28, 4, 28])
        FakeUSBDevice.link, FakeUSBDevice.mounted = FULL, True
        hs.on_open()
        hs.service()
        self.assertEqual([e[2] for e in _endpoints(blob)], [196, 3, 196])

    # -- volume and mute

    def test_the_computers_input_level_lands_in_mic_volume_and_mic_mute(self):
        mic = self.audio.MicrophoneInterface()
        self.build(mic)
        feature = (6 << 8) | 0
        reply = self.request(mic, 1, 0x01, 0x0200, feature, to_host=False)  # SET_CUR volume
        reply[:] = struct.pack("<h", -1280)
        self.request(mic, 1, 0x01, 0x0200, feature, to_host=False, stage=_ACK)
        self.assertEqual(mic.mic_volume, -1280)
        reply = self.request(mic, 1, 0x01, 0x0100, feature, to_host=False)  # SET_CUR mute
        reply[:] = b"\x01"
        self.request(mic, 1, 0x01, 0x0100, feature, to_host=False, stage=_ACK)
        self.assertTrue(mic.mic_mute)
        self.assertEqual(struct.unpack("<h", self.request(mic, 1, 0x01, 0x0200, feature))[0], -1280)
        self.assertEqual(mic.volume, 0, "the speaker's level is a different control")

    def test_the_clock_answers_for_a_microphone_alone(self):
        mic = self.audio.MicrophoneInterface()
        self.build(mic)
        clock = (4 << 8) | 0
        self.assertEqual(struct.unpack("<I", self.request(mic, 1, 0x01, 0x0100, clock))[0], 48000)

    def test_the_speaker_controls_are_not_there_without_a_speaker(self):
        mic = self.audio.MicrophoneInterface()
        self.build(mic)
        self.assertNotIn((2 << 8) | 0, self.usbdev.dev._itfs)
        self.assertIn((6 << 8) | 0, self.usbdev.dev._itfs)


if __name__ == "__main__":
    unittest.main()
