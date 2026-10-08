"""The CircuitPython TFT FeatherWing configs use the wings' own pins.

Adafruit's 2.4" (ILI9341) and 3.5" (HX8357D) TFT FeatherWings share one
pinout: TFT CS on D9, DC on D10, the STMPE610 touch controller's CS on D6,
and no display reset line (the panel resets with the Feather). The 2.4"
config once drove D6 as the display reset and put touch CS on D8, so
opening the display reset the touch controller and touch never answered.
These configs only import on a board, so the check reads their source.
"""

import ast
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parent.parent
_WINGS = (
    "board_configs/cp/busdisplay/spi/pitft_ili9341_featherwing/board_config.py",
    "board_configs/cp/busdisplay/spi/pitft_hx8357_featherwing/board_config.py",
)


def _pin(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "board":
        return node.attr
    return None


def _calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                yield node


class FeatherWingPins(unittest.TestCase):
    def check(self, rel):
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        (bus,) = list(_calls(tree, "FourWire"))
        kw = {k.arg: k.value for k in bus.keywords}
        self.assertEqual(_pin(kw.get("chip_select")), "D9", "TFT CS")
        self.assertEqual(_pin(kw.get("command")), "D10", "TFT DC")
        self.assertNotIn("reset", kw, "the wing has no display reset line")
        (touch,) = list(_calls(tree, "Adafruit_STMPE610_SPI"))
        self.assertEqual(_pin(touch.args[1]), "D6", "touch CS")

    def test_24_inch_wing(self):
        self.check(_WINGS[0])

    def test_35_inch_wing(self):
        self.check(_WINGS[1])


if __name__ == "__main__":
    unittest.main()
