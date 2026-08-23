import ast
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: F401


class FakeBridge(types.ModuleType):
    def __init__(self):
        super().__init__("_wasm_bridge")
        self.events = []
        self.registered = None
        self.timer_fired = []
        self.timers = {}
        self.output_enabled = True
        self.input_enabled = True
        self.audio_writes = []
        self.input_bytes = b""

    def register_framebuffer(self, buffer, width, height, canvas):
        self.registered = (buffer, width, height, canvas)
        return True

    def unregister_framebuffer(self):
        self.registered = None

    def poll_event(self, *_contract):
        return json.dumps(self.events.pop(0)) if self.events else None

    def poll_events(self, *_contract):
        queued = [json.dumps(event) for event in self.events]
        self.events.clear()
        return (queued or None, len(queued))

    def clear_events(self):
        self.events.clear()

    def timer_start(self, timer_id, delay, periodic, callback=None):
        self.timers[timer_id] = (delay, periodic, callback)

    def timer_cancel(self, timer_id):
        self.timers.pop(timer_id, None)

    def timer_poll(self):
        return self.timer_fired.pop(0) if self.timer_fired else None

    def sleep_ms(self, _ms):
        return None

    def audio_state(self, input):
        return self.input_enabled if input else self.output_enabled

    def audio_write(self, data, *format_args):
        data = bytes(data)
        self.audio_writes.append((data, format_args))
        return len(data)

    def audio_readinto(self, target, *_format_args):
        count = min(len(target), len(self.input_bytes))
        target[:count] = self.input_bytes[:count]
        self.input_bytes = self.input_bytes[count:]
        return count

    def audio_clear(self, input):
        if input:
            self.input_bytes = b""
        else:
            self.audio_writes.clear()

    def audio_queued_size(self, input):
        if input:
            return len(self.input_bytes)
        return sum(len(item[0]) for item in self.audio_writes)


class WasmBackendTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()
        self.modules_patch = mock.patch.dict(sys.modules, {"_wasm_bridge": self.bridge})
        self.modules_patch.start()
        for name in ("displaydev.wasmdisplay", "audiodev.wasm_audio", "multimer.wasm"):
            sys.modules.pop(name, None)

    def tearDown(self):
        self.modules_patch.stop()

    def test_display_owns_and_registers_rgb565_buffer(self):
        from displaydev.wasmdisplay import WasmDisplay

        display = WasmDisplay(4, 3, "canvas", quiet=True)
        self.assertEqual(len(display.framebuffers()[0]), 24)
        self.assertEqual(self.bridge.registered[1:], (4, 3, "canvas"))
        display.fill_rect(0, 0, 4, 3, 0xF800)
        self.assertEqual(bytes(self.bridge.registered[0]), b"\x00\xf8" * 12)
        display.show()
        display.deinit()
        self.assertIsNone(self.bridge.registered)

    def test_input_maps_pointer_touch_wheel_keyboard_and_gamepad(self):
        import events
        import keys
        from displaydev.wasmdisplay import WasmDevices

        self.bridge.events.extend(
            [
                {
                    "type": "pointerdown",
                    "x": 2,
                    "y": 3,
                    "button": 0,
                    "pointerId": 7,
                    "pointerType": "touch",
                },
                {
                    "type": "pointermove",
                    "x": 5,
                    "y": 8,
                    "movementX": 3,
                    "movementY": 5,
                    "buttons": 1,
                    "pointerId": 0,
                    "pointerType": "mouse",
                },
                {"type": "wheel", "deltaX": 2, "deltaY": -4},
                {
                    "type": "keydown",
                    "key": "BrowserBack",
                    "code": "BrowserBack",
                    "location": 0,
                },
                {
                    "type": "gamepad",
                    "index": 0,
                    "axes": [0.5],
                    "buttons": [{"pressed": True}],
                },
            ]
        )
        output = WasmDevices().read()
        self.assertEqual(
            [item.type for item in output],
            [
                events.FINGERDOWN,
                events.MOUSEBUTTONDOWN,
                events.MOUSEMOTION,
                events.MOUSEWHEEL,
                events.KEYDOWN,
                events.JOYAXISMOTION,
                events.JOYBUTTONDOWN,
            ],
        )
        self.assertEqual(output[4].key, keys.K_AC_BACK)

    def test_audio_forwards_all_formats_and_channels(self):
        from audiodev import AudioFormat
        from audiodev.wasm_audio import WasmPCMInput, WasmPCMOutput

        formats = (
            (8, False, "little"),
            (8, True, "big"),
            (16, False, "big"),
            (16, True, "little"),
            (32, False, "little"),
            (32, True, "big"),
        )
        for bits, signed, byteorder in formats:
            for channels in (1, 2):
                with self.subTest(
                    bits=bits, signed=signed, byteorder=byteorder, channels=channels
                ):
                    fmt = AudioFormat(
                        22050, channels, bits, signed=signed, byteorder=byteorder
                    )
                    payload = bytes(fmt.frame_size * 2)
                    self.assertEqual(WasmPCMOutput(fmt).write(payload), len(payload))
                    self.assertEqual(
                        self.bridge.audio_writes[-1][1],
                        (22050, channels, bits, signed, byteorder == "big"),
                    )
                    self.bridge.input_bytes = payload
                    target = bytearray(len(payload))
                    self.assertEqual(WasmPCMInput(fmt).readinto(target), len(payload))

    def test_audio_permissions_fail_clearly(self):
        from audiodev.wasm_audio import WasmPCMInput, WasmPCMOutput

        self.bridge.output_enabled = False
        with self.assertRaisesRegex(RuntimeError, "Enable Audio"):
            WasmPCMOutput().open()
        self.bridge.input_enabled = False
        with self.assertRaisesRegex(RuntimeError, "Enable Microphone"):
            WasmPCMInput().open()

    def test_timer_one_shot_rearm_and_self_deinit(self):
        from multimer.wasm import Timer, pump

        fired = []
        one = Timer(
            -1,
            period=10,
            mode=Timer.ONE_SHOT,
            callback=lambda timer: fired.append(timer.id),
        )
        self.bridge.timer_fired.append(one.id)
        pump()
        self.assertEqual(fired, [one.id])
        self.assertNotIn(one.id, self.bridge.timers)

        periodic = Timer(-1)
        periodic.init(
            period=20, mode=Timer.PERIODIC, callback=lambda timer: timer.deinit()
        )
        self.bridge.timer_fired.append(periodic.id)
        pump()
        self.assertNotIn(periodic.id, self.bridge.timers)
        periodic.init(period=30, callback=lambda _timer: None, hard=False)
        self.assertEqual(self.bridge.timers[periodic.id][:2], (30, True))
        self.assertTrue(callable(self.bridge.timers[periodic.id][2]))
        periodic.deinit()

    def test_automatic_selectors_prefer_builtin_bridge(self):
        import audiodev.auto
        import displaydev.auto
        import multimer.auto

        self.assertEqual(importlib.reload(displaydev.auto).host_kind(), "wasm")
        self.assertEqual(importlib.reload(audiodev.auto).select_backend(), "wasm_audio")
        self.assertEqual(importlib.reload(multimer.auto).name, "wasm")

    def test_python_backends_do_not_import_browser_proxies(self):
        root = Path(__file__).parents[1] / "lib"
        for relative in (
            "displaydev/wasmdisplay.py",
            "audiodev/wasm_audio.py",
            "multimer/wasm.py",
        ):
            tree = ast.parse((root / relative).read_text("utf-8"))
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
            self.assertNotIn("js", names)
            self.assertNotIn("pyscript", names)
            self.assertNotIn("pyodide", names)


if __name__ == "__main__":
    unittest.main()
