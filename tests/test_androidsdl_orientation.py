"""AndroidSDLDisplay waits for the Activity to finish turning before CreateWindow.

A renderer created mid-turn can draw a frame that never reaches the screen,
so an app that draws once and waits stays black. These tests fake the
Activity (no phone needed) and check what shape its views had when
``SDLDisplay.__init__`` ran.
"""

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401

try:
    from displaydev import androidsdl
    from displaydev.sdldisplay import SDLDisplay
except Exception as exc:  # usdl2 / SDL2 missing on this host
    androidsdl = None
    _SKIP = str(exc)
else:
    _SKIP = ""

LANDSCAPE = (2176, 1008)
PORTRAIT = (1080, 2176)


class _Activity:
    """Starts landscape; turns portrait after ``polls`` shape reads."""

    def __init__(self, polls):
        self.requested = None
        self._polls = polls
        self.decor = _View(self)
        self.surface = _View(self)

    def setRequestedOrientation(self, flag):
        self.requested = flag

    def getWindow(self):
        activity = self

        class _Window:
            def getDecorView(self):
                return activity.decor

        return _Window()

    def shape(self):
        if self.requested is None or self._polls > 0:
            if self.requested is not None:
                self._polls -= 1
            return LANDSCAPE
        return PORTRAIT


class _View:
    def __init__(self, activity):
        self._activity = activity
        self._wh = None

    def getWidth(self):
        self._wh = self._activity.shape()
        return self._wh[0]

    def getHeight(self):
        return self._wh[1]


def _fake_jnius(activity):
    def autoclass(name):
        if name == "org.kivy.android.PythonActivity":
            return types.SimpleNamespace(mActivity=activity)
        if name == "org.libsdl.app.SDLActivity":
            return types.SimpleNamespace(mSurface=activity.surface)
        raise LookupError(name)

    return types.SimpleNamespace(autoclass=autoclass)


@unittest.skipIf(androidsdl is None, "displaydev.androidsdl unavailable: %s" % _SKIP)
class WaitBeforeCreateWindowTests(unittest.TestCase):
    def _construct(self, activity):
        seen = {}

        def fake_sdl_init(display, *args, **kwargs):
            seen["requested"] = activity.requested
            seen["shapes"] = (
                (activity.decor.getWidth(), activity.decor.getHeight()),
                (activity.surface.getWidth(), activity.surface.getHeight()),
            )

        with mock.patch.dict(sys.modules, {"jnius": _fake_jnius(activity)}), \
                mock.patch.object(androidsdl.sys, "platform", "android"), \
                mock.patch.object(androidsdl.time, "sleep", lambda s: None), \
                mock.patch.object(SDLDisplay, "__init__", fake_sdl_init), \
                mock.patch.object(androidsdl.AndroidSDLDisplay, "_await_drawable", lambda *a: None), \
                mock.patch.object(androidsdl.AndroidSDLDisplay, "deinit", lambda self: None):
            # Dropped inside the patches: there is no window to release.
            androidsdl.AndroidSDLDisplay(width=720, height=1280)
        return seen

    def test_portrait_app_started_landscape_waits_for_the_turn(self):
        activity = _Activity(polls=12)
        seen = self._construct(activity)
        self.assertEqual(seen["requested"], androidsdl._ORIENTATION_PORTRAIT)
        self.assertEqual(seen["shapes"], (PORTRAIT, PORTRAIT))

    def test_already_portrait_returns_quickly(self):
        activity = _Activity(polls=0)
        activity.requested = androidsdl._ORIENTATION_PORTRAIT
        with mock.patch.dict(sys.modules, {"jnius": _fake_jnius(activity)}), \
                mock.patch.object(androidsdl.sys, "platform", "android"):
            self.assertTrue(androidsdl._wait_activity_shape(False, timeout_s=1.0, poll_s=0.001))

    def test_a_turn_that_never_comes_times_out(self):
        activity = _Activity(polls=10**9)
        activity.requested = androidsdl._ORIENTATION_PORTRAIT
        with mock.patch.dict(sys.modules, {"jnius": _fake_jnius(activity)}), \
                mock.patch.object(androidsdl.sys, "platform", "android"):
            self.assertFalse(androidsdl._wait_activity_shape(False, timeout_s=0.05, poll_s=0.001))

    def test_off_android_does_not_wait(self):
        self.assertFalse(androidsdl._wait_activity_shape(False, timeout_s=5.0))


if __name__ == "__main__":
    unittest.main()
