# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``wifi_manager``: which networks it tries and in what order, setup mode's
way out, and a setup screen that an app switch has deleted.

The radio, the clock and the screen are fakes, so nothing here touches a
network. On a weak link a scan misses a known network about half the time
and a join fails once and then works, so the join order and the two rounds
are what keep a board on its network.
"""

import unittest

import _env  # noqa: F401
import wifi_manager as wm

_clock = [0]


class FakeRadio:
    """``scan()`` returns *seen*; ``join()`` takes its result for each SSID
    from *script* (``None`` joins, a string is the reason it didn't), and
    fails with "network not found" once a script runs out."""

    def __init__(self, seen=None, script=None):
        self.seen = seen
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.joins = []
        self.address = None
        self.ap = None

    def scan(self):
        if self.seen is None:
            raise OSError("scan failed")
        return dict(self.seen)

    def join(self, ssid, password, timeout):
        self.joins.append(ssid)
        results = self.script.get(ssid) or ["network not found"]
        err = results.pop(0)
        if err is None:
            self.address = "10.0.0.5"
        return err

    def ip(self):
        return self.address

    def mac(self):
        return b"\x00\x11\x22\x33\x44\x55"

    def start_ap(self, ssid, password):
        self.ap = ssid
        return "192.168.4.1"

    def stop_ap(self):
        self.ap = None


class FakeUI:
    def __init__(self):
        self.shown = None
        self.statuses = []
        self.closed = False

    def show(self, ap_name, ap_pass, url):
        self.shown = (ap_name, url)

    def status(self, text, ok=False, error=False):
        self.statuses.append(text)

    def close(self):
        self.closed = True


def _net(ssid, hidden=False):
    return {"ssid": ssid, "password": "pw-" + ssid, "hidden": hidden}


class _Patched(unittest.TestCase):
    """Fakes in place of the stores, the clock and the sleep."""

    def setUp(self):
        self._saved = {
            name: getattr(wm, name)
            for name in ("_known", "_remember", "_sleep_ms", "_ticks_ms", "_ticks_diff", "_make_ui")
        }
        self.known = []
        self.remembered = []
        _clock[0] = 0
        self.sleeps = 0
        self.on_sleep = None
        wm._known = lambda: list(self.known)
        wm._remember = lambda ssid, password, hidden=False: self.remembered.append(ssid)
        wm._ticks_ms = lambda: _clock[0]
        wm._ticks_diff = lambda a, b: a - b
        wm._sleep_ms = self._sleep
        wm._cancelled = False

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(wm, name, value)
        wm._cancelled = False

    def _sleep(self, ms):
        _clock[0] += ms
        self.sleeps += 1
        if self.on_sleep is not None:
            self.on_sleep(self.sleeps)


class JoinKnownTest(_Patched):
    def test_in_range_first_strongest_first_then_the_rest(self):
        self.known = [_net("away"), _net("weak"), _net("strong")]
        radio = FakeRadio(seen={"weak": -78, "strong": -50, "other": -40})
        self.assertIsNone(wm._join_known(radio, 5))
        self.assertEqual(radio.joins, ["strong", "weak", "away"] * 2)

    def test_a_join_that_fails_once_works_in_the_second_round(self):
        self.known = [_net("home")]
        radio = FakeRadio(seen={"home": -78}, script={"home": ["wrong password", None]})
        self.assertEqual(wm._join_known(radio, 5), "10.0.0.5")
        self.assertEqual(radio.joins, ["home", "home"])
        self.assertEqual(self.remembered, ["home"])

    def test_a_network_the_scan_missed_is_still_tried(self):
        self.known = [_net("home")]
        radio = FakeRadio(seen={"neighbour": -60}, script={"home": [None]})
        self.assertEqual(wm._join_known(radio, 5), "10.0.0.5")
        self.assertEqual(radio.joins, ["home"])

    def test_a_failed_scan_tries_every_known_network(self):
        self.known = [_net("a"), _net("b")]
        radio = FakeRadio(seen=None, script={"b": [None]})
        self.assertEqual(wm._join_known(radio, 5), "10.0.0.5")
        self.assertEqual(radio.joins, ["a", "b"])

    def test_nothing_known_tries_nothing(self):
        radio = FakeRadio(seen={"home": -50})
        self.assertIsNone(wm._join_known(radio, 5))
        self.assertEqual(radio.joins, [])


class SetupModeTest(_Patched):
    def _setup(self, radio, rescan):
        ui = FakeUI()
        wm._make_ui = lambda display_drv: ui
        s = wm._Setup(radio, None, 5, rescan=rescan)
        for name in ("_open_sockets", "_close_sockets", "_serve_dns", "_serve_http"):
            setattr(s, name, lambda *a: None)
        return s, ui

    def test_cancel_ends_setup_without_a_network(self):
        radio = FakeRadio(seen={})
        s, ui = self._setup(radio, rescan=True)
        self.on_sleep = lambda n: n == 3 and wm.cancel()
        self.assertIsNone(s.run())
        self.assertTrue(ui.closed)
        self.assertIsNone(radio.ap)

    def test_a_cancel_from_before_does_not_end_the_next_setup(self):
        wm.cancel()
        radio = FakeRadio(seen={})
        s, ui = self._setup(radio, rescan=True)

        def submit(n):
            if n == 2:
                s.pending = ("home", "pw", False)

        self.on_sleep = submit
        radio.script = {"home": [None]}
        self.assertEqual(s.run(), "10.0.0.5")

    def test_run_waits_for_a_new_network_instead_of_rejoining_a_known_one(self):
        self.known = [_net("home")]
        radio = FakeRadio(seen={"home": -50}, script={"home": [None]})
        s, ui = self._setup(radio, rescan=False)

        def tick(n):
            _clock[0] += (wm.RESCAN_S + 1) * 1000  # a rescan is due every loop
            if n == 5:
                wm.cancel()

        self.on_sleep = tick
        self.assertIsNone(s.run())
        self.assertEqual(radio.joins, [])

    def test_setup_from_connect_rejoins_a_known_network_that_comes_back(self):
        self.known = [_net("home")]
        radio = FakeRadio(seen={}, script={"home": [None]})
        s, ui = self._setup(radio, rescan=True)
        self.on_sleep = lambda n: _clock.__setitem__(0, _clock[0] + (wm.RESCAN_S + 1) * 1000)
        self.assertEqual(s.run(), "10.0.0.5")
        self.assertEqual(radio.joins, ["home"])

    def test_a_network_from_the_page_is_joined_and_remembered(self):
        radio = FakeRadio(seen={"home": -60}, script={"home": [None]})
        s, ui = self._setup(radio, rescan=True)
        s.pending = ("home", "pw", False)
        self.assertEqual(s.run(), "10.0.0.5")
        self.assertEqual(self.remembered, ["home"])
        self.assertTrue(ui.closed)


class _Deleted(Exception):
    pass


class FakeLv:
    def __init__(self, active, deleted=False):
        self.active = active
        self.deleted = deleted
        self.loaded = []

    def screen_active(self):
        if self.deleted:
            raise _Deleted("Referenced object was deleted!")
        return self.active

    def screen_load(self, scr):
        self.loaded.append(scr)

    def color_hex(self, c):
        return c


class FakeObj:
    def __init__(self, deleted=False):
        self.deleted = deleted
        self.deletes = 0
        self.text = None

    def delete(self):
        if self.deleted:
            raise _Deleted("Referenced object was deleted!")
        self.deletes += 1

    def set_style_text_color(self, color, part):
        if self.deleted:
            raise _Deleted("Referenced object was deleted!")

    def set_text(self, text):
        self.text = text


def _lv_ui(lv, scr, prev):
    ui = object.__new__(wm._LvUI)
    ui.lv, ui.scr, ui.prev, ui.status_lbl = lv, scr, prev, FakeObj()
    return ui


class LvglScreenTest(_Patched):
    def test_close_gives_the_screen_back_when_it_is_still_showing(self):
        scr, prev = FakeObj(), FakeObj()
        lv = FakeLv(active=scr)
        ui = _lv_ui(lv, scr, prev)
        ui.close()
        self.assertEqual(lv.loaded, [prev])
        self.assertEqual(scr.deletes, 1)
        self.assertIsNone(ui.scr)

    def test_close_leaves_another_apps_screen_alone(self):
        scr, prev, other = FakeObj(), FakeObj(), FakeObj()
        lv = FakeLv(active=other)
        ui = _lv_ui(lv, scr, prev)
        ui.close()
        self.assertEqual(lv.loaded, [])
        self.assertIsNone(ui.scr)

    def test_close_survives_screens_an_app_switch_deleted(self):
        scr, prev = FakeObj(deleted=True), FakeObj(deleted=True)
        ui = _lv_ui(FakeLv(active=None, deleted=True), scr, prev)
        ui.close()
        self.assertIsNone(ui.scr)

    def test_status_on_a_deleted_label_still_reaches_the_repl(self):
        ui = _lv_ui(FakeLv(active=None), FakeObj(), FakeObj())
        ui.status_lbl = FakeObj(deleted=True)
        ui.status("Joining home...")
        self.assertIsNone(ui.status_lbl)


if __name__ == "__main__":
    unittest.main()
