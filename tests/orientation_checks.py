# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""orientation's checks, runnable on MicroPython and CPython.

    python tests/orientation_checks.py ../lib        # from tests/
    micropython tests/orientation_checks.py ../lib

test_orientation.py runs them both ways.
"""

import sys

if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])

from orientation import Orientation, sector  # noqa: E402

# Readings in g as a QMA6100P at +-2 g gives them, held still with a little
# noise, in the board's frame: Y up when the screen shows unrotated.
UPRIGHT = (0.02, 0.99, 0.05)  # sector 0
RIGHT_SIDE_DOWN = (-1.01, 0.03, -0.04)  # sector 90
UPSIDE_DOWN = (-0.03, -1.0, 0.08)  # sector 180
LEFT_SIDE_DOWN = (0.98, -0.06, 0.1)  # sector 270
FLAT_FACE_UP = (0.05, 0.1, 1.02)
FLAT_FACE_DOWN = (-0.04, 0.02, -0.99)
TILTED_30 = (0.0, 0.86, 0.5)  # 30 degrees back from upright: still upright
TILTED_70 = (0.0, 0.34, 0.94)  # nearly flat: ignored
NEAR_45 = (-0.69, 0.72, 0.0)  # 43.8 degrees: still sector 0
PAST_45 = (-0.72, 0.69, 0.0)  # 46.2 degrees: sector 90


def check_sectors():
    assert sector(*UPRIGHT) == 0
    assert sector(*RIGHT_SIDE_DOWN) == 90
    assert sector(*UPSIDE_DOWN) == 180
    assert sector(*LEFT_SIDE_DOWN) == 270
    assert sector(*FLAT_FACE_UP) is None
    assert sector(*FLAT_FACE_DOWN) is None
    assert sector(*TILTED_30) == 0
    assert sector(*TILTED_70) is None
    assert sector(*NEAR_45) == 0
    assert sector(*PAST_45) == 90
    assert sector(0, 0, 0) is None
    # Units don't matter: raw counts give the same sector.
    assert sector(-4100, 120, -160) == 90


def check_two_readings_to_turn():
    turn = Orientation()
    assert turn.rotation == 0
    assert turn.update(*RIGHT_SIDE_DOWN) is None
    assert turn.rotation == 0
    assert turn.update(*RIGHT_SIDE_DOWN) == 90
    assert turn.rotation == 90
    # Staying put reports nothing new.
    assert turn.update(*RIGHT_SIDE_DOWN) is None
    assert turn.rotation == 90


def check_a_knock_does_not_turn():
    turn = Orientation(rotation=0)
    for reading in (UPRIGHT, LEFT_SIDE_DOWN, UPRIGHT, LEFT_SIDE_DOWN, UPRIGHT):
        assert turn.update(*reading) is None
    assert turn.rotation == 0


def check_flat_resets_the_count():
    turn = Orientation()
    assert turn.update(*UPSIDE_DOWN) is None
    assert turn.update(*FLAT_FACE_UP) is None
    assert turn.update(*UPSIDE_DOWN) is None
    assert turn.rotation == 0
    assert turn.update(*UPSIDE_DOWN) == 180
    # Lying it down keeps the last rotation.
    for _ in range(4):
        assert turn.update(*FLAT_FACE_DOWN) is None
    assert turn.rotation == 180


def check_all_four_and_back():
    turn = Orientation()
    seen = []
    for reading in (RIGHT_SIDE_DOWN, UPSIDE_DOWN, LEFT_SIDE_DOWN, UPRIGHT):
        for _ in range(3):
            r = turn.update(*reading)
            if r is not None:
                seen.append(r)
    assert seen == [90, 180, 270, 0], seen


def check_offset_and_stable():
    turn = Orientation(offset=180, stable=3)
    assert turn.update(*UPRIGHT) is None
    assert turn.update(*UPRIGHT) is None
    assert turn.update(*UPRIGHT) == 180
    # 270 + 90 wraps to 0.
    turn = Orientation(offset=90, rotation=180)
    assert turn.update(*LEFT_SIDE_DOWN) is None
    assert turn.update(*LEFT_SIDE_DOWN) == 0


CHECKS = (
    check_sectors,
    check_two_readings_to_turn,
    check_a_knock_does_not_turn,
    check_flat_resets_the_count,
    check_all_four_and_back,
    check_offset_and_stable,
)


def test_all():
    for check in CHECKS:
        check()


if __name__ == "__main__":
    test_all()
    print("orientation: %d checks passed" % len(CHECKS))
