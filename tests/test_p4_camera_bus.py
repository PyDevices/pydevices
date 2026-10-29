"""An ESP32-P4 board's camera() opens the board's I2C bus before the camera.

The camera's control bus (SCCB) is the board I2C. When ``camera()`` ran
before anything else had opened that bus, cameraif opened the port itself,
and the next ``machine.I2C`` on it (the microphone's ES7210, the speaker's
ES8311, touch) found no device; the bus stayed dead until a hard reset. A
camera-only program such as the medialink surveillance camera hit it on the
first press. These load each P4 board's board_peripherals.py with stand-in
``machine`` and ``cameraif`` modules and check what is open when the camera
starts.
"""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402

_BOARDS = {
    "panel": "board_configs/fbdisplay/esp32-p4-wifi6-touch-lcd-4b/board_peripherals.py",
    "dev-kit": "board_configs/nodisplay/esp32-p4-wifi6-dev-kit/board_peripherals.py",
}


def _fakes(events):
    """Stand-in machine and cameraif modules that log what is opened, in order."""
    machine = types.ModuleType("machine")

    class I2C:
        def __init__(self, port, **kwargs):
            self.port = port
            events.append(("I2C", port))

    class Pin:
        IN = OUT = 0

        def __init__(self, *args, **kwargs):
            pass

    machine.I2C = I2C
    machine.Pin = Pin

    cameraif = types.ModuleType("cameraif")
    cameraif.available = lambda: True

    class Camera:
        def __init__(self, **kwargs):
            events.append(("Camera", kwargs.get("i2c")))

    cameraif.Camera = Camera
    # Without camera_sensors, camera() calls cameraif.Camera directly.
    return {"machine": machine, "cameraif": cameraif, "camera_sensors": None, "board_config": None}


def _load(path, modules):
    spec = importlib.util.spec_from_file_location("p4_board_peripherals_under_test", _env.ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class P4CameraOpensBusFirstTests(unittest.TestCase):
    def test_camera_starts_on_an_open_bus(self):
        for board, path in _BOARDS.items():
            with self.subTest(board=board):
                events = []
                modules = _fakes(events)
                bp = _load(path, modules)
                with mock.patch.dict(sys.modules, modules):
                    bp.camera()
                self.assertEqual(events, [("I2C", 1), ("Camera", 1)])

    def test_camera_reuses_a_bus_already_open(self):
        for board, path in _BOARDS.items():
            with self.subTest(board=board):
                events = []
                modules = _fakes(events)
                bp = _load(path, modules)
                with mock.patch.dict(sys.modules, modules):
                    bp.camera()
                    bp.camera()
                self.assertEqual(events, [("I2C", 1), ("Camera", 1), ("Camera", 1)])

    def test_a_caller_naming_its_own_bus_is_left_alone(self):
        for board, path in _BOARDS.items():
            with self.subTest(board=board):
                events = []
                modules = _fakes(events)
                bp = _load(path, modules)
                with mock.patch.dict(sys.modules, modules):
                    bp.camera(i2c=0)
                self.assertEqual(events, [("Camera", 0)])


if __name__ == "__main__":
    unittest.main()
