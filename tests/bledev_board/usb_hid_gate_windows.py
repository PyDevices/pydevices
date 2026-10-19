# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The HID gate over USB, Windows' half: hear what ``usb_hid_gate.py`` types, and check it.

Run with a Windows Python, with pydevices' ``lib`` and this folder on the path::

    PYTHONPATH="$(wslpath -w lib);$(wslpath -w tests/bledev_board)" \\
        python.exe "$(wslpath -w tests/bledev_board/usb_hid_gate_windows.py)" 30

For ``SECONDS`` (default 30) it hooks the keyboard and the mouse at the
lowest level Windows offers to an app (``WH_KEYBOARD_LL``, ``WH_MOUSE_LL``)
and swallows everything that isn't injected, so the text, the chords, the
media keys and the click reach no window: start the board's script while it
listens. Then it compares what it heard with ``hid_script``:

- the text typed, read with Shift as a US keyboard reads it, equals
  ``hid_script.TEXT``;
- every key event of ``hid_script.expected()`` (gamepad left out) arrived,
  down and up, and nothing else: the same keys the same number of times;
- Ctrl+C and Right Alt+Left Shift+F5 arrived as chords, the modifiers held
  when the key went down;
- the mouse moved right and up, then left and down, clicked the left button
  once and turned the wheel one notch away.

The keyboard and mouse you are using are swallowed too while it listens.
Consumer control (volume, play/pause) is a HID collection Windows hands to
the shell, past these hooks, so it would act on the PC: with
``--skip consumer`` (and ``usb_hid_gate.SKIP = ("consumer",)`` on the
board) those steps are left out on both sides.
Prints one JSON line and ``RESULT PASS`` or ``RESULT FAIL``.
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time

import events
import hid_script

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# The hook's points are physical pixels; without this, GetCursorPos's are scaled.
user32.SetProcessDPIAware()

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
LLKHF_UP, LLKHF_INJECTED = 0x80, 0x10
LLMHF_INJECTED = 0x01
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEWHEEL = 0x200, 0x201, 0x202, 0x20A
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = (wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = (wt.HHOOK,)
user32.PeekMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
user32.GetCursorPos.argtypes = (ctypes.POINTER(wt.POINT),)
kernel32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wt.HMODULE

# HID usage (what hid_script.expected() puts in a Key's scancode) to the
# virtual key Windows reports for it.
VK = {0x28: 0x0D, 0x2B: 0x09, 0x2C: 0x20, 0x2D: 0xBD, 0x2E: 0xBB, 0x2F: 0xDB, 0x30: 0xDD, 0x31: 0xDC,
      0x33: 0xBA, 0x34: 0xDE, 0x35: 0xC0, 0x36: 0xBC, 0x37: 0xBE, 0x38: 0xBF, 0x3E: 0x74,
      0xE0: 0xA2, 0xE1: 0xA0, 0xE2: 0xA4, 0xE3: 0x5B, 0xE4: 0xA3, 0xE5: 0xA1, 0xE6: 0xA5, 0xE7: 0x5C,
      0x000C00E9: 0xAF, 0x000C00CD: 0xB3}
for _u in range(0x04, 0x1E):
    VK[_u] = 0x41 + _u - 0x04  # a..z
for _u in range(0x1E, 0x27):
    VK[_u] = 0x31 + _u - 0x1E  # 1..9
VK[0x27] = 0x30  # 0

# US layout: virtual key to (plain, shifted) character.
CHARS = {0x0D: ("\n", "\n"), 0x09: ("\t", "\t"), 0x20: (" ", " "), 0xBD: ("-", "_"), 0xBB: ("=", "+"),
         0xDB: ("[", "{"), 0xDD: ("]", "}"), 0xDC: ("\\", "|"), 0xBA: (";", ":"), 0xDE: ("'", '"'),
         0xC0: ("`", "~"), 0xBC: (",", "<"), 0xBE: (".", ">"), 0xBF: ("/", "?")}
for _i, (_p, _s) in enumerate(zip("1234567890", "!@#$%^&*()")):
    CHARS[0x31 + _i if _p != "0" else 0x30] = (_p, _s)
for _c in range(26):
    CHARS[0x41 + _c] = (chr(0x61 + _c), chr(0x41 + _c))
MODS = {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}
SHIFTS = {0xA0, 0xA1}

heard_keys, heard_mouse = [], []


def _keyboard(n, wparam, lparam):
    if n == 0:
        k = KBDLLHOOKSTRUCT.from_address(lparam)
        if not k.flags & LLKHF_INJECTED:
            heard_keys.append(("up" if k.flags & LLKHF_UP else "down", k.vkCode))
            return 1  # swallowed: no window sees it
    return user32.CallNextHookEx(None, n, wparam, lparam)


def _mouse(n, wparam, lparam):
    if n == 0:
        m = MSLLHOOKSTRUCT.from_address(lparam)
        if not m.flags & LLMHF_INJECTED:
            if wparam == WM_MOUSEMOVE:
                cur = wt.POINT()
                user32.GetCursorPos(ctypes.byref(cur))
                heard_mouse.append(("move", m.pt.x - cur.x, m.pt.y - cur.y))
            elif wparam == WM_MOUSEWHEEL:
                heard_mouse.append(("wheel", ctypes.c_short(m.mouseData >> 16).value))
            else:
                heard_mouse.append(({WM_LBUTTONDOWN: "left down", WM_LBUTTONUP: "left up"}.get(wparam, hex(wparam)),))
            return 1
    return user32.CallNextHookEx(None, n, wparam, lparam)


def listen(seconds):
    kp, mp = HOOKPROC(_keyboard), HOOKPROC(_mouse)
    mod = kernel32.GetModuleHandleW(None)
    # The pointer starts mid-screen, so no edge clamps a move the board makes.
    user32.SetCursorPos(user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 2)
    hk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kp, mod, 0)
    hm = user32.SetWindowsHookExW(WH_MOUSE_LL, mp, mod, 0)
    if not hk or not hm:
        sys.exit("could not hook: error %d" % ctypes.get_last_error())
    print("listening", flush=True)
    msg = wt.MSG()
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                pass
            time.sleep(0.002)
    finally:
        user32.UnhookWindowsHookEx(hk)
        user32.UnhookWindowsHookEx(hm)


def presses(keys):
    """(key, modifiers held at any point while it was down) for each key
    press, in order. A chord is one report, and Windows may hand out its key
    before its modifiers or after, so a modifier pressed while the key is
    still down counts too."""
    held, out, open_ = set(), [], {}
    for kind, vk in keys:
        if kind == "down":
            if vk in MODS:
                held.add(vk)
                for i in open_.values():
                    out[i][1].add(vk)
            else:
                open_[vk] = len(out)
                out.append((vk, set(held)))
        else:
            held.discard(vk)
            open_.pop(vk, None)
    return out


def typed(keys):
    text = ""
    for vk, mods in presses(keys):
        if mods - SHIFTS or vk not in CHARS:
            continue  # a chord or a media key, not typing
        text += CHARS[vk][1 if mods & SHIFTS else 0]
    return text


def chords(keys):
    return [(tuple(sorted(mods)), vk) for vk, mods in presses(keys) if mods - SHIFTS]


def main():
    args = sys.argv[1:]
    skip = ()
    if "--skip" in args:
        i = args.index("--skip")
        skip = tuple(args[i + 1].split(","))
        del args[i:i + 2]
    seconds = float(args[0]) if args else 30
    listen(seconds)
    steps = tuple(st for st in hid_script.STEPS if st[0] not in skip)
    want = [("down" if e.type == events.KEYDOWN else "up", VK[e.scancode])
            for e in hid_script.expected(steps, has_gamepad=False) if e.type in (events.KEYDOWN, events.KEYUP)]
    text = typed(heard_keys)
    got_chords = chords(heard_keys)
    want_chords = [((0xA2,), 0x43), ((0xA0, 0xA5), 0x74)]
    moves = [m for m in heard_mouse if m[0] == "move"]
    others = [m for m in heard_mouse if m[0] != "move"]
    mouse_ok = (len(moves) == 2 and moves[0][1] > 0 and moves[0][2] < 0 and moves[1][1] < 0 and moves[1][2] > 0
                and others == [("left down",), ("left up",), ("wheel", 120)])
    keys_ok = sorted(heard_keys) == sorted(want)
    # Each key went down before it last came up.
    order_ok = keys_ok and all(heard_keys.index(("down", vk)) < len(heard_keys) - heard_keys[::-1].index(("up", vk))
                               for _, vk in want)
    result = {"text": text, "text_ok": text == hid_script.TEXT, "key_events": len(heard_keys),
              "key_events_expected": len(want), "keys_ok": order_ok,
              "chords": [[["%02x" % m for m in mods], "%02x" % vk] for mods, vk in got_chords],
              "chords_ok": got_chords == want_chords, "mouse": heard_mouse, "mouse_ok": mouse_ok}
    if not keys_ok:
        extra = list(heard_keys)
        for e in want:
            if e in extra:
                extra.remove(e)
        missing = list(want)
        for e in heard_keys:
            if e in missing:
                missing.remove(e)
        result["unexpected"] = [[k, "%02x" % v] for k, v in extra[:10]]
        result["missing"] = [[k, "%02x" % v] for k, v in missing[:10]]
    print(json.dumps(result))
    ok = result["text_ok"] and result["keys_ok"] and result["chords_ok"] and mouse_ok
    print("RESULT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
