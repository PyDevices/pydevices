# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The HID gate, the host: connect to ``hid_peripheral.py`` and check every event.

Runs on a board (mpble) or on a laptop (``bledev.bleak``)::

    PYTHONPATH="$(wslpath -w lib);$(wslpath -w tests/bledev_board)" \\
        python.exe "$(wslpath -w tests/bledev_board/hid_central.py)"

It never pairs unless the device demands it, and on a laptop it refuses to:
Windows would then keep the board as a keyboard. The events must equal
``hid_script.expected()`` one for one, and the text they spell must equal
``hid_script.TEXT``. Then it answers every ``a`` with an LED write, which the
device times (the round trip), and records how long each report took from
arriving to reaching the app. Ends with ``RESULT PASS`` or ``RESULT FAIL``
(in /hid_central.log on a board). ``CONN`` passes connection intervals.
"""
import asyncio, gc, sys, time

import events
import keys
import bledev
import bledev.hid as hid
import hid_script

MICROPYTHON = sys.implementation.name == "micropython"
CONN = {}
if MICROPYTHON:
    import bledev.mpble

    LOG = "/hid_central.log"
else:
    import bledev.bleak

    LOG = None
    if "--fast" in sys.argv:
        CONN = {"priority": "throughput"}
NAME = "bledev-hid-gate"
LATENCY_N = 200
ENCRYPTED = False  # the harness sets it when the device pairs


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    if LOG:
        with open(LOG, "a") as f:
            f.write(line + "\n")


def stats(values):
    v = sorted(values)
    n = len(v)
    if not n:
        return "none"
    return "n={} min={} median={} p90={} p99={} max={} (us)".format(
        n, v[0], v[n // 2], v[min(n - 1, n * 9 // 10)], v[min(n - 1, n * 99 // 100)], v[-1])


async def main():
    if LOG:
        try:
            import os
            os.remove(LOG)
        except OSError:
            pass
    gc.collect()
    if MICROPYTHON:
        ble = bledev.mpble.get()
        if ENCRYPTED:
            ble.enable_bonding()
    else:
        ble = bledev.bleak.BleakBLE()
    t0 = time.ticks_ms() if MICROPYTHON else time.monotonic() * 1000
    device = await ble.find(name=NAME, timeout_ms=30000)
    connection = await device.connect(timeout_ms=15000, **CONN)
    host = hid.Host(connection)
    if not MICROPYTHON:
        # Never let Windows pair with a board that is a keyboard.
        async def refuse(bond=True, timeout_ms=20000):
            raise bledev.BLEError("refusing to pair a HID device with this PC")

        connection.pair = refuse
    await host.start()
    now = time.ticks_ms() if MICROPYTHON else time.monotonic() * 1000
    rmap = host.report_map
    log("connected and started in", int(now - t0), "ms; mtu", connection.mtu, "paired", host.paired,
        "map", len(rmap.descriptor), "bytes, applications", ["0x%08x" % a for a in rmap.applications],
        "inputs", [(r.report_id, r.size) for r in rmap.inputs()], "conn", CONN)

    want = hid_script.expected()
    got = []
    while len(got) < len(want):
        try:
            got += await host.events(5000)
        except bledev.BLETimeoutError:
            break
    await asyncio.sleep(0.3)
    extra = host.poll()
    problem = hid_script.compare(got + extra, want)
    text = hid_script.typed_text(got)
    log("events", len(got) + len(extra), "want", len(want))
    log("typed", repr(text))
    ok = problem is None and text == hid_script.TEXT
    if problem:
        log("MISMATCH", problem)
    if text != hid_script.TEXT:
        log("TEXT MISMATCH, want", repr(hid_script.TEXT))
    await host.set_leds(1)  # done comparing: start the latency phase

    decode = []
    answered = 0
    while answered < LATENCY_N:
        try:
            evs = await host.events(5000)
        except bledev.BLETimeoutError:
            log("latency phase stalled after", answered)
            ok = False
            break
        arrived = host.last_report_us
        for e in evs:
            if e.type == events.KEYDOWN and e.key == keys.K_a:
                decode.append(hid.ticks_diff(hid.ticks_us(), arrived))
                await host.set_leds(answered & 1)
                answered += 1
    log("report arrival to the app, on this host:", stats(decode))
    log("RESULT", "PASS" if ok else "FAIL")
    await host.close()


asyncio.run(main())
