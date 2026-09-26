# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Serve timers while CPython's REPL waits for a key (``PyOS_InputHook``).

readline calls the hook about every 100 ms while idle and after each
keystroke; Python 3.13's ``_pyrepl`` calls it from its own wait loop on both
the Unix and the Windows console. Waiting in the hook's *own* loop, on stdin,
delivering as deadlines pass and returning the moment a key arrives, makes
delivery at the prompt as punctual as anywhere else instead of 100 ms
coarse. The hook is installed only when the slot is empty, so a host that
owns it (matplotlib, IPython) keeps it.
"""

import sys

if sys.implementation.name != "cpython":
    raise ImportError("PyOS_InputHook is CPython's")

import ctypes

_HOOK = ctypes.CFUNCTYPE(ctypes.c_int)
_installed = None
_wait_for_key = None
_MAX_SLICE_MS = 50


def _unix_wait(fd):
    import select

    def wait(ms):
        try:
            r, _, _ = select.select([fd], [], [], ms / 1000.0)
        except (OSError, ValueError):
            return True
        return bool(r)

    return wait


def _win32_wait(fd):
    import msvcrt

    k32 = ctypes.windll.kernel32
    handle = msvcrt.get_osfhandle(fd)

    def wait(ms):
        # 0 means signalled; a console handle signals on any input record.
        return k32.WaitForSingleObject(ctypes.c_void_p(handle), int(ms)) == 0

    return wait


def _hook():
    from . import _dispatch

    try:
        while True:
            wait = _dispatch.deliver()
            if wait is None:
                return 0
            if _wait_for_key(min(wait, _MAX_SLICE_MS)):
                return 0
    except Exception:
        return 0


def install():
    """Install the hook if stdin is usable and the slot is free. True if installed."""
    global _installed, _wait_for_key
    if _installed is not None:
        return True
    try:
        import os

        if os.environ.get("MULTIMER_INPUTHOOK", "1") == "0":
            return False  # tests prove the hook matters by turning it off
    except Exception:
        pass
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return False
    slot = ctypes.c_void_p.in_dll(ctypes.pythonapi, "PyOS_InputHook")
    if slot.value:
        return False
    _wait_for_key = _win32_wait(fd) if sys.platform == "win32" else _unix_wait(fd)
    cfunc = _HOOK(_hook)
    slot.value = ctypes.cast(cfunc, ctypes.c_void_p).value
    _installed = cfunc  # keep the trampoline alive for the life of the process
    return True


def installed():
    return _installed is not None
