# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Comprehensive unit test suite for the appdev package."""

import sys
import unittest
import _env
import events
import keys
import appdev
from appdev import (
    App,
    Touch,
    Keypad,
    Encoder,
    Joystick,
    HostEvents,
    TouchGrid,
    JoyMap,
)


class _FakeDisplay:
    def __init__(self, width=320, height=240, rotation=0, needs_refresh=False):
        self.width = width
        self.height = height
        self.rotation = rotation
        self.needs_refresh = needs_refresh
        self.shows = 0
        self.quitted = False
        self.quit_chord = (keys.K_q, keys.KMOD_CTRL)
        self.touch_scale = 1.0

    def show(self, timer=None):
        self.shows += 1

    def quit(self):
        self.quitted = True


class _FakeJoystickDriver:
    def __init__(self):
        self.instance_id = 1
        self.axes = [0.0, 0.0]
        self.buttons = [False, False]
        self.hats = [(0, 0)]
        self.balls = [(0, 0)]

    def get_instance_id(self):
        return self.instance_id

    def get_numaxes(self):
        return len(self.axes)

    def get_axis(self, i):
        return self.axes[i]

    def get_numbuttons(self):
        return len(self.buttons)

    def get_button(self, i):
        return self.buttons[i]

    def get_numhats(self):
        return len(self.hats)

    def get_hat(self, i):
        return self.hats[i]

    def get_numballs(self):
        return len(self.balls)

    def get_ball(self, i):
        return self.balls[i]


class TestAppLifecycle(unittest.TestCase):
    def tearDown(self):
        if App.current() is not None:
            App.current()._perform_teardown()

    def test_singleton(self):
        self.assertIsNone(App.current())
        app = App()
        self.assertIs(App.current(), app)
        app._perform_teardown()
        self.assertIsNone(App.current())

    def test_board_config_auto_wiring(self):
        class BoardConfig:
            display_drv = _FakeDisplay()
            host_read = lambda: []
            touch_read = lambda: ()
            keypad_read = lambda: ()
            encoder_read = lambda: 0
            encoder_button_read = lambda: False
            joystick_driver = _FakeJoystickDriver()

        app = App(BoardConfig)
        self.assertEqual(len(app.displays), 1)
        self.assertIsNotNone(app.host_dev)
        self.assertIsNotNone(app.touch_dev)
        self.assertIsNotNone(app.keypad_dev)
        self.assertIsNotNone(app.encoder_dev)
        self.assertIsNotNone(app.joystick_dev)
        self.assertEqual(len(app.devices), 5)
        app._perform_teardown()

    def test_before_quit_and_display_quit_order(self):
        order = []
        disp = _FakeDisplay()
        app = App(displays=[disp])
        app.before_quit = lambda: order.append("before_quit")
        app.request_quit()
        self.assertTrue(app.quit_requested)
        app._perform_teardown()
        self.assertTrue(disp.quitted)
        self.assertEqual(order, ["before_quit"])


class TestEventSubscriptions(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def tearDown(self):
        self.app._perform_teardown()

    def test_on_and_off_single_event(self):
        received = []
        self.app.on(events.KEYDOWN, received.append)

        # Inject fake device emitting KEYDOWN
        class FakeDev:
            def poll(self):
                return [events.Key(events.KEYDOWN, "A", keys.K_a, 0, 0, None)]

        self.app.register(FakeDev())
        evs = self.app.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].key, keys.K_a)

        self.app.off(events.KEYDOWN, received.append)
        evs = self.app.poll()
        self.assertEqual(len(received), 1)

    def test_on_decorator_and_multi_event(self):
        received = []

        @self.app.on([events.MOUSEBUTTONDOWN, events.MOUSEBUTTONUP])
        def handler(e):
            received.append(e.type)

        class FakeDev:
            def poll(self):
                return [
                    events.Button(events.MOUSEBUTTONDOWN, (10, 20), 1, False, None),
                    events.Button(events.MOUSEBUTTONUP, (10, 20), 1, False, None),
                ]

        self.app.register(FakeDev())
        self.app.poll()
        self.assertEqual(received, [events.MOUSEBUTTONDOWN, events.MOUSEBUTTONUP])


class TestTimerSubscriptions(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def tearDown(self):
        self.app._perform_teardown()

    def test_every_direct_and_decorator(self):
        hits_direct = []
        hits_dec = []

        sub = self.app.every(20, hits_direct.append)

        @self.app.every(50)
        def on_tick(t):
            hits_dec.append(t)

        subs = [t for t in self.app.timers if t.name != "app.service"]
        self.assertEqual(len(subs), 2)
        sub.cancel()
        subs = [t for t in self.app.timers if t.name != "app.service"]
        self.assertEqual(len(subs), 1)


class TestDeviceAdapters(unittest.TestCase):
    def test_touch_adapter(self):
        disp = _FakeDisplay(width=100, height=200, rotation=0)
        samples = [(10, 20)]
        touch = Touch(read=lambda: samples.pop(0) if samples else (), display=disp)

        # First sample -> MOUSEBUTTONDOWN
        evs = touch.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.MOUSEBUTTONDOWN)
        self.assertEqual(evs[0].pos, (10, 20))

        # Release -> MOUSEBUTTONUP
        evs = touch.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.MOUSEBUTTONUP)
        self.assertEqual(evs[0].pos, (10, 20))

    def test_touch_injection(self):
        disp = _FakeDisplay(width=100, height=200)
        touch = Touch(read=lambda: (), display=disp)
        touch.inject_tap(50, 60)

        ev_down = touch.poll()
        self.assertEqual(len(ev_down), 1)
        self.assertEqual(ev_down[0].type, events.MOUSEBUTTONDOWN)
        self.assertEqual(ev_down[0].pos, (50, 60))

        ev_up = touch.poll()
        self.assertEqual(len(ev_up), 1)
        self.assertEqual(ev_up[0].type, events.MOUSEBUTTONUP)

    def test_keypad_adapter(self):
        state = [set([keys.K_SPACE])]
        keypad = Keypad(read=lambda: state.pop(0) if state else set())

        # Press
        evs = keypad.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.KEYDOWN)
        self.assertEqual(evs[0].key, keys.K_SPACE)

        # Release
        evs = keypad.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.KEYUP)
        self.assertEqual(evs[0].key, keys.K_SPACE)

    def test_encoder_adapter(self):
        pos_values = [0, 3]
        btn_values = [True, False]
        encoder = Encoder(
            read=lambda: pos_values.pop(0) if pos_values else 3,
            button_read=lambda: btn_values.pop(0) if btn_values else False,
        )

        # First poll sees button press (True) and position change (3)
        evs = encoder.poll()
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0].type, events.MOUSEBUTTONDOWN)
        self.assertEqual(evs[1].type, events.MOUSEWHEEL)
        self.assertEqual(evs[1].y, 3)

    def test_joystick_adapter(self):
        driver = _FakeJoystickDriver()
        joy = Joystick(driver)

        # Initial poll baseline
        self.assertEqual(joy.poll(), [])

        # Axis change
        driver.axes[0] = 0.8
        evs = joy.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.JOYAXISMOTION)
        self.assertEqual(evs[0].axis, 0)
        self.assertAlmostEqual(evs[0].value, 0.8)

        # Button change
        driver.buttons[1] = True
        evs = joy.poll()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].type, events.JOYBUTTONDOWN)
        self.assertEqual(evs[0].button, 1)

    def test_host_events_adapter_quit_chord(self):
        disp = _FakeDisplay()
        disp.quit_chord = (keys.K_q, keys.KMOD_CTRL)

        events_stream = [
            [events.Key(events.KEYDOWN, "q", keys.K_q, keys.KMOD_CTRL, 0, None)],
            [events.Key(events.KEYUP, "q", keys.K_q, keys.KMOD_CTRL, 0, None)],
        ]
        host = HostEvents(
            host_read=lambda: events_stream.pop(0) if events_stream else [],
            display=disp,
        )

        ev_quit = host.poll()
        self.assertEqual(len(ev_quit), 1)
        self.assertEqual(ev_quit[0].type, events.QUIT)

        ev_swallowed = host.poll()
        self.assertEqual(ev_swallowed, [])


class TestMappers(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def tearDown(self):
        self.app._perform_teardown()

    def test_touch_grid(self):
        clicks = []
        releases = []
        grid = TouchGrid(
            self.app,
            x=0,
            y=0,
            w=300,
            h=300,
            cols=3,
            rows=3,
            keys=[1, 2, 3, 4, 5, 6, 7, 8, 9],
            on_press=clicks.append,
            on_release=releases.append,
        )

        # Simulate touch in middle cell (col 1, row 1 -> key 5)
        btn_down = events.Button(events.MOUSEBUTTONDOWN, (150, 150), 1, False, None)
        btn_up = events.Button(events.MOUSEBUTTONUP, (150, 150), 1, False, None)

        # Dispatch
        for cb in self.app._event_callbacks.get(events.MOUSEBUTTONDOWN, ()):
            cb(btn_down)
        self.assertEqual(clicks, [5])
        self.assertEqual(grid.read_held(), [5])

        for cb in self.app._event_callbacks.get(events.MOUSEBUTTONUP, ()):
            cb(btn_up)
        self.assertEqual(releases, [5])
        self.assertEqual(grid.read_held(), [])
        self.assertEqual(grid.read(), [5])

    def test_joy_map(self):
        joymap = {
            1: {
                "hats": {0: [keys.K_LEFT, keys.K_RIGHT, keys.K_DOWN, keys.K_UP]},
                "buttons": {0: keys.K_RETURN},
            }
        }
        jm = JoyMap(self.app, joymap)

        # Button down
        ev_btn = events.JoyButtonDown(events.JOYBUTTONDOWN, 1, 0)
        for cb in self.app._event_callbacks.get(events.JOYBUTTONDOWN, ()):
            cb(ev_btn)
        self.assertEqual(jm.read(), [keys.K_RETURN])

        # Hat motion
        ev_hat = events.JoyHatMotion(events.JOYHATMOTION, 1, 0, (-1, 0))
        for cb in self.app._event_callbacks.get(events.JOYHATMOTION, ()):
            cb(ev_hat)
        self.assertIn(keys.K_LEFT, jm.read())
        self.assertIn(keys.K_RETURN, jm.read())


class TestDisplayRefreshCoordination(unittest.TestCase):
    def test_refresh_paused_context(self):
        disp = _FakeDisplay(needs_refresh=True)
        app = App(displays=[disp])
        self.assertFalse(app._refresh_paused)

        with app.refresh_paused():
            self.assertTrue(app._refresh_paused)

        self.assertFalse(app._refresh_paused)
        app._perform_teardown()


if __name__ == "__main__":
    unittest.main()
