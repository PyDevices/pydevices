# SPDX-FileCopyrightText: 2021 Amir Gonnen
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""POSIX timer signal as the wake source (CPython and unix MicroPython).

One kernel timer for the whole process, armed one-shot to the earliest
deadline. Its signal reaches the main thread:

* on CPython the Python-level handler runs between two bytecodes of the main
  thread, and a blocking call that the signal interrupts is retried after the
  handler (PEP 475): that is bytecode delivery with sleeps and reads woken;
* on MicroPython the ffi handler runs in signal context with the heap locked,
  so it does exactly one thing: ``micropython.schedule`` the dispatcher. The
  callback then runs at the next bytecode boundary, and a ``read()`` at the
  REPL is interrupted (EINTR), runs pending callbacks, and is retried
  (``ports/unix/mphalport.h``, ``MP_HAL_RETRY_SYSCALL``).

Linux gets a real-time signal from ``timer_create`` so nothing shares it;
other POSIX hosts fall back to ``setitimer`` on SIGALRM.
"""

import sys

if sys.platform not in ("linux", "darwin"):
    raise ImportError("signal source needs a POSIX host")

name = "signal"
delivery = "bytecode"
wakes_blocking = True

_CLOCK_MONOTONIC = 1
_SIGEV_THREAD_ID = 4
_wake = None
_armed_ms = None

_USE_CTYPES = sys.implementation.name == "cpython"

if _USE_CTYPES:
    import ctypes
    import signal

    _libc = ctypes.CDLL(None, use_errno=True)
    _have_timer_create = hasattr(_libc, "timer_create") and sys.platform == "linux"

    class _timespec(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

    class _itimerspec(ctypes.Structure):
        _fields_ = [("it_interval", _timespec), ("it_value", _timespec)]

    class _sigval(ctypes.Union):
        _fields_ = [("sival_int", ctypes.c_int), ("sival_ptr", ctypes.c_void_p)]

    class _sigevent(ctypes.Structure):
        _fields_ = [
            ("sigev_value", _sigval),
            ("sigev_signo", ctypes.c_int),
            ("sigev_notify", ctypes.c_int),
            ("sigev_notify_thread_id", ctypes.c_int),
            ("_pad", ctypes.c_char * 40),
        ]

    _timer = None
    _signo = None

    def _handler(_signum, _frame=None):
        w = _wake
        if w is not None:
            w()

    def start(wake):
        global _wake, _timer, _signo
        _wake = wake
        if _have_timer_create:
            _libc.timer_create.restype = ctypes.c_int
            _libc.timer_create.argtypes = [ctypes.c_int, ctypes.POINTER(_sigevent), ctypes.POINTER(ctypes.c_void_p)]
            _libc.timer_settime.restype = ctypes.c_int
            _libc.timer_settime.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_itimerspec), ctypes.POINTER(_itimerspec)]
            _libc.timer_delete.restype = ctypes.c_int
            _libc.timer_delete.argtypes = [ctypes.c_void_p]
            _libc.gettid.restype = ctypes.c_int
            _signo = signal.SIGRTMIN + 4
            sev = _sigevent()
            sev.sigev_notify = _SIGEV_THREAD_ID
            sev.sigev_signo = _signo
            sev.sigev_notify_thread_id = _libc.gettid()
            tid = ctypes.c_void_p()
            signal.signal(_signo, _handler)
            if _libc.timer_create(_CLOCK_MONOTONIC, ctypes.byref(sev), ctypes.byref(tid)) != 0:
                signal.signal(_signo, signal.SIG_IGN)
                raise OSError("timer_create failed (errno=%d)" % ctypes.get_errno())
            _timer = tid
        else:
            _signo = signal.SIGALRM
            signal.signal(_signo, _handler)
        # A signal must interrupt a blocking call so the handler runs now;
        # PEP 475 then retries the call for the caller.
        signal.siginterrupt(_signo, True)

    def _settime(ms):
        if _have_timer_create:
            spec = _itimerspec()
            spec.it_value.tv_sec = ms // 1000
            spec.it_value.tv_nsec = (ms % 1000) * 1_000_000
            if ms == 0:
                spec.it_value.tv_nsec = 0
            _libc.timer_settime(_timer, 0, ctypes.byref(spec), None)
        else:
            signal.setitimer(signal.ITIMER_REAL, ms / 1000.0, 0)

    def arm(delay_ms):
        global _armed_ms
        # 0 disarms a POSIX timer; the smallest positive value fires at once.
        ms = int(delay_ms)
        if ms <= 0:
            if _have_timer_create:
                spec = _itimerspec()
                spec.it_value.tv_nsec = 1
                _libc.timer_settime(_timer, 0, ctypes.byref(spec), None)
            else:
                signal.setitimer(signal.ITIMER_REAL, 1e-6, 0)
            _armed_ms = 0
            return
        _armed_ms = ms
        _settime(ms)

    def cancel():
        global _armed_ms
        _armed_ms = None
        _settime(0)

    def stop():
        global _timer, _wake
        cancel()
        if _have_timer_create and _timer is not None:
            _libc.timer_delete(_timer)
            _timer = None
        if _signo is not None:
            try:
                signal.signal(_signo, signal.SIG_IGN)
            except Exception:
                pass
        _wake = None

else:
    import array

    import ffi
    import uctypes

    _libc = ffi.open("libc.so.6")
    try:
        _librt = ffi.open("librt.so.1")
    except OSError:
        _librt = _libc

    _timer_create_ = _librt.func("i", "timer_create", "ipp")
    _timer_delete_ = _librt.func("i", "timer_delete", "P")
    _timer_settime_ = _librt.func("i", "timer_settime", "PiPp")
    _sigaction_ = _libc.func("i", "sigaction", "iPp")
    _sigrtmin = _libc.func("i", "__libc_current_sigrtmin", "")()
    try:
        _gettid = _libc.func("i", "gettid", "")
    except OSError:
        _syscall = _libc.func("l", "syscall", "l")

        def _gettid():
            return _syscall(186)

    _sigaction_t = {
        "sa_handler": 0 | uctypes.UINT64,
        "sa_mask": (8 | uctypes.ARRAY, 16 | uctypes.UINT64),
        "sa_flags": 136 | uctypes.INT32,
        "sa_restorer": (144 | uctypes.PTR, uctypes.UINT8),
    }
    _sigevent_t = {
        "sigev_value": 0 | uctypes.UINT64,
        "sigev_signo": 8 | uctypes.INT32,
        "sigev_notify": 12 | uctypes.INT32,
        "sigev_notify_thread_id": 16 | uctypes.INT32,
    }
    _timespec_t = {"tv_sec": 0 | uctypes.INT64, "tv_nsec": 8 | uctypes.INT64}
    _itimerspec_t = {"it_interval": (0, _timespec_t), "it_value": (16, _timespec_t)}

    def _struct(desc):
        buf = bytearray(uctypes.sizeof(desc))
        return uctypes.struct(uctypes.addressof(buf), desc, uctypes.NATIVE), buf

    _timer = None
    _signo = None
    _cb = None
    _keep = []
    # Pre-built itimerspec so arm() allocates nothing it does not have to.
    _spec, _spec_buf = _struct(_itimerspec_t)
    _old, _old_buf = _struct(_itimerspec_t)

    def _handler(_signum):
        # Signal context, heap locked: schedule and return.
        w = _wake
        if w is not None:
            w()

    def start(wake):
        global _wake, _timer, _signo, _cb
        _wake = wake
        _signo = _sigrtmin + 4
        _cb = ffi.callback("v", _handler, "i", lock=True)
        sa, sa_buf = _struct(_sigaction_t)
        sa_old, sa_old_buf = _struct(_sigaction_t)
        sa.sa_handler = _cb.cfun()
        _keep.extend((sa_buf, sa_old_buf))
        if _sigaction_(_signo, sa, sa_old) != 0:
            raise OSError("sigaction failed")
        sev, sev_buf = _struct(_sigevent_t)
        _keep.append(sev_buf)
        sev.sigev_notify = _SIGEV_THREAD_ID
        sev.sigev_signo = _signo
        sev.sigev_notify_thread_id = _gettid()
        tid = array.array("P", [0])
        if _timer_create_(_CLOCK_MONOTONIC, sev, tid) != 0:
            raise OSError("timer_create failed")
        _timer = tid[0]

    def arm(delay_ms):
        global _armed_ms
        ms = int(delay_ms)
        _spec.it_interval.tv_sec = 0
        _spec.it_interval.tv_nsec = 0
        if ms <= 0:
            _spec.it_value.tv_sec = 0
            _spec.it_value.tv_nsec = 1
            _armed_ms = 0
        else:
            _spec.it_value.tv_sec = ms // 1000
            _spec.it_value.tv_nsec = (ms % 1000) * 1000000
            _armed_ms = ms
        _timer_settime_(_timer, 0, _spec, _old)

    def cancel():
        global _armed_ms
        _armed_ms = None
        _spec.it_value.tv_sec = 0
        _spec.it_value.tv_nsec = 0
        _spec.it_interval.tv_sec = 0
        _spec.it_interval.tv_nsec = 0
        _timer_settime_(_timer, 0, _spec, _old)

    def stop():
        global _timer, _wake
        if _timer is not None:
            cancel()
            _timer_delete_(_timer)
            _timer = None
        if _signo is not None:
            sa, sa_buf = _struct(_sigaction_t)
            sa_old, sa_old_buf = _struct(_sigaction_t)
            sa.sa_handler = 1  # SIG_IGN: a late signal must not kill the process
            _sigaction_(_signo, sa, sa_old)
        _wake = None
