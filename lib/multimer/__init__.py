# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""multimer: one Timer, one clock, one dispatcher, on every PyDevices host.

::

    import multimer
    from multimer import Timer

    tim = Timer(-1)
    tim.init(mode=Timer.PERIODIC, period=10, callback=on_tick)
    sub = multimer.every(33, draw)
    multimer.report()        # what is running, from the REPL

Callbacks run on the main thread at a safe point: between two bytecodes
where the host can interrupt (a board, a signal, a pending call), otherwise
at the next idle point (``sleep_ms``, ``pump``, the REPL waiting for a key, an
await). They never run on another thread and never inside a C call. Importing
this package does nothing to the host; the wake source is chosen when the
first timer is armed. See ``docs/multimer.md``.
"""

import sys

from ._asyncio_loader import load_asyncio, loop_running
from ._dispatch import (
    Timer,
    alive,
    hold,
    info,
    keepalive,
    pump,
    run_until,
    schedule,
    sleep_ms,
    stop_all,
    timers,
)
from ._dispatch import source as _source
from ._ticks import (
    monotonic,
    run_deadline_hook,
    set_deadline_hook,
    ticks_add,
    ticks_diff,
    ticks_less,
    ticks_ms,
    ticks_us,
)

__version__ = "0.2.0"


def every(ms, callback, *, name=None):
    """A PERIODIC :class:`Timer` firing ``callback(timer)`` every *ms*."""
    return Timer(-1, mode=Timer.PERIODIC, period=ms, callback=callback, name=name)


def after(ms, callback, *, name=None):
    """A ONE_SHOT :class:`Timer` firing ``callback(timer)`` once, after *ms*."""
    return Timer(-1, mode=Timer.ONE_SHOT, period=ms, callback=callback, name=name)


async def asleep_ms(ms):
    """Coroutine sleep for async code; delivers due timers on hosts without a wake source."""
    aio = load_asyncio()
    if aio is None:
        raise ImportError("asleep_ms needs asyncio")
    sleep = getattr(aio, "sleep_ms", None)
    if sleep is not None:
        await sleep(ms)
    else:
        await aio.sleep(ms / 1000)
    pump()
    run_deadline_hook()


def strategy():
    """How the program stays alive past the script body: ambient, exit_hook, none, or None."""
    from . import _hostloop

    return _hostloop.strategy()


def repl(namespace=None, prompt=">>> ", tick_ms=10):
    """A line REPL that keeps delivering timers while it reads (hosts with no prompt)."""
    from ._repl import repl as _repl

    return _repl(namespace, prompt, tick_ms)


def report(file=None):
    """Print the dispatcher's state and every live timer, for a person at a prompt."""
    out = file if file is not None else sys.stdout
    d = info()
    out.write(
        "multimer on %s: source=%s delivery=%s wakes_blocking=%s strategy=%s\n"
        % (d["host"], d["source"], d["delivery"], d["wakes_blocking"], strategy())
    )
    out.write(
        "  deliveries=%d wakes=%d max_gap=%d ms errors=%d sched_full=%d held=%d keepalive=%s next=%s ms\n"
        % (
            d["deliveries"],
            d["wakes"],
            d["max_gap_ms"],
            d["errors"],
            d["sched_full"],
            d["held"],
            d["keepalive"],
            d["next_ms"],
        )
    )
    if "source_error" in d:
        out.write("  source fell back to none: %s\n" % d["source_error"])
    ts = timers()
    if not ts:
        out.write("  no timers armed\n")
    for t in ts:
        out.write("  %r due_in=%s ms\n" % (t, t.due_in))


__all__ = [
    "Timer",
    "after",
    "alive",
    "asleep_ms",
    "every",
    "hold",
    "info",
    "keepalive",
    "loop_running",
    "monotonic",
    "pump",
    "repl",
    "report",
    "run_deadline_hook",
    "run_until",
    "schedule",
    "set_deadline_hook",
    "sleep_ms",
    "stop_all",
    "strategy",
    "ticks_add",
    "ticks_diff",
    "ticks_less",
    "ticks_ms",
    "ticks_us",
    "timers",
]


_SUBMODULES = ("_dispatch", "_hostloop", "_inputhook", "_repl", "_ticks", "_asyncio_loader")


def __getattr__(name):
    if name == "asyncio":
        return load_asyncio()
    if name == "source":
        s = _source()
        return None if s is None else s.name
    # MicroPython resolves ``from . import _hostloop`` through the package's
    # __getattr__ and does not fall back to importing the submodule itself.
    if name in _SUBMODULES:
        module = __import__(__name__ + "." + name, None, None, (name,))
        globals()[name] = module
        return module
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
