# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Name keys, match a shortcut, and read a USB keyboard's codes.

keys holds the key codes and modifier masks that keyboard events carry,
the same numbers SDL uses. This shows the three things a program does
with them: turn a code into a name, check for a shortcut like Ctrl+S, and
translate the codes a USB or Bluetooth keyboard sends.

Needs: nothing but the keys module, so no board or keyboard.

Run it:
    micropython keys_simpletest.py

Tested on: the unix ports of MicroPython and CircuitPython, and CPython
3.12 on Linux and 3.14 on Windows.
"""

import keys

# Names and codes go both ways.
print("K_RETURN is called", keys.keyname(keys.K_RETURN))
print("'Escape' is code", keys.key("Escape"))

# A shortcut is a key and the modifiers it needs.
SAVE = (keys.K_s, keys.KMOD_CTRL)
print("Right Ctrl+S saves:", keys.chord_matches(SAVE, keys.K_s, keys.KMOD_RCTRL))
print("Plain S saves:", keys.chord_matches(SAVE, keys.K_s, keys.KMOD_NONE))

# A HID keyboard report says "usage 0x04 with modifier bit 1": Shift+A.
code = keys.hid_keycode(0x04)
mods = keys.hid_modifiers(0b10)
print("The keyboard sent", keys.modname(mods), "+", keys.keyname(code))
