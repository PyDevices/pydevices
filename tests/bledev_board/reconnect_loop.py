# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Rapid reconnects from a laptop against the REPL gate's board.

Needs ``repl_server.py`` serving (from ``/main.py``). Each cycle logs in
through ``bledev.repl.connect()``, runs one line, closes, and waits ``GAP``
seconds before the next, which is how the REPL gate once failed: bleak
couldn't subscribe on a connection made 1.5 s after the last one closed.
Prints each cycle, how many connection attempts it took, and a total::

    PYTHONPATH="$(wslpath -w lib)" python.exe "$(wslpath -w tests/bledev_board/reconnect_loop.py)" 100 1.5

``--no-retry`` sets ``attempts=1``, the old behaviour, to show the failure.
"""
import asyncio
import sys
import time

import bledev
import bledev.bleak
import bledev.nus as nus
import bledev.repl as repl

args = [a for a in sys.argv[1:] if not a.startswith("--")]
N = int(args[0]) if args else 20
GAP = float(args[1]) if len(args) > 1 else 1.5
RETRY = "--no-retry" not in sys.argv

attempts = []
_helper = nus.connect_and_set_up


async def counting(ble, setup, **kwargs):
    async def counted(connection):
        attempts[-1] += 1
        return await setup(connection)

    if not RETRY:
        kwargs["attempts"] = 1
    return await _helper(ble, counted, **kwargs)


nus.connect_and_set_up = counting


async def main():
    ble = bledev.bleak.BleakBLE()
    fails = 0
    retried = 0
    for i in range(N):
        attempts.append(0)
        t0 = time.monotonic()
        try:
            link = await repl.connect(ble, "bledev-gate-pw", name="bledev-repl", timeout_ms=15000)
            out = await repl.run(link, "%d * 3" % i)
            ok = out.strip() == str(i * 3)
            await link.close()
            status = "OK" if ok else "BAD OUTPUT"
            fails += 0 if ok else 1
        except Exception as e:
            fails += 1
            status = "FAIL {} {}".format(type(e).__name__, e)
        if attempts[-1] > 1:
            retried += 1
        print("cycle", i, status, "attempts", attempts[-1], "%.1fs" % (time.monotonic() - t0), flush=True)
        await asyncio.sleep(GAP)
    print("RESULT {}/{} failed, {} needed a second attempt".format(fails, N, retried))
    return fails


sys.exit(1 if asyncio.run(main()) else 0)
