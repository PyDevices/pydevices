# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Who owns the main thread after the script body ends.

The dispatcher answers *how a callback reaches the main thread*. This module
answers the separate question *who holds the main thread once the script's
last line has run*, which is what ``app.run()`` used to exist for.

Three strategies, chosen once by :func:`install`:

``ambient``
    The host already runs a loop that outlives the script body: a browser
    page, a Jupyter kernel, an MCU REPL after ``main.py``, or ``-i``. Nothing
    to do but register teardown.

``exit_hook``
    Script mode on CPython, MicroPython or CircuitPython. An interpreter exit
    hook takes the main thread during shutdown and delivers timers until
    :func:`multimer.alive` is false: ``keepalive`` was cleared or no timer is
    armed. The script "drops out the bottom" and the program keeps running.

``none``
    No mechanism, or the entry point is ``-m`` / ``-c`` (a test runner or a
    one-liner, never an app). The caller blocks explicitly
    (``multimer.run_until``).

This is ``appdev._hostloop`` moved down a layer; the classification code is
unchanged and its tests still apply.
"""

import sys

AMBIENT = "ambient"
EXIT_HOOK = "exit_hook"
NONE = "none"

_state = {
    "strategy": None,
    "on_stop": [],
    "started": False,
    "stopped": False,
    "crashed": False,
    "claimed": False,
}


# ---------------------------------------------------------------------------
# Host classification
# ---------------------------------------------------------------------------


def _impl():
    return getattr(sys.implementation, "name", "")


def _mcu():
    """True on microcontroller firmware, as opposed to a desktop OS build."""
    return _impl() in ("micropython", "circuitpython") and sys.platform not in (
        "linux",
        "win32",
        "darwin",
    )


def _main_file():
    """``__main__.__file__``, or None at a bare REPL."""
    m = sys.modules.get("__main__")
    if m is None:
        try:
            import __main__ as m
        except Exception:
            return None
    return getattr(m, "__file__", None)


def _cmdline_tokens():
    """Argv tokens including flags, or () when unavailable.

    ``sys.argv`` omits interpreter flags on every implementation we target, so
    the real command line has to come from the OS. ``/proc/self/cmdline``
    covers Linux (and Android); ``GetCommandLineW`` covers Windows, including
    ``micropython.exe`` where there is no ``/proc``.
    """
    try:
        with open("/proc/self/cmdline", "rb") as f:
            toks = tuple(t.decode() for t in f.read().split(b"\0") if t)
        if toks:
            return toks
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            return _win32_cmdline()
        except Exception:
            pass
    # CPython 3.10+ keeps the flags itself (macOS has no /proc).
    argv = getattr(sys, "orig_argv", None)
    if argv:
        return tuple(argv)
    return ()


def _win32_cmdline():
    """Command line via ``kernel32!GetCommandLineW`` (CPython and MicroPython)."""
    if _impl() == "micropython":
        import ffi
        import uctypes

        k32 = ffi.open("kernel32.dll")
        get = k32.func("p", "GetCommandLineW", "")
        addr = get()
        out = bytearray()
        off = 0
        while True:
            pair = uctypes.bytes_at(addr + off, 2)
            if pair == b"\0\0":
                break
            out += pair
            off += 2
        text = _utf16le(out)
    else:
        import ctypes

        ctypes.windll.kernel32.GetCommandLineW.restype = ctypes.c_wchar_p
        text = ctypes.windll.kernel32.GetCommandLineW()
    return tuple(_split_cmdline(text))


def _utf16le(data):
    """Decode UTF-16LE by hand: MicroPython has no ``utf-16-le`` codec."""
    chars = []
    for i in range(0, len(data) - 1, 2):
        code = data[i] | (data[i + 1] << 8)
        chars.append("?" if 0xD800 <= code <= 0xDFFF else chr(code))
    return "".join(chars)


def _split_cmdline(text):
    """Minimal CommandLineToArgvW: enough to spot a bare ``-i`` flag."""
    out = []
    cur = []
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch in " \t" and not in_quotes:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def ambient():
    """True when the host runs a loop that outlives the script body.

    Browser/wasm and Jupyter own the program lifecycle outright. MicroPython
    firmware drops to a REPL after ``main.py``, and the REPL runs scheduled
    callbacks while it waits, so it is a real ambient loop. CircuitPython is
    excluded: its supervisor resets the port after ``code.py`` returns.
    """
    if sys.platform in ("emscripten", "webassembly"):
        return True
    try:
        import pyscript  # noqa: F401

        return True
    except Exception:
        pass
    try:
        get_ipython()  # noqa: F821
        return True
    except Exception:
        pass
    if _mcu() and _impl() == "micropython":
        return True
    return False


def interactive():
    """True when a REPL prompt will remain after the current top-level work."""
    if _impl() == "cpython":
        flags = getattr(sys, "flags", None)
        if getattr(flags, "interactive", 0):
            return True
        # ``python -c`` has no ``__main__.__file__`` either, but no prompt
        # follows it: it is a batch entry, like ``-m``.
        return _main_file() is None and not batch()
    if _mcu() and _impl() == "circuitpython":
        # CircuitPython cannot tell code.py from the REPL, and delivers
        # nothing in the background either way: the exit hook is the only
        # thing that can hold the VM.
        return False
    toks = _cmdline_tokens()
    if toks:
        if "-i" in toks:
            return True
        if "-c" in toks or "-m" in toks:
            return False
    main = _main_file()
    return main is None or main in ("<stdin>", "<string>")


def batch():
    """True when the interpreter was started with ``-m`` or ``-c``."""
    toks = _cmdline_tokens()
    return "-m" in toks or "-c" in toks


def on_exit(fn):
    """Register ``fn()`` to run at interpreter shutdown. True when registered."""
    try:
        import atexit

        atexit.register(fn)
        return True
    except ImportError:
        pass
    hook = getattr(sys, "atexit", None)
    if hook is not None:
        try:
            hook(fn)
            return True
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# Crash guard
# ---------------------------------------------------------------------------


def _crashed():
    """True when the script body died with an uncaught exception."""
    if _state["crashed"]:
        return True
    try:
        return sys.exc_info()[0] is not None
    except Exception:
        return False


def _install_crash_guard():
    prev = getattr(sys, "excepthook", None)
    if prev is None:
        return

    def _hook(exc_type, exc, tb):
        if not issubclass(exc_type, SystemExit):
            _state["crashed"] = True
        prev(exc_type, exc, tb)

    try:
        sys.excepthook = _hook
    except Exception:
        pass


def mark_crashed():
    """Suppress the exit-hook loop (the program is not in a runnable state)."""
    _state["crashed"] = True


def claim():
    """The caller is running the loop itself (``run_until``); the hook only tears down."""
    _state["claimed"] = True


def release():
    _state["claimed"] = False


def on_stop(fn):
    """Register teardown to run when the process stops keeping the program alive."""
    if fn not in _state["on_stop"]:
        _state["on_stop"].append(fn)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _stop():
    if _state["stopped"]:
        return
    _state["stopped"] = True
    for fn in tuple(_state["on_stop"]):
        try:
            fn()
        except BaseException:
            pass


def _cp_break_watch():
    """Zero-arg "did the user press Ctrl-C" probe for CircuitPython, else None.

    CircuitPython does not arm Ctrl-C as an interrupt character while an
    atexit handler runs: it arrives as stdin data. A loop that never reads
    stdin fills the USB CDC ring and the board stops answering every tool
    that could recover it. Draining the ring each pass fixes both halves.
    """
    if _impl() != "circuitpython" or not _mcu():
        return None
    try:
        import supervisor

        rt = supervisor.runtime
    except Exception:
        return None
    try:
        backlog = rt.serial_bytes_available
        if backlog:
            sys.stdin.read(backlog)
    except Exception:
        pass

    def pressed():
        try:
            waiting = rt.serial_bytes_available
            if not waiting:
                return False
            return "\x03" in sys.stdin.read(waiting)
        except Exception:
            return False

    return pressed


def _run_loop():
    from . import _dispatch

    interrupted = _cp_break_watch()
    while _dispatch.alive():
        wait = _dispatch.next_delay_ms()
        _dispatch.sleep_ms(50 if wait is None else min(wait, 50))
        if interrupted is not None and interrupted():
            break


def _exit_hook():
    # Never let an exception escape: MicroPython turns an uncaught exception
    # in sys.atexit into "FATAL: uncaught NLR", CPython prints a traceback.
    try:
        if not _state["claimed"] and not _crashed():
            _run_loop()
    except BaseException:
        pass
    _stop()
    try:
        from . import _dispatch

        _dispatch.stop_all()
        _dispatch.stop_source()
    except BaseException:
        pass


def ensure_installed():
    """Decide the strategy once; idempotent and never raises."""
    if _state["strategy"] is not None:
        return _state["strategy"]
    try:
        return _install()
    except BaseException:
        _state["strategy"] = NONE
        return NONE


def _install():
    if ambient() or interactive():
        _state["strategy"] = AMBIENT
        on_exit(_stop)
        _maybe_input_hook()
        return AMBIENT
    if batch():
        on_exit(_stop)
        _state["strategy"] = NONE
        return NONE
    _install_crash_guard()
    if on_exit(_exit_hook):
        _state["strategy"] = EXIT_HOOK
        return EXIT_HOOK
    _state["strategy"] = NONE
    return NONE


def _maybe_input_hook():
    if _impl() != "cpython":
        return
    try:
        get_ipython()  # noqa: F821
        return  # the kernel owns the hook and the loop
    except Exception:
        pass
    try:
        from . import _inputhook

        _inputhook.install()
    except Exception:
        pass


def strategy():
    """The strategy chosen, or None before a timer was armed."""
    return _state["strategy"]


def _reset_for_test():
    _state["strategy"] = None
    _state["on_stop"] = []
    for k in ("started", "stopped", "crashed", "claimed"):
        _state[k] = False
