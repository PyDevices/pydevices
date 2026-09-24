# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""appdev._hostloop — decide who owns the main thread after the script body ends.

``multimer`` answers *how callbacks get delivered*. ``hostloop`` answers the
separate question *who holds the main thread once the script's last line has
run*, which is what ``app.run()`` currently exists to answer.

Three strategies, chosen once by :func:`install`:

``ambient``
    The host already runs a loop that outlives the script body: a browser page,
    a Jupyter kernel, an MCU REPL after ``main.py``, or ``-i``. Arm the app's
    timers and install nothing else.

``exit_hook``
    Script mode on CPython / MicroPython / CircuitPython. Register an interpreter
    exit hook that takes the main thread during shutdown and pumps until the app
    quits. The script "drops out the bottom" and the app keeps running.

``none``
    No mechanism available, or the entry point is ``-m`` / ``-c`` (a test runner
    or a one-liner, never an app). The caller must block explicitly
    (``app.run()``).

Private to ``appdev``: it imports nothing from ``appdev`` (or ``multimer``), so
it can be promoted to a top-level package later with a file move and one import
line, but it has no consumer today that does not go through :class:`appdev.App`.

:func:`install` is idempotent and never raises.
"""

import sys

AMBIENT = "ambient"
EXIT_HOOK = "exit_hook"
NONE = "none"

_state = {
    "strategy": None,
    "pump": None,
    "alive": None,
    "on_start": None,
    "on_stop": None,
    "drive": None,
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
    """True on microcontroller firmware, as opposed to a desktop OS build.

    Both MicroPython and CircuitPython also build for linux/win32/darwin, and
    those builds behave like CPython for lifecycle purposes.
    """
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
    return ()


def _win32_cmdline():
    """Command line via ``kernel32!GetCommandLineW`` (CPython and MicroPython)."""
    if _impl() == "micropython":
        import ffi

        k32 = ffi.open("kernel32.dll")
        get = k32.func("p", "GetCommandLineW", "")
        addr = get()
        # UTF-16LE, NUL-terminated. Read until a 16-bit zero.
        import uctypes

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
    """Decode UTF-16LE by hand: MicroPython has no ``utf-16-le`` codec.

    Without this, micropython.exe could never read its own command line, so
    ``-m`` / ``-c`` / ``-i`` all went undetected there. Characters outside the
    BMP come out as ``?``; only the ASCII flags matter here.
    """
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

    Browser/wasm and Jupyter own the program lifecycle outright. MCU firmware
    drops to a REPL after ``main.py``, which keeps hardware timers delivering.
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
    # MicroPython firmware: boot.py/main.py always lands in the REPL, and
    # hardware timers keep delivering there, so the REPL is a real ambient loop.
    #
    # CircuitPython is deliberately excluded. Its supervisor resets the port
    # after code.py returns -- peripherals are deinitialised and nothing keeps
    # pumping -- so an app that returns from run() is simply dead. CircuitPython
    # must drive its own loop inside run().
    if _mcu() and _impl() == "micropython":
        return True
    return False


def interactive():
    """True when a REPL prompt will remain after the current top-level work.

    Under ``-i`` the REPL *is* the ambient loop, and the user quitting it means
    they are done — so the exit hook must not start a second loop afterwards.
    """
    if _impl() == "cpython":
        flags = getattr(sys, "flags", None)
        if getattr(flags, "interactive", 0):
            return True
        return _main_file() is None
    if _mcu() and _impl() == "circuitpython":
        # CircuitPython offers no way to tell code.py from the REPL: __main__
        # carries neither __file__ nor __name__ in either case, and
        # supervisor.runtime.run_reason reports what triggered the last code.py
        # run -- REPL_RELOAD after a Ctrl-D -- not whether one is in progress.
        # The distinction does not matter here. CircuitPython delivers no timers
        # in the background, so an app has to hold the VM whichever way it was
        # started, and the exit hook is the only thing that can hold it.
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
    """True when the interpreter was started with ``-m`` or ``-c``.

    A module or a command string is a deliberate non-app entry point: test
    runners (``python -m unittest``), packaging tools and one-liners all land
    here. Taking the main thread at exit in those would hang the runner, so
    :func:`install` reports :data:`NONE` and the caller keeps ``app.run()``.
    """
    toks = _cmdline_tokens()
    return "-m" in toks or "-c" in toks


def on_exit(fn):
    """Register ``fn()`` to run at interpreter shutdown. True when registered.

    CPython has ``atexit``; MicroPython and CircuitPython expose ``sys.atexit``
    when ``MICROPY_PY_SYS_ATEXIT`` is enabled. ``sys.atexit`` holds one hook, so
    hostloop registers exactly one and does all of its shutdown work inside it.
    """
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
    """True when the script body died with an uncaught exception.

    Exit hooks run even after an uncaught exception (verified on CPython and
    MicroPython), and entering the app loop with a half-built UI hangs the
    process instead of surfacing the error. Two signals, because no single one
    covers every host:

    * CPython clears the exception before ``atexit`` runs, but has
      ``sys.excepthook`` -- wrapped by :func:`_install_crash_guard`.
    * MicroPython and CircuitPython have no ``sys.excepthook``, but the
      exception is still live in ``sys.exc_info()`` inside the hook.
    """
    if _state["crashed"]:
        return True
    try:
        return sys.exc_info()[0] is not None
    except Exception:
        return False


def _install_crash_guard():
    """Wrap ``sys.excepthook`` where it exists (CPython only)."""
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
    """Suppress the exit-hook loop (the app is not in a runnable state)."""
    _state["crashed"] = True


def claim():
    """Tell hostloop the caller is running the loop itself (``app.run()``).

    The exit hook then skips its loop and performs teardown only, so an explicit
    ``run()`` and an installed hook never both drive the app.
    """
    _state["claimed"] = True


def quit():
    """Signal that the app has finished; tear down if nothing else will.

    Under :data:`EXIT_HOOK` the loop notices via ``alive()`` on its next
    iteration, so this is a no-op. Under :data:`AMBIENT` there is no loop of
    ours to notice -- the host's loop would happily keep driving the app's
    timers forever -- so teardown has to happen here. Call from the app's single
    quit choke point (``App._handle_quit``).
    """
    if _state["strategy"] == AMBIENT:
        _stop()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _start():
    if _state["started"]:
        return
    _state["started"] = True
    fn = _state["on_start"]
    if fn is not None:
        fn()


def _stop():
    if _state["stopped"]:
        return
    _state["stopped"] = True
    fn = _state["on_stop"]
    if fn is not None:
        try:
            fn()
        except BaseException:
            pass


def _cp_break_watch():
    """Zero-arg "did the user press Ctrl-C" probe for CircuitPython, else None.

    CircuitPython does not arm Ctrl-C as an interrupt character while an atexit
    handler is running: it arrives as ordinary stdin data instead of raising
    KeyboardInterrupt. A pump loop never reads stdin, so the USB CDC receive
    ring fills, the host's writes start timing out, and the board stops
    answering every tool that could recover it -- a hard reset or a 1200-baud
    bootloader touch becomes the only way back. Draining the ring each pass
    fixes both halves at once: writes keep flowing, and Ctrl-C means quit again.

    Returns None off MCU CircuitPython, where the interpreter handles Ctrl-C
    itself and stdin must be left alone.
    """
    if _impl() != "circuitpython" or not _mcu():
        return None
    try:
        import supervisor

        rt = supervisor.runtime
    except Exception:
        return None

    # Anything already buffered predates this loop and cannot be a request to
    # stop it -- it is typically the Ctrl-C/Ctrl-D a host tool used to start the
    # run in the first place. Drop that backlog once, or the app quits the
    # instant it starts.
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
    pump = _state["pump"]
    alive = _state["alive"]
    if pump is None or alive is None:
        return
    # Note: the drive() path (asyncio-backed apps) does not get this treatment;
    # it owns its own event loop and would need the equivalent drain in there.
    interrupted = _cp_break_watch()
    if interrupted is None:
        while alive():
            pump()
        return
    while alive():
        pump()
        if interrupted():
            break


def _exit_hook():
    # Never let an exception escape: MicroPython turns an uncaught exception in
    # sys.atexit into "FATAL: uncaught NLR" (rc=1), and CPython prints an
    # "Exception ignored in atexit callback" traceback.
    try:
        if not _state["claimed"] and not _crashed():
            drive = _state["drive"]
            if drive is not None:
                # Async app: a synchronous pump loop would never run the event
                # loop, and AsyncTimer would silently never fire. Hand the whole
                # run to the caller, which owns the asyncio entry point (and is
                # responsible for flushing on_start from inside it -- AsyncTimer
                # can only arm once a loop is actually running).
                drive()
            else:
                _start()
                _run_loop()
    except BaseException:
        pass
    _stop()


def install(pump, alive, on_start=None, on_stop=None, drive=None):
    """Arrange for ``pump()`` to be called until ``alive()`` is false.

    Args:
        pump: Zero-arg callable that services timers/events once. Should sleep
            or block briefly so the loop does not spin.
        alive: Zero-arg predicate; the loop runs while it returns true.
        on_start: Zero-arg callable invoked at the moment the loop begins --
            immediately under ``ambient``, at shutdown under ``exit_hook``. This
            is the single well-defined point at which deferred arming can flush.
        on_stop: Zero-arg callable invoked after the loop ends (teardown).
        drive: Optional zero-arg callable that runs the whole app to completion,
            used instead of ``pump``/``alive`` under :data:`EXIT_HOOK`. Required
            for apps whose timers are asyncio-backed on a host with no ambient
            loop: a synchronous pump loop never runs the event loop, so
            ``AsyncTimer`` would silently never fire. ``drive`` owns the asyncio
            entry point and must flush ``on_start`` itself, from inside the
            running loop (``AsyncTimer.init`` needs one). Ignored under
            :data:`AMBIENT`, where the host's loop already runs.

    Returns:
        str: :data:`AMBIENT`, :data:`EXIT_HOOK`, or :data:`NONE`.

    The strategy is decided once per process and never re-decided. A later call
    rebinds the callbacks to the new owner without registering a second exit
    hook, so sequential apps in one process each get driven in turn.
    """
    rebind = _state["strategy"] is not None

    _state["pump"] = pump
    _state["alive"] = alive
    _state["on_start"] = on_start
    _state["on_stop"] = on_stop
    _state["drive"] = drive

    if rebind:
        # A second App superseding the first (sequential apps in one process, or
        # a test suite). Keep the strategy and the single registered hook; hand
        # them the new owner's callbacks and let it start.
        _state["started"] = False
        _state["stopped"] = False
        _state["claimed"] = False
        if _state["strategy"] == AMBIENT:
            _start()
        return _state["strategy"]

    if ambient() or interactive():
        # The host's own loop (page, kernel, REPL) is already running or about
        # to be. Arm now; register teardown only.
        _state["strategy"] = AMBIENT
        _start()
        on_exit(_stop)
        return AMBIENT

    if batch():
        # ``-m`` / ``-c``: not an app entry point. Register teardown only.
        on_exit(_stop)
        _state["strategy"] = NONE
        return NONE

    _install_crash_guard()
    if on_exit(_exit_hook):
        _state["strategy"] = EXIT_HOOK
        return EXIT_HOOK

    _state["strategy"] = NONE
    return NONE


def strategy():
    """The strategy chosen by :func:`install`, or None before it is called."""
    return _state["strategy"]


def _reset_for_test():
    for k in _state:
        _state[k] = (
            None
            if k in ("strategy", "pump", "alive", "on_start", "on_stop", "drive")
            else False
        )
