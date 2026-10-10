"""The Seeed Round Display configs put taps where they land.

This panel's CHSC6X reads x about 1.3 times too far from the centre. The raw
readings below are the means of five taps on each of five targets, measured
on a XIAO nRF52840; through each config's ``touch_read`` it must come out near
its target. The configs only import on a board, so the hardware modules are
stubbed and the config's source is run as-is.
"""

import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MP_DRIVER = "drivers/touch/chsc6x.py"
_CP_DRIVER = "drivers/touch/circuitpython/chsc6x.py"
# (config, the CHSC6X driver it runs with)
_CONFIGS = (
    (
        "board_configs/busdisplay/spi/seeed_gc9a01_on_xiao_nrf52840/board_config.py",
        _MP_DRIVER,
    ),
    (
        "board_configs/cp/busdisplay/spi/seeed_gc9a01_on_xiao_nrf52840/board_config.py",
        _CP_DRIVER,
    ),
    (
        "board_configs/busdisplay/spi/seeed_gc9a01_on_qtpy_esp32s3/board_config.py",
        _MP_DRIVER,
    ),
    (
        "board_configs/busdisplay/spi/seeed_gc9a01_on_qtpy_rp2040/board_config.py",
        _MP_DRIVER,
    ),
    (
        "board_configs/cp/busdisplay/spi/seeed_gc9a01_on_qtpy_esp32s3/board_config.py",
        _CP_DRIVER,
    ),
    (
        "board_configs/cp/busdisplay/spi/seeed_gc9a01_on_qtpy_rp2040/board_config.py",
        _CP_DRIVER,
    ),
)
# (target x, target y), mean raw (x, y) over five taps.
_MEASURED = (
    ((120, 120), (117.8, 123.0)),
    ((120, 50), (114.2, 51.0)),
    ((190, 120), (208.0, 124.4)),
    ((120, 190), (119.4, 203.6)),
    ((50, 120), (26.2, 121.2)),
)
_TOLERANCE = 8  # px, about the spread of a fingertip's taps


class _Anything:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Anything()

    def __call__(self, *args, **kwargs):
        return _Anything()


class _Touch:
    point = None

    def __init__(self, *args, **kwargs):
        pass

    def read_points(self):
        return (_Touch.point,) if _Touch.point is not None else ()


def _helper_source(driver):
    """``round_display_points`` from a driver, without the driver's imports."""
    src = (_ROOT / driver).read_text(encoding="utf-8")
    start = src.index("def round_display_points")
    end = src.find("\ndef ", start + 1)
    return src[start:] if end < 0 else src[start:end]


def _stub_modules(driver):
    stubs = {}
    for name in ("gc9a01", "machine", "spibus", "board", "displayio", "fourwire"):
        mod = types.ModuleType(name)
        mod.__getattr__ = lambda attr: _Anything
        stubs[name] = mod
    # The real helper, with a stand-in for the controller.
    chsc6x = types.ModuleType("chsc6x")
    exec(_helper_source(driver), chsc6x.__dict__)  # noqa: S102
    chsc6x.CHSC6X = _Touch
    stubs["chsc6x"] = chsc6x
    peripherals = types.ModuleType("board_peripherals")
    peripherals.PERIPHERALS = frozenset()
    peripherals.load_peripherals = lambda ns: None
    stubs["board_peripherals"] = peripherals
    return stubs


class RoundDisplayTouch(unittest.TestCase):
    def setUp(self):
        self._saved = dict(sys.modules)

    def tearDown(self):
        sys.modules.clear()
        sys.modules.update(self._saved)
        _Touch.point = None

    def check(self, rel, driver):
        sys.modules.update(_stub_modules(driver))
        ns = {}
        exec(compile((_ROOT / rel).read_text(encoding="utf-8"), rel, "exec"), ns)  # noqa: S102
        read = ns["touch_read"]
        self.assertEqual(read(), ())
        for (tx, ty), (rx, ry) in _MEASURED:
            _Touch.point = (round(rx), round(ry))
            ((x, y),) = read()
            self.assertLessEqual(abs(x - tx), _TOLERANCE, f"x for target {(tx, ty)}")
            self.assertLessEqual(abs(y - ty), 14, f"y for target {(tx, ty)}")

    def test_micropython_config(self):
        self.check(*_CONFIGS[0])

    def test_circuitpython_config(self):
        self.check(*_CONFIGS[1])

    def test_qtpy_esp32s3_config(self):
        self.check(*_CONFIGS[2])

    def test_qtpy_rp2040_config(self):
        self.check(*_CONFIGS[3])

    def test_qtpy_esp32s3_circuitpython_config(self):
        self.check(*_CONFIGS[4])

    def test_qtpy_rp2040_circuitpython_config(self):
        self.check(*_CONFIGS[5])


if __name__ == "__main__":
    unittest.main()
