# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A line REPL that keeps delivering timers while it reads.

For hosts with no prompt to fall through to: CircuitPython, whose supervisor
resets the board when ``code.py`` returns, and any program that must hold the
main thread itself. ``multimer.repl()`` reads lines from stdin between
deliveries and evaluates them in the caller's namespace, so ``report()`` and
the program's own objects are reachable over the same serial port without
stopping it. Ctrl-D (or ``quit()``) returns.
"""

import sys

from . import _dispatch


def _reader():
    """A zero-arg callable returning available stdin text, or ''."""
    try:
        import supervisor

        rt = supervisor.runtime

        def read():
            n = rt.serial_bytes_available
            return sys.stdin.read(n) if n else ""

        # Only boards have the attribute; the unix build raises here.
        rt.serial_bytes_available
        return read
    except Exception:
        pass
    try:
        import select
    except ImportError:
        return None
    # poll() exists on CPython, MicroPython and CircuitPython; select() only
    # on the first two.
    poll = getattr(select, "poll", None)
    if poll is not None:
        try:
            poller = poll()
            poller.register(sys.stdin, select.POLLIN)

            def read():
                if not poller.poll(0):
                    return ""
                data = sys.stdin.readline()
                return data if data else "\x04"

            return read
        except Exception:
            pass
    sel = getattr(select, "select", None)
    if sel is not None:
        try:
            fd = sys.stdin.fileno()

            def read():
                r, _, _ = sel([fd], [], [], 0)
                if not r:
                    return ""
                data = sys.stdin.readline()
                return data if data else "\x04"

            return read
        except Exception:
            pass
    return None


def repl(namespace=None, prompt=">>> ", tick_ms=10):
    """Read-eval-print until EOF, delivering timers between lines.

    Returns when stdin closes or the user enters ``quit()``. Statements
    ending with ``:`` are read in blocks up to a blank line.
    """
    if namespace is None:
        # CircuitPython keeps __main__ out of sys.modules; importing it works.
        main = sys.modules.get("__main__")
        if main is None:
            try:
                main = __import__("__main__")
            except ImportError:
                main = None
        namespace = main.__dict__ if main is not None else {}
    read = _reader()
    if read is None:
        raise RuntimeError("multimer.repl: no way to read stdin without blocking on this host")
    sys.stdout.write("multimer.repl: timers keep running; Ctrl-D or quit() returns\n")
    sys.stdout.write(prompt)
    buf = ""
    block = []
    while True:
        _dispatch.sleep_ms(tick_ms)
        data = read()
        if not data:
            continue
        if "\x04" in data:
            sys.stdout.write("\n")
            return
        buf += data
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.rstrip("\r")
            if block:
                if line.strip():
                    block.append(line)
                    sys.stdout.write("... ")
                    continue
                src = "\n".join(block)
                block = []
            elif line.rstrip().endswith(":"):
                block.append(line)
                sys.stdout.write("... ")
                continue
            else:
                src = line
            if src.strip() in ("quit()", "exit()"):
                return
            _run(src, namespace)
            sys.stdout.write(prompt)


def _run(src, namespace):
    try:
        try:
            code = compile(src, "<repl>", "eval")
        except SyntaxError:
            code = compile(src, "<repl>", "exec")
            exec(code, namespace)
        else:
            value = eval(code, namespace)
            if value is not None:
                sys.stdout.write(repr(value) + "\n")
    except Exception as exc:
        _dispatch._print_exception(exc)
