# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The running asyncio loop as the wake source (Jupyter, PyScript, async apps).

``loop.call_later`` to the earliest deadline; the callback runs the
dispatcher at an await point of the loop that owns the process. Cells and
pages return to that loop, so timers keep firing after a cell or the script
body ends. Only chosen when a loop is already running, or the host is one
whose lifecycle is a loop (``pyscript``, ``get_ipython``).
"""

import sys

if sys.implementation.name != "cpython":
    raise ImportError("asyncio source is CPython only")

import asyncio

name = "asyncio"
delivery = "idle"
wakes_blocking = False

_wake = None
_loop = None
_handle = None


def _fire():
    global _handle
    _handle = None
    w = _wake
    if w is not None:
        w()


def start(wake):
    global _wake, _loop
    _wake = wake
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        # Jupyter with no cell coroutine running, PyScript at import:
        # the loop exists and will run; a not-yet-running loop is fine too.
        _loop = asyncio.get_event_loop()


def arm(delay_ms):
    global _handle
    loop = _loop
    if loop is None:
        return
    if _handle is not None:
        _handle.cancel()
        _handle = None
    try:
        _handle = loop.call_later(max(0, int(delay_ms)) / 1000.0, _fire)
    except RuntimeError:
        # Called from another thread: hand it to the loop's thread.
        loop.call_soon_threadsafe(arm, delay_ms)


def cancel():
    global _handle
    if _handle is not None:
        _handle.cancel()
        _handle = None


def stop():
    global _wake
    cancel()
    _wake = None
