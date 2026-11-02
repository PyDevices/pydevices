# multimer types: queued, sync
"""
keyboard_test.py — verify keyboard input reaches an LVGL textarea.

Run with the SDL window focused:

    micropython apps/spotify_remote/keyboard_test.py

Click the text field, type, and watch characters appear. VALUE_CHANGED
events are printed to the REPL.
"""

import lvgl as lv
import display_driver  # NOQA


scr = lv.screen_active()

title = lv.label(scr)
title.set_text("Type in the field below")
title.align(lv.ALIGN.TOP_MID, 0, 12)
title.set_width(scr.get_width() - 20)

ta = lv.textarea(scr)
ta.set_size(min(scr.get_width() - 40, 400), 44)
ta.align(lv.ALIGN.CENTER, 0, 0)
ta.set_one_line(True)
ta.set_placeholder_text("Type here...")
lv.group_focus_obj(ta)


def on_change(_event):
    print("text:", repr(ta.get_text()))


ta.add_event_cb(on_change, lv.EVENT.VALUE_CHANGED, None)

print("Keyboard test ready — click the field and type.")