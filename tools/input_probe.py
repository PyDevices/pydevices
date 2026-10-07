#!/usr/bin/env python3
"""Core input / keypad diagnostic (no LVGL required).

Use this when debugging keyboard and hardware keypad behavior. It exercises
the same ``events.Key`` contract every displaydev backend must emit.

## Layers (fix at the lowest layer that owns the bug)

1. **displaydev** (``sdldisplay`` / ``pgdisplay`` / ``psdisplay`` / ``jndisplay``)
   — native → ``events.Key`` conversion (repeat, scancode, mod, name).
2. **appdev** (``HostEventsDevice``, ``KeypadDevice``, ``VirtualDevices``)
   — quit chords, hardware keypad, FIFO fan-out to virtual keypad.
Applications consume these layers via ``app.poll()`` and
``app.on(KEYDOWN, …)``.

## Usage (from the ``pydevices`` repo root)

Self-tests (no window focus needed)::

    python tools/input_probe.py --selftest
    micropython tools/input_probe.py --selftest

Interactive host dump (needs a board config and display backend; focus window)::

    PYTHONPATH=lib:board_configs/desktop python tools/input_probe.py

Print the historical fix checklist::

    python tools/input_probe.py --fixes

Quit: platform quit chord (usually Ctrl+Q).

## Historical fix checklist (A-E; implemented - see ``--fixes``)

Ordered by layer. Each item is a targeted change with acceptance criteria.

### A. appdev — ``KeypadDevice`` name must not use ``chr(key)`` (multi-backend / HW)

- **Where:** ``appdev/_keypad.py`` ``_poll``.
- **Bug:** ``chr(keys.K_UP)`` etc. raises ``ValueError`` (SDL scancode-masked
  codes). FunHouse ``board_config`` feeds ``keys.K_UP`` / ``K_DOWN``.
- **Fix:** Set ``name`` via ``keys.keyname(key)`` (or ``""`` / hex fallback),
  never ``chr(key)`` for arbitrary ints. Keep ``key`` as the int code.
- **Accept:** ``KeypadDevice(read=lambda: {keys.K_UP}).poll()`` returns a
  ``KEYDOWN``; FunHouse up/down no longer crash the auto-service tick.
- **Tests:** ``--selftest`` case ``keypad_chr_safe``; board smoke if available.

### B. displaydev — document + unify key-repeat policy (SDL/pygame vs browser)

- **Where:** ``sdldisplay._convert``, ``pgdisplay._convert`` vs
  ``psdisplay``/``jndisplay`` (already drop ``e.repeat``).
- **Bug:** Desktop floods ``KEYDOWN`` on hold; browser emits one. Apps that
  count downs (or LVGL keypad FIFO drain) behave differently per backend.
- **Fix (choose one contract, apply consistently):**
  1. **Preferred for parity with browser:** drop OS auto-repeat at SDL/pygame
     convert (``if e.key.repeat: continue`` / pygame equivalent), **or**
  2. Expose ``repeat`` on ``events.Key`` (new field or reuse unused slot) and
     document that consumers must ignore repeats if they want edge semantics;
     then stop silently dropping only on browser.
- **Accept:** Hold ``a`` for 2s → same ``KEYDOWN`` count on SDL and PyScript
  under the chosen contract; ``--selftest`` cannot fully prove OS repeat
  (manual hold in interactive mode + ``downs[key]`` counter).
- **Do not** coalesce only in LVGL — non-LVGL apps share this path.

### C. appdev — keypad virtual-device FIFO backpressure (LVGL path, multi-display)

- **Where:** ``appdev/_host.py`` ``VirtualDevice.add_event`` (keypad fifo).
- **Bug:** Only ``MOUSEMOTION`` coalesces; key fifo is uncapped; LVGL drains
  ~1 event per indev period. SDL repeat (B) + slow UI → lagged "playback".
- **Fix:** Coalesce consecutive identical ``KEYDOWN`` events and preserve an
  explicit release edge when a different key overlaps the active keypad key.
- **Accept:** Hold Backspace 3s then type — no multi-second backlog of
  deletes; fifo length stays bounded under load (probe ``fifo_depth``).

### D. appdev — browser ``mod_mask`` left-only (browser backends)

- **Where:** ``appdev/keys.py`` ``mod_mask``.
- **Bug:** Ambient ``event.mod`` never sets ``KMOD_R*`` even when right
  modifier keys are held (key events themselves can be ``K_RSHIFT``).
- **Fix:** Either document "always use ``chord_matches`` / ``KMOD_SHIFT``
  groups" as the API contract, **or** track pressed modifier keys and OR
  left/right bits into subsequent events' ``mod`` (host-side or in
  ``PSDevices``/``JNDevices``).
- **Accept:** ``event.mod & KMOD_SHIFT`` true for both Shift keys on all
  backends; apps using group masks work; right-only bit checks documented
  as unsupported on browser unless tracking is added.

### E. Optional — WSLg / remote-desktop keycode notes (docs or SDL normalize)

- **Where:** comment or normalize in ``sdldisplay`` if hosts emit
  ``SDL_SCANCODE_TO_KEYCODE`` for letters (``key | 0x40000000``) instead of
  ASCII.
- **Fix:** If observed on a WSLg path: normalize using
  ``SDL_GetKeyName`` → ASCII/control codes at **sdldisplay** (affects all
  consumers), not only in ``display_driver``.
- **Accept:** Letter ``KEYDOWN`` ``event.key`` in 32..126 on that host;
  ``keys.keyname`` resolves; LVGL and non-LVGL typing both work.

## What this probe prints

Interactive lines::

    KEYDOWN  key=97  keys.K_a  name='A'  mod=0x1  scancode=4  downs=1

Counters expose OS repeat. ``--selftest`` runs automated core checks.
"""

import sys

_file = __file__.replace("\\", "/")
_tools = _file.rsplit("/", 1)[0] if "/" in _file else "."
_root = _tools.rsplit("/", 1)[0] if "/" in _tools else "."
_src = (_root + "/lib") if _root not in (".", "") else "lib"
for _p in (_src, _tools):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

import events  # noqa: E402
import keys  # noqa: E402
from displaydev._domkeys import enrich_mod, key_to_keycode, mod_mask  # noqa: E402
from appdev import types  # noqa: E402
from appdev._host import VirtualDevices  # noqa: E402
from appdev._keypad import KeypadDevice  # noqa: E402


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _keys_const_name(code):
    for name in dir(keys):
        if name.startswith("K_") and getattr(keys, name, None) == code:
            return name
    return "?"


def _mod_parts(mod):
    if not mod:
        return "0"
    bits = []
    for name in (
        "KMOD_LSHIFT",
        "KMOD_RSHIFT",
        "KMOD_LCTRL",
        "KMOD_RCTRL",
        "KMOD_LALT",
        "KMOD_RALT",
        "KMOD_LGUI",
        "KMOD_RGUI",
        "KMOD_CAPS",
        "KMOD_NUM",
    ):
        bit = getattr(keys, name, 0)
        if bit and (mod & bit) == bit:
            bits.append(name.replace("KMOD_", ""))
    return "0x%x(%s)" % (mod, "|".join(bits) if bits else "?")


def format_key_event(event, downs=None):
    phase = "KEYDOWN" if event.type == events.KEYDOWN else "KEYUP"
    if event.type not in (events.KEYDOWN, events.KEYUP):
        return repr(event)
    code = event.key
    parts = [
        phase,
        "key=%s" % code,
        "keys.%s" % _keys_const_name(code),
        "name=%r" % (getattr(event, "name", None) or ""),
        "mod=%s" % _mod_parts(getattr(event, "mod", 0) or 0),
        "scancode=%s" % getattr(event, "scancode", None),
    ]
    if downs is not None and event.type == events.KEYDOWN:
        parts.append("downs=%d" % downs.get(code, 0))
    # Heuristics that flag known bugs while probing
    if isinstance(code, int) and (code & 0x40000000) and _keys_const_name(code) == "?":
        parts.append("WARN:scancode-masked-unknown")
    if _keys_const_name(code) in (
        "K_LSHIFT",
        "K_RSHIFT",
        "K_LCTRL",
        "K_RCTRL",
        "K_LALT",
        "K_RALT",
        "K_LGUI",
        "K_RGUI",
    ):
        parts.append("NOTE:modifier-key")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Self-tests (automated evidence; no display focus)
# ---------------------------------------------------------------------------
class _ProbeResult:
    def __init__(self):
        self.ok = 0
        self.fail = 0
        self.lines = []

    def check(self, name, cond, detail=""):
        if cond:
            self.ok += 1
            self.lines.append("PASS  %s" % name)
        else:
            self.fail += 1
            self.lines.append("FAIL  %s  %s" % (name, detail))


def run_selftest():
    r = _ProbeResult()

    # A — KeypadDevice must not crash on SDL-masked navigation codes
    for label, code in (
        ("K_UP", keys.K_UP),
        ("K_DOWN", keys.K_DOWN),
        ("K_LEFT", keys.K_LEFT),
        ("K_RIGHT", keys.K_RIGHT),
        ("K_ESCAPE", keys.K_ESCAPE),
    ):
        held = {code}

        def _read(h=held):
            return h

        dev = KeypadDevice(read=_read)
        try:
            out = dev.poll()
            r.check(
                "keypad_chr_safe_%s" % label,
                len(out) == 1 and out[0].type == events.KEYDOWN and out[0].key == code,
                "got %r" % (out,),
            )
        except Exception as exc:
            r.check(
                "keypad_chr_safe_%s" % label,
                False,
                "%s: %s (expected after fix A)" % (type(exc).__name__, exc),
            )

    # ASCII path still works
    held_a = {ord("a")}
    dev_a = KeypadDevice(read=lambda: held_a)
    out_a = dev_a.poll()
    r.check("keypad_ascii_a", len(out_a) == 1 and out_a[0].key == 97, repr(out_a))
    r.check(
        "keypad_up_name",
        KeypadDevice(read=lambda: {keys.K_UP}).poll()[0].name
        == keys.keyname(keys.K_UP),
    )

    # D — bare mod_mask stays left-only; enrich_mod adds right bits from pressed keys
    m = mod_mask(True, True, True, True)
    r.check("mod_mask_has_LSHIFT", bool(m & keys.KMOD_LSHIFT))
    r.check("mod_mask_lacks_RSHIFT", not (m & keys.KMOD_RSHIFT), "hex=%s" % hex(m))
    enriched = enrich_mod(m, {keys.K_RSHIFT, keys.K_RCTRL})
    r.check("enrich_mod_RSHIFT", bool(enriched & keys.KMOD_RSHIFT))
    r.check("enrich_mod_RCTRL", bool(enriched & keys.KMOD_RCTRL))
    r.check(
        "chord_matches_group_RCTRL",
        keys.chord_matches((keys.K_q, keys.KMOD_CTRL), keys.K_q, keys.KMOD_RCTRL),
    )
    r.check(
        "key_to_keycode_Shift_right",
        key_to_keycode("Shift", 2) == keys.K_RSHIFT,
    )

    # C — same-key KEYDOWN coalesce + KEYUP purge
    class _FakeHost:
        type = types.HOST

        def poll(self):
            return []

    vd = VirtualDevices(_FakeHost())
    kp = vd._vd_keypad
    for _ in range(5):
        kp.add_event(events.Key(events.KEYDOWN, "a", ord("a"), 0, 0, None))
    r.check("keypad_fifo_coalesce", len(kp._fifo) == 1, "len=%d" % len(kp._fifo))
    kp.add_event(events.Key(events.KEYDOWN, "b", ord("b"), 0, 0, None))
    r.check(
        "keypad_fifo_rollover_order",
        len(kp._fifo) == 3
        and kp._fifo[0].type == events.KEYDOWN
        and kp._fifo[0].key == ord("a")
        and kp._fifo[1].type == events.KEYUP
        and kp._fifo[1].key == ord("a")
        and kp._fifo[2].type == events.KEYDOWN
        and kp._fifo[2].key == ord("b"),
        "fifo=%r" % (kp._fifo,),
    )
    kp.add_event(events.Key(events.KEYUP, "a", ord("a"), 0, 0, None))
    r.check(
        "keypad_fifo_late_keyup_ignored",
        len(kp._fifo) == 3 and kp._fifo[-1].key == ord("b"),
        "fifo=%r" % (kp._fifo,),
    )
    kp.add_event(events.Key(events.KEYUP, "b", ord("b"), 0, 0, None))
    r.check(
        "keypad_fifo_active_keyup_preserved",
        len(kp._fifo) == 4
        and kp._fifo[-1].type == events.KEYUP
        and kp._fifo[-1].key == ord("b"),
        "fifo=%r" % (kp._fifo,),
    )

    print("=== input_probe selftest ===")
    for line in r.lines:
        print(line)
    print("----")
    print("%d passed, %d failed" % (r.ok, r.fail))
    return 0 if r.fail == 0 else 1


# Keep in sync with the module docstring fix checklist (MicroPython
# scripts often have ``__doc__ is None``).
_FIXES_TEXT = """
Historical fixes implemented (acceptance criteria)

Ordered by layer. Each item is a targeted change with acceptance criteria.

A. appdev — KeypadDevice name must not use chr(key) (multi-backend / HW)
   Where: appdev/_keypad.py _poll
   Fix: keys.keyname(key) or "" / hex fallback — never chr(key) for arbitrary ints
   Accept: KeypadDevice(read=lambda: {keys.K_UP}).poll() returns KEYDOWN

B. displaydev — unify key-repeat policy (SDL/pygame vs browser)
   Where: sdldisplay/pgdisplay _convert vs psdisplay/jndisplay (already drop repeat)
   Fix: either drop OS repeat on desktop for parity, OR expose repeat on events.Key
        and stop silently dropping only on browser
   Accept: hold a key 2s → same KEYDOWN count on SDL and PyScript under chosen contract

C. appdev — keypad virtual-device FIFO backpressure
   Where: appdev/_host.py VirtualDevice.add_event (keypad fifo)
   Fix: coalesce same-key KEYDOWN and preserve release edges across key rollover
   Accept: hold Backspace then type — no multi-second backlog; fifo stays bounded

D. appdev — browser mod_mask left-only
   Where: appdev/keys.py mod_mask
   Fix: document group-mask API, or track pressed modifiers into event.mod
   Accept: event.mod & KMOD_SHIFT true for both Shift keys on all backends

E. Optional — WSLg/remote-desktop letter normalization (sdldisplay if observed)
   Where: sdldisplay when letters arrive as key|0x40000000
   Fix: normalize via SDL_GetKeyName at sdldisplay (all consumers), not only LVGL
   Accept: letter event.key in 32..126 on that host
"""


def print_fixes():
    print(_FIXES_TEXT.strip())


# ---------------------------------------------------------------------------
# Interactive host probe
# ---------------------------------------------------------------------------
def run_interactive():
    import board_config
    from appdev import App

    app = App(board_config)

    downs = {}
    pressed = set()
    fifo_note = {"last_warn": 0}

    def _on_key(event):
        if event.type == events.KEYDOWN:
            downs[event.key] = downs.get(event.key, 0) + 1
            pressed.add(event.key)
        elif event.type == events.KEYUP:
            pressed.discard(event.key)
        print(format_key_event(event, downs=downs))
        # Chord sample: Ctrl+Shift+letter
        mod = getattr(event, "mod", 0) or 0
        if (
            event.type == events.KEYDOWN
            and (mod & keys.KMOD_CTRL)
            and (mod & keys.KMOD_SHIFT)
        ):
            print(
                "  chord: Ctrl+Shift+%s  chord_matches(Ctrl)=%s"
                % (
                    _keys_const_name(event.key),
                    keys.chord_matches((event.key, keys.KMOD_CTRL), event.key, mod),
                )
            )

    def _tick(_=None):
        # Report virtual-keypad FIFO depth when a host has virtual peers.
        try:
            from appdev._host import _vd_peers

            for host in app.devices:
                if getattr(host, "type", None) != types.HOST:
                    continue
                peers = _vd_peers.get(id(host)) or []
                for vd in peers:
                    depth = len(vd._vd_keypad._fifo)
                    if depth >= 8 and depth != fifo_note["last_warn"]:
                        print("WARN keypad_fifo_depth=%d (fix C backlog)" % depth)
                        fifo_note["last_warn"] = depth
        except Exception:
            pass

    print("input_probe: focus the display window, then press keys.")
    print("Watch downs= for OS key-repeat. Modifiers show NOTE:modifier-key.")
    print(
        "Try: letters, Shift+letter, Shift+1, arrows, Tab, Backspace hold, Ctrl+Q quit."
    )
    print("held keys / down counts update live.\n")

    for et in (events.KEYDOWN, events.KEYUP):
        app.on(et, _on_key)
    app.on_tick(_tick, period=200, async_=False)
    app.run()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--fixes" in argv:
        print_fixes()
        return 0
    if "--selftest" in argv:
        return run_selftest()
    if "--lvgl" in argv:
        print("--lvgl moved to pydevices-examples/tools/lvgl_input_probe.py")
        return 2
    run_interactive()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0) from None
