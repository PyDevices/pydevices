"""Letting the UI thread in while the worker thread loops.

The VM passes the GIL on only every 32 backward jumps, so a loop whose
iterations are mostly calls -- building 30 list entries, each a few
milliseconds of Python -- held it for ~300 ms, and the UI thread (which runs
LVGL) froze behind it on the LCD-7 (2026-09-25). Work that loops calls
cooperate(); on the worker thread that sleeps 1 ms, which releases the GIL.
"""

import time

try:
    import _thread
except ImportError:
    _thread = None

_worker_ident = None


def set_worker_thread():
    """Called once by the worker thread itself."""
    global _worker_ident
    if _thread is not None:
        _worker_ident = _thread.get_ident()


def cooperate():
    if _worker_ident is not None and _thread.get_ident() == _worker_ident:
        time.sleep_ms(1) if hasattr(time, "sleep_ms") else time.sleep(0.001)
