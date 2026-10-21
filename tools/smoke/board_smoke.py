# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The board smoke test. It runs on the board (or a desktop interpreter).

It checks what a board package promises: ``board_config`` imports, the
display draws, touch reads, and each peripheral in ``PERIPHERALS`` answers
(its factory builds one without raising). Roles that would take the board
away, such as ``sleep``, are looked up but never called. It prints one line,
``SMOKE {json}``, for ``tools/mark_tested.py`` to read.

``tools/mark_tested.py`` runs it for you. To run it by hand, copy it to the
board and run it; set ``SMOKE_SKIP`` (a list of roles) and ``SMOKE_PATH`` (a
folder to import the board package from) in front of it if you need to.
"""

import gc
import json
import sys
import time

try:
    _skip = set(SMOKE_SKIP)  # noqa: F821  (set by mark_tested.py)
except NameError:
    _skip = set()
try:
    sys.path.insert(0, SMOKE_PATH)  # noqa: F821
except NameError:
    pass

# Roles whose factory takes the board away (it sleeps, resets or powers off).
# A smoke test never calls these: it only proves the role is there and callable.
NEVER_CALL = frozenset({"sleep", "lightsleep", "deepsleep", "reset", "soft_reset", "bootloader", "poweroff", "power_off", "shutdown"})

_checks = []


def _run(name, fn):
    started = time.ticks_ms()
    try:
        detail = fn()
        ok = True
    except Exception as exc:  # noqa: BLE001  (every failure is a result here)
        detail = "{}: {}".format(type(exc).__name__, exc)
        ok = False
    _checks.append({"check": name, "ok": ok, "detail": str(detail)[:120], "ms": time.ticks_diff(time.ticks_ms(), started)})
    return ok


def _close(obj):
    for name in ("deinit", "close", "stop"):
        method = getattr(obj, name, None)
        if callable(method):
            try:
                method()
            except Exception:  # noqa: BLE001
                pass
            return


def _import():
    import board_config  # noqa: F401

    return "imported"


gc.collect()
_free_before = gc.mem_free() if hasattr(gc, "mem_free") else None
_run("board_config imports", _import)
bc = sys.modules.get("board_config")

if bc is not None and getattr(bc, "display_drv", None) is not None:

    def _draw():
        display = bc.display_drv
        w, h = display.width, display.height
        display.fill_rect(0, 0, w, h, 0x0000)
        display.fill_rect(w // 4, h // 4, w // 2, h // 2, 0x07E0)
        show = getattr(display, "show", None)
        if callable(show):
            show()
        return "{}x{}, a green square".format(w, h)

    _run("display draws", _draw)

if bc is not None and callable(getattr(bc, "touch_read", None)):
    _run("touch reads", lambda: "read {!r}".format(bc.touch_read()))

_peripherals = sys.modules.get("board_peripherals")
_factories = set(getattr(_peripherals, "FACTORY_ROLES", ())) if _peripherals else set()
for _role in sorted(getattr(bc, "PERIPHERALS", ()) if bc is not None else ()):
    if _role in _skip:
        continue

    def _answer(role=_role):
        obj = getattr(bc, role)
        if role in NEVER_CALL:
            if not callable(obj):
                raise TypeError("{} is not callable".format(role))
            return "present, not called"
        if role in _factories:
            obj = obj()
            kind = type(obj).__name__
            _close(obj)
            return kind
        return type(obj).__name__

    _run(_role + " answers", _answer)

_skipped = sorted(_skip & set(getattr(bc, "PERIPHERALS", ()) if bc is not None else ()))
gc.collect()
_result = {
    "board_ok": all(c["ok"] for c in _checks),
    "checks": _checks,
    "skipped": _skipped,
    "firmware": "{} {} ({})".format(
        sys.implementation.name,
        ".".join(str(n) for n in sys.implementation.version[:3]),
        getattr(sys.implementation, "_machine", sys.platform),
    ),
    "free_before": _free_before,
    "free_after": gc.mem_free() if hasattr(gc, "mem_free") else None,
}
try:
    import os

    _result["firmware"] += ", " + os.uname().version
except (ImportError, AttributeError):
    pass
print("SMOKE " + json.dumps(_result))
