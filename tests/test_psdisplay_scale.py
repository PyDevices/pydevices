# SPDX-License-Identifier: MIT
"""PSDisplay.touch_scale follows the SDL contract HostEventsDevice divides by.

A canvas the page shows smaller than its framebuffer (the pyscript-template
caps it with max-width) must map a mouse click back up to framebuffer pixels.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

_LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"


class _Rect:
    def __init__(self, width, height):
        self.width, self.height, self.left, self.top = width, height, 0, 0


class _Canvas:
    def __init__(self, width, height, css_width, css_height):
        self.width, self.height = width, height
        self._rect = _Rect(css_width, css_height)

    def getBoundingClientRect(self):
        return self._rect


class TestPSDisplayTouchScale(unittest.TestCase):
    def setUp(self):
        js = types.ModuleType("js")
        js.console = mock.Mock()
        js.document = mock.Mock()
        js.navigator = mock.Mock()
        self._mods = mock.patch.dict(sys.modules, {"js": js})
        self._mods.start()
        self._path = mock.patch.object(sys, "path", [str(_LIB)] + sys.path)
        self._path.start()
        sys.modules.pop("displaydev.psdisplay", None)
        from displaydev import psdisplay

        self.PSDisplay = psdisplay.PSDisplay

    def tearDown(self):
        sys.modules.pop("displaydev.psdisplay", None)
        self._path.stop()
        self._mods.stop()

    def _display(self, canvas):
        display = object.__new__(self.PSDisplay)
        display._canvas = canvas
        return display

    def test_downscaled_canvas_divides_up_to_framebuffer(self):
        # 720 framebuffer pixels shown in 320 CSS pixels.
        display = self._display(_Canvas(720, 480, 320, 213.33))
        self.assertAlmostEqual(display.touch_scale, 320 / 720, places=3)
        # HostEventsDevice: framebuffer x = css x // touch_scale.
        self.assertEqual(int(160 // display.touch_scale), 360)

    def test_one_to_one_and_unlaid_out(self):
        self.assertEqual(self._display(_Canvas(480, 320, 480, 320)).touch_scale, 1.0)
        self.assertEqual(self._display(_Canvas(480, 320, 0, 0)).touch_scale, 1.0)

    def test_assignment_does_not_pin_the_scale(self):
        display = self._display(_Canvas(720, 480, 360, 240))
        display.touch_scale = 1.0
        self.assertAlmostEqual(display.touch_scale, 0.5)


if __name__ == "__main__":
    unittest.main()
