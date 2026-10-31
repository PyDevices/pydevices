# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The panel's contract, run on whichever interpreter runs this file.

Prints one ``PASS name`` or ``FAIL name: why`` line per check, then the
frame costs, and exits 1 if anything failed. ``--plant`` swaps in the old
panel's handling of a patch change (move the patch selector, nothing else),
so the patch-follow checks must fail: that is how test_controlpanel.py knows
they can.

    micropython panel_contract.py [width height] [--plant]
"""

import sys

import _headless
import lvgl as lv

argv = sys.argv[1:]
PLANT = "--plant" in argv
numbers = [int(a) for a in argv if a.isdigit()]
WIDTH, HEIGHT = (numbers[0], numbers[1]) if len(numbers) >= 2 else (800, 480)

_headless.display(WIDTH, HEIGHT)
_areas = []


def _clock_us():
    import time

    if hasattr(time, "ticks_us"):
        return time.ticks_us()
    return int(time.perf_counter() * 1000000)


from controlpanel import build  # noqa: E402
from controlpanel import panel as panel_module  # noqa: E402
from controlpanel.mock import MockAdapter  # noqa: E402

if PLANT:
    # The old panel: a patch change moved the selector and nothing else.
    def _old_apply(self, kind, index, value):
        self._echoing = True
        try:
            if kind == "macro" and index < len(self.encoders):
                self.encoders[index].set_value(value)
            elif kind == "patch" and self.pads:
                self._select(value)
        finally:
            self._echoing = False

    panel_module.Panel._apply_external = _old_apply

failures = []


def check(name, ok, why=""):
    if ok:
        print("PASS " + name)
    else:
        print("FAIL %s: %s" % (name, why))
        failures.append(name)


def fresh(**kw):
    screen = lv.obj(None)
    lv.screen_load(screen)
    group = lv.group_create()
    adapter = MockAdapter(**kw)
    panel = build(adapter, screen=screen, group=group)
    _headless.refresh()
    return adapter, panel, group, screen


def shown(panel):
    return [enc.value for enc in panel.encoders]


def ring_matches(panel, values):
    # Each ring's lit LEDs must match its value: LED i is lit when the value
    # passes i/16 of the range.
    for enc, value in zip(panel.encoders, values):
        lit = sum(1 for level in enc.lit() if level)
        expected = sum(1 for i in range(16) if value * 16 / 127 - i >= 24 / 255)
        if lit != expected:
            return False
    return True


# ---- built from the adapter ----------------------------------------------------

adapter, panel, group, screen = fresh()
check("sixteen encoders and sixteen pads", len(panel.encoders) == 16 and len(panel.pads) == 16)
check("encoders open on the adapter's values", shown(panel) == adapter.macro_values, str(shown(panel)))
check("rings open on the adapter's values", ring_matches(panel, adapter.macro_values))
check("patch 1 is lit", panel.pads[0][3] == "lit" and panel.patch == 0)
check("the display names the patch", panel.display.text(0).startswith("A01 Init"), panel.display.text(0))

# ---- a patch change from the host (the engine's order: patch, then macros) ----

before = list(adapter.edits)
adapter.host_program(7)
check("host patch: every encoder follows", shown(panel) == adapter.macro_values, "%s != %s" % (shown(panel), adapter.macro_values))
check("host patch: every ring follows", ring_matches(panel, adapter.macro_values))
check("host patch: pad 8 is lit", panel.pads[7][3] == "lit" and panel.pads[0][3] != "lit")
check("host patch: nothing is published back", adapter.edits == before, str(adapter.edits))
check("host patch: the display follows", panel.display.text(0).startswith("A08 "), panel.display.text(0))

adapter.host_program(21)
check("host patch in bank B: the bank turns", panel.bank == 1 and panel.pads[5][3] == "lit", "bank %d" % panel.bank)
check("host patch in bank B: encoders follow", shown(panel) == adapter.macro_values)
screen.delete()

# ---- the same, from an adapter that reports only the patch ----------------------

adapter, panel, group, screen = fresh(echo=False)
adapter.host_program(9)
# This adapter reports the patch before its macros change, and never reports
# them; the panel catches up on its next tick.
_headless.advance(200)
check("patch-only adapter: every encoder follows", shown(panel) == adapter.macro_values, "%s != %s" % (shown(panel), adapter.macro_values))
check("patch-only adapter: every ring follows", ring_matches(panel, adapter.macro_values))
check("patch-only adapter: reset point is the new patch", [panel.default_value(i) for i in range(16)] == adapter.macro_values)
screen.delete()

# ---- host automation ---------------------------------------------------------------

adapter, panel, group, screen = fresh()
adapter.host_parameter(3, 99)
check("automation moves its encoder", panel.encoders[3].value == 99)
check("automation publishes nothing", adapter.edits == [], str(adapter.edits))

# ---- the user turns, resets, picks ---------------------------------------------------

enc = panel.encoders[2]
start = enc.value
lv.group_focus_obj(enc.obj)
group.set_editing(True)
group.send_data(lv.KEY.RIGHT)
check("a key turns the focused encoder", enc.value == start + 1 and adapter.edits[-1] == ("macro", 2, start + 1), str(adapter.edits[-1:]))
check("an edited patch is marked", panel.display.text(0)[3] == "*", panel.display.text(0))
check("the display shows the value", panel.display.text(1).startswith("ENV AMT") and panel.display.text(1).endswith("%d" % (start + 1)), panel.display.text(1))
_headless.advance(2000)
check("the display returns to idle", panel.display.text(1).startswith("READY"), panel.display.text(1))
group.send_data(lv.KEY.END)
check("End turns it fully up", enc.value == 127)
adapter.host_parameter(3, panel.default_value(3))
enc.obj.send_event(lv.EVENT.DOUBLE_CLICKED, None)
check("a double-click returns it to the patch's value", enc.value == start and adapter.macro_values[2] == start)
check("back at the patch's values, the mark goes", panel.display.text(0)[3] == " ", panel.display.text(0))

panel.fine = True
group.send_data(lv.KEY.RIGHT)
group.send_data(lv.KEY.RIGHT)
check("fine mode steps one at a time", enc.value == start + 2, str(enc.value))
panel.fine = False

panel.pads[4][0].send_event(lv.EVENT.CLICKED, None)
check("a pad picks its patch", adapter.patch_index == 4 and ("patch", 4, 4) in adapter.edits)
check("a pad moves every encoder", shown(panel) == adapter.macro_values)

panel.banks[1][0].send_event(lv.EVENT.CLICKED, None)
check("a bank button shows its bank", panel.bank == 1 and panel.pads[0][2].get_text() == adapter.patches[16])
panel.pads[2][0].send_event(lv.EVENT.CLICKED, None)
check("a pad in bank B picks patch 19", adapter.patch_index == 18 and panel.display.text(0).startswith("B03 "), panel.display.text(0))

panel.buttons["BYPASS"][0].send_event(lv.EVENT.CLICKED, None)
check("bypass publishes and shows", adapter.bypass and adapter.edits[-1] == ("bypass", 0, True) and panel.display.text(1).startswith("BYPASSED"), panel.display.text(1))
panel.buttons["RELOAD"][0].send_event(lv.EVENT.CLICKED, None)
check("reload asks the engine", adapter.reloads == 1)
adapter.engine_error = 3
panel.refresh_status()
check("an engine error shows", panel.display.text(1).startswith("ENGINE ERROR 3"), panel.display.text(1))
adapter.engine_error = 0
screen.delete()

# ---- by hand: drag, double-click, wheel ------------------------------------------------

adapter, panel, group, screen = fresh()
_headless.pointer()
enc = panel.encoders[5]
area = lv.area_t()
enc.obj.get_coords(area)
x = (area.x1 + area.x2) // 2
y = (area.y1 + area.y2) // 2 + 10
start = enc.value
target = min(127, start + 40)
_headless.touch(x, y, False)
_headless.touch(x, y, True)
step = panel.travel * (target - start) // 127 + 1
for i in range(1, 11):
    _headless.touch(x, y - step * i // 10, True)
_headless.touch(x, y - step, False)
check("dragging up turns it up", abs(enc.value - target) <= 1 and adapter.macro_values[5] == enc.value, "%d -> %d, wanted %d" % (start, enc.value, target))
_headless.touch(x, y, True, 30)
_headless.touch(x, y, False, 60)
_headless.touch(x, y, True, 30)
_headless.touch(x, y, False, 300)
check("a double-click resets it", enc.value == start, "%d, wanted %d" % (enc.value, start))
_headless.wheel(group)
_headless.turn(3)
check("the wheel turns the clicked encoder", enc.value > start and adapter.macro_values[5] == enc.value, "%d" % enc.value)
group.set_editing(False)
_headless.turn(1)


def _where(obj):
    a = lv.area_t()
    obj.get_coords(a)
    return (a.x1, a.y1)


check("out of edit mode the wheel moves on to the next encoder", _where(group.get_focused()) == _where(panel.encoders[6].obj), "%s vs %s, enc5 %s" % (_where(group.get_focused()), _where(panel.encoders[6].obj), _where(panel.encoders[5].obj)))
screen.delete()

# ---- fewer macros, no patches ---------------------------------------------------------

adapter, panel, group, screen = fresh(patch_count=0, macro_count=4)
check("no patches: no pads", panel.pads == [] and panel.display.text(0).startswith("DEMO SYNTH"))
check("four macros: four take focus", group.get_obj_count() == 4, str(group.get_obj_count()))
screen.delete()

# ---- what a frame costs ------------------------------------------------------------------

adapter, panel, group, screen = fresh()
screen.invalidate()
t0 = _clock_us()
full_pixels = _headless.refresh()
full_us = _clock_us() - t0
check("a full frame redraws the whole screen", full_pixels >= WIDTH * HEIGHT, "%d px" % full_pixels)

disp = lv.display_get_default()
steps = 32
t0 = _clock_us()
pixels = 0
for _ in range(steps):
    adapter.host_parameter(0, (adapter.macro_values[0] + 1) % 128)
    pixels += _headless.refresh()
step_us = (_clock_us() - t0) // steps
pixels //= steps
check("a one-step turn redraws under 2% of the screen", pixels < WIDTH * HEIGHT // 50, "%d px" % pixels)

t0 = _clock_us()
adapter.host_program(12)
_headless.refresh()
patch_us = _clock_us() - t0
print("COST %dx%d full_frame_ms=%.1f step_redraw_ms=%.2f step_pixels=%d patch_change_ms=%.1f" % (
    WIDTH, HEIGHT, full_us / 1000, step_us / 1000, pixels, patch_us / 1000))

print("RESULT %s" % ("FAIL" if failures else "OK"))
sys.exit(1 if failures else 0)
