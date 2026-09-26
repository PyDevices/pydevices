# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A worker thread and ``Py_AddPendingCall`` as the wake source (CPython).

The thread only keeps time. When a deadline passes it asks the interpreter
to run one C callback on the main thread at its next bytecode boundary; that
callback runs the dispatcher. So callbacks land on the main thread on every
CPython, Windows and Android included, with no signal, no APC, no alertable
wait and no SDL timer thread.

The interpreter's pending-call queue holds 32 entries and refuses more, so
this source keeps at most one outstanding and retries a refusal a
millisecond later. A pending call does not wake a blocked ``time.sleep``;
``multimer.sleep_ms`` sleeps only until the next deadline, and the REPL's
input hook covers the prompt.
"""

import sys

if sys.implementation.name != "cpython":
    raise ImportError("pending source is CPython only")

import ctypes
import threading
import time

name = "pending"
delivery = "bytecode"
wakes_blocking = False

_wake = None
_cond = threading.Condition()
_deadline = None  # perf_counter seconds, or None when idle
_stop = False
_thread = None
_pending = False

_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)


def _on_main(_arg):
    global _pending
    _pending = False
    w = _wake
    if w is not None:
        w()
    return 0


_cfunc = _CB(_on_main)  # referenced for the life of the module


def _worker():
    global _pending
    add = ctypes.pythonapi.Py_AddPendingCall
    add.restype = ctypes.c_int
    add.argtypes = [_CB, ctypes.c_void_p]
    with _cond:
        while not _stop:
            if _deadline is None:
                _cond.wait()
                continue
            now = time.perf_counter()
            if now < _deadline:
                _cond.wait(_deadline - now)
                continue
            if _pending:
                # Already asked; the main thread has not got there yet.
                _cond.wait(0.001)
                continue
            _pending = True
            rc = add(_cfunc, None)
            if rc != 0:
                _pending = False
                _cond.wait(0.001)
                continue
            # Delivered once the main thread reaches a bytecode boundary. The
            # dispatcher re-arms from there; until it does, stay idle.
            _set_deadline_locked(None)


def _set_deadline_locked(value):
    global _deadline
    _deadline = value
    _cond.notify()


def start(wake):
    global _wake, _thread, _stop
    _wake = wake
    _stop = False
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_worker, name="multimer-pending", daemon=True)
        _thread.start()


def arm(delay_ms):
    with _cond:
        _set_deadline_locked(time.perf_counter() + max(0, int(delay_ms)) / 1000.0)


def cancel():
    with _cond:
        _set_deadline_locked(None)


def stop():
    global _stop, _wake
    with _cond:
        _stop = True
        _set_deadline_locked(None)
    _wake = None
