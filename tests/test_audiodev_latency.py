# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""The shared latency vocabulary every audio backend and board config uses."""

from pathlib import Path
import sys
import unittest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

from audiodev import (  # noqa: E402
    LATENCIES,
    LOW_LATENCY_QUEUE_MS,
    AudioFormat,
    check_latency,
    queue_bytes,
)


class CheckLatencyTests(unittest.TestCase):
    def test_accepts_and_returns_every_documented_profile(self):
        for latency in LATENCIES:
            self.assertEqual(latency, check_latency(latency))

    def test_rejects_anything_else(self):
        # Falling back to the default would leave an app that asked for low
        # latency quietly buffered, which is the bug this guards.
        for bad in ("fast", "LOW", "", 0, True):
            with self.assertRaises(ValueError):
                check_latency(bad)


class QueueBytesTests(unittest.TestCase):
    fmt = AudioFormat(24000, 1, 16)

    def test_buffered_profiles_return_the_boards_own_value(self):
        for latency in (None, "buffered"):
            self.assertEqual(20000, queue_bytes(self.fmt, latency, default=20000))

    def test_low_profile_is_derived_from_the_format(self):
        expected = 24000 * 2 * LOW_LATENCY_QUEUE_MS // 1000
        self.assertEqual(expected, queue_bytes(self.fmt, "low", default=20000))

    def test_low_profile_scales_with_rate_and_channels(self):
        stereo = AudioFormat(48000, 2, 16)
        self.assertEqual(
            48000 * 4 * LOW_LATENCY_QUEUE_MS // 1000,
            queue_bytes(stereo, "low", default=20000),
        )

    def test_explicit_queue_ms_overrides_either_profile(self):
        self.assertEqual(4800, queue_bytes(self.fmt, None, 100, default=20000))
        self.assertEqual(9600, queue_bytes(self.fmt, "low", 200, default=20000))

    def test_minimum_floor_applies_to_computed_sizes(self):
        self.assertEqual(4096, queue_bytes(self.fmt, None, 1, default=20000, minimum=4096))

    def test_minimum_does_not_inflate_a_boards_own_value(self):
        # The default is returned untouched, floor or not: the board tuned it.
        self.assertEqual(2048, queue_bytes(self.fmt, None, default=2048, minimum=4096))

    def test_never_returns_less_than_one_frame(self):
        self.assertEqual(self.fmt.frame_size, queue_bytes(self.fmt, None, 0, default=20000))

    def test_validates_the_profile_before_computing(self):
        with self.assertRaises(ValueError):
            queue_bytes(self.fmt, "fast", default=20000)


if __name__ == "__main__":
    unittest.main()
