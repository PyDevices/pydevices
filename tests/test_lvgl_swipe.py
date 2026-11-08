# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""display_driver's pointer indev: a slow one-finger swipe makes LVGL's
GESTURE, and two fingers still make only a two-finger swipe.

Runs ``import display_driver`` against real LVGL and SDL's dummy video in a
child process (the import builds the program's one display and App), then
feeds the pointer the way a touch panel does: a finger moving a few pixels
per read, each position read twice, as touch chips repeat it.
"""

import os
import subprocess
import sys
import unittest

import _env

try:
    import lvgl  # noqa: F401

    HAVE_LVGL = True
except ImportError:
    HAVE_LVGL = False

CHILD = r'''
import os, sys
import lvgl as lv
import events
import display_driver

vd = display_driver._drivers[0].virtual_devices[0]
ptr = vd._vd_pointer
scr = lv.screen_active()
scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
got = []
scr.add_event_cb(lambda e: got.append(int(e.get_gesture_type())), lv.EVENT.GESTURE, None)

def pump(n=1):
    for _ in range(n):
        lv.tick_inc(10)
        lv.timer_handler()

# One finger, 120 px down at 6 px a read, each position read twice.
x, y = 160, 40
ptr.add_event(events.Button(events.MOUSEBUTTONDOWN, (x, y), 1, True, None))
pump(2)
for _ in range(20):
    y += 6
    for _ in range(2):
        ptr.add_event(events.Motion(events.MOUSEMOTION, (x, y), (0, 6), (1, 0, 0), True, None))
        pump()
ptr.add_event(events.Button(events.MOUSEBUTTONUP, (x, y), 1, True, None))
pump(3)
print("SWIPE", [g for g in got if g == lv.INDEV_GESTURE.NONE])

# Two fingers 80 px apart, sliding down 120 px together: a two-finger
# swipe, and nothing else (no one-finger GESTURE from the first finger).
del got[:]
a, b = [120, 100], [200, 100]
for fid, p in ((0, a), (1, b)):
    vd._route(events.Finger(events.FINGERDOWN, tuple(p), fid, None))
    pump()
for _ in range(30):
    a[1] += 4
    b[1] += 4
    for fid, p in ((0, a), (1, b)):
        vd._route(events.Finger(events.FINGERMOTION, tuple(p), fid, None))
    pump(2)
for fid, p in ((1, b), (0, a)):
    vd._route(events.Finger(events.FINGERUP, tuple(p), fid, None))
    pump()
pump(3)
print("TWO", got == [int(lv.INDEV_GESTURE.TWO_FINGERS_SWIPE)], got)
sys.stdout.flush()
os._exit(0)  # the App's window and timers would keep the process up
'''


@unittest.skipUnless(HAVE_LVGL, "needs the lvgl module")
class SlowSwipe(unittest.TestCase):
    def test_slow_swipe_and_pinch(self):
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        env["PYTHONPATH"] = os.pathsep.join([str(_env.ROOT / "lib"), env.get("PYTHONPATH", "")])
        out = subprocess.run(
            [sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=120
        )
        lines = {line.split()[0]: line for line in out.stdout.splitlines() if line.split()}
        self.assertIn("SWIPE", lines, out.stdout + out.stderr)
        self.assertEqual("SWIPE [0]", lines["SWIPE"])
        self.assertTrue(lines["TWO"].startswith("TWO True"), lines["TWO"])

if __name__ == "__main__":
    unittest.main()
