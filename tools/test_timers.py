#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
Probe public multimer Timer APIs available on this Python port.

Public surfaces exercised (when importable on the host):

- ``machine.Timer`` — MCU hardware (not multimer; listed for comparison)
- ``multimer.auto.Timer`` — optional platform-selected provider
- ``multimer.AsyncTimer`` — asyncio / uasyncio (sleep and yield-loop styles)

Optional probes of every explicit provider are enabled with
``MULTIMER_PROBE_BACKENDS=1``.

Run the full desktop matrix from the sibling examples repository::

    cd ../gallery
    python tools/run_test_timers.py

Each probe is isolated so one failure does not stop the rest. Imports that
fail are reported as SKIP.
"""

import os
import sys
import time


def _bootstrap_src_path():
    """Allow the probe to run directly from the core checkout."""
    here = __file__.replace("\\", "/")
    tools_dir = here.rsplit("/", 1)[0] if "/" in here else "."
    repo_root = tools_dir.rsplit("/", 1)[0] if "/" in tools_dir else "."
    lib = repo_root + "/lib" if repo_root not in ("", ".") else "lib"
    if lib not in sys.path:
        sys.path.insert(0, lib)


_bootstrap_src_path()

from multimer import auto as timer  # noqa: E402
from multimer import ticks_add, ticks_less, ticks_ms  # noqa: E402

TEST_PERIOD_MS = 50
TEST_DURATION_MS = 300
MIN_CALLBACKS = 2


def _probe_providers_enabled():
    """Whether to probe every explicit provider available on this port."""
    environ = getattr(os, "environ", None)
    if environ is None:
        return False
    try:
        return environ.get("MULTIMER_PROBE_BACKENDS", "") == "1"
    except Exception:
        return False


def _timer_id():
    return -1 if sys.platform == "rp2" else 1


def _print_platform():
    impl = getattr(sys, "implementation", None)
    name = impl.name if impl else "unknown"
    version = impl.version if impl else "unknown"
    print("multimer timer probe")
    print(f"  implementation: {name} {version}")
    print(f"  platform: {sys.platform}")
    print(f"  python: {sys.version.split()[0]}")
    print()


def _print_error(label, err):
    print(f"  {label}: {type(err).__name__}: {err}")


def _wait_ms(ms, sleep_ms):
    deadline = ticks_add(ticks_ms(), ms)
    while ticks_less(ticks_ms(), deadline):
        sleep_ms(10)


def _run_timer_test(TimerClass, sleep_ms=timer.sleep_ms):
    """
    Start a periodic timer, wait, stop, verify fire.

    Returns:
        tuple[str, str | int]: (status, detail) where status is PASS, FAIL, or SKIP.
    """
    if TimerClass is None:
        return "SKIP", "Timer is None on this platform"

    counter = [0]
    received = [None]

    def callback(_timer):
        received[0] = _timer
        counter[0] += 1

    timer = TimerClass(_timer_id())
    timer.init(mode=TimerClass.PERIODIC, period=TEST_PERIOD_MS, callback=callback)
    _wait_ms(TEST_DURATION_MS, sleep_ms)
    timer.deinit()

    count = counter[0]
    if count >= MIN_CALLBACKS:
        if received[0] is not timer:
            return "FAIL", f"callback arg is not timer instance: {received[0]!r}"
        return "PASS", f"{count} callbacks in {TEST_DURATION_MS} ms"
    return "FAIL", f"expected >={MIN_CALLBACKS} callbacks, got {count}"


async def _run_async_timer_test(TimerClass):
    from multimer import asyncio

    counter = [0]

    def callback(_timer):
        counter[0] += 1

    timer = TimerClass(_timer_id())
    timer.init(mode=TimerClass.PERIODIC, period=TEST_PERIOD_MS, callback=callback)
    await asyncio.sleep(TEST_DURATION_MS / 1000)
    timer.deinit()
    return counter[0]


def _run_async_loop_test(TimerClass):
    """Exercise AsyncTimer while the main thread also does sync work."""
    from multimer import asyncio

    counter = [0]

    def callback(_timer):
        counter[0] += 1

    async def main():
        timer = TimerClass(_timer_id())
        timer.init(mode=TimerClass.PERIODIC, period=TEST_PERIOD_MS, callback=callback)
        elapsed = 0
        while elapsed < TEST_DURATION_MS:
            time.sleep(0.01)  # noqa: ASYNC251 — intentional sync work on the event-loop thread
            await asyncio.sleep(0)
            elapsed += 10
        timer.deinit()
        return counter[0]

    return asyncio.run(main())


def _run_async_timer_test_sync(TimerClass):
    from multimer import asyncio

    return asyncio.run(_run_async_timer_test(TimerClass))


def _probe(name, import_fn, *, async_test=False, async_loop_test=False):
    print(f"{name}:")
    try:
        imported = import_fn()
    except ImportError as err:
        print("  SKIP (import)")
        _print_error("reason", err)
        print()
        return
    except Exception as err:
        print("  SKIP (import)")
        _print_error("reason", err)
        print()
        return

    try:
        provider_sleep = getattr(imported, "sleep_ms", timer.sleep_ms)
        TimerClass = getattr(imported, "Timer", imported)
        if async_loop_test:
            count = _run_async_loop_test(TimerClass)
            if count >= MIN_CALLBACKS:
                status, detail = "PASS", f"{count} callbacks in {TEST_DURATION_MS} ms"
            else:
                status, detail = (
                    "FAIL",
                    f"expected >={MIN_CALLBACKS} callbacks, got {count}",
                )
        elif async_test:
            count = _run_async_timer_test_sync(TimerClass)
            if count >= MIN_CALLBACKS:
                status, detail = "PASS", f"{count} callbacks in {TEST_DURATION_MS} ms"
            else:
                status, detail = (
                    "FAIL",
                    f"expected >={MIN_CALLBACKS} callbacks, got {count}",
                )
        else:
            status, detail = _run_timer_test(TimerClass, provider_sleep)
    except Exception as err:
        print("  FAIL (runtime)")
        _print_error("reason", err)
        try:
            sys.print_exception(err)
        except AttributeError:
            pass
        print()
        return

    print(f"  {status}: {detail}")
    print()


def _import_machine_timer():
    from machine import Timer

    return Timer


def _import_async_timer():
    from multimer import AsyncTimer

    return AsyncTimer


def _import_multimer_timer():
    from multimer import auto as provider

    return provider


def _import_backend_timer(backend_name):
    return __import__(
        f"multimer.{backend_name}",
        None,
        None,
        ("Timer",),
    )


def main():
    _print_platform()

    probes = [
        ("machine.Timer", _import_machine_timer, False, False),
        ("AsyncTimer", _import_async_timer, True, False),
        ("AsyncTimer (yield loop)", _import_async_timer, False, True),
        ("multimer.auto.Timer", _import_multimer_timer, False, False),
    ]

    if _probe_providers_enabled():
        print("explicit provider probes enabled (MULTIMER_PROBE_BACKENDS=1)")
        print()
        for name in ("librt", "win32", "sdl2", "threading", "polling"):
            probes.append(
                (
                    f"multimer.{name}.Timer",
                    lambda n=name: _import_backend_timer(n),
                    False,
                    False,
                )
            )

    for name, import_fn, async_test, async_loop_test in probes:
        _probe(name, import_fn, async_test=async_test, async_loop_test=async_loop_test)


if __name__ == "__main__":
    main()
