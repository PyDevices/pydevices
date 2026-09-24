# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The HID gate, the device: a board that is a keyboard, media remote and gamepad.

Needs ``hid_script.py`` beside it (or in /lib). It advertises as
``bledev-hid-gate``, waits for a host to set its LEDs (the host's signal that
it has subscribed), then:

1. performs ``hid_script.STEPS``: typed text with Shift, two chords, two
   media keys, and gamepad axes, buttons and hat;
2. taps ``a`` ``LATENCY_N`` times, timing each press until the host writes the
   LEDs back (the host does that for every ``a`` it sees): the round trip.

``PLANT = True`` drops Shift from the first character typed; the host's
comparison must then fail. ``ENCRYPTED = True`` makes the host pair first.
Logs to /hid_peripheral.log and ends with ``DONE``.
"""
import asyncio, gc, sys, time
import bledev.mpble
import bledev.hid as hid
import hid_script

PLANT = False
ENCRYPTED = False
LATENCY_N = 200
NAME = "bledev-hid-gate"
LOG = "/hid_peripheral.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def stats(values):
    v = sorted(values)
    n = len(v)
    if not n:
        return "none"
    return "n={} min={} median={} p90={} p99={} max={} (us)".format(
        n, v[0], v[n // 2], v[min(n - 1, n * 9 // 10)], v[min(n - 1, n * 99 // 100)], v[-1])


async def one_host(per):
    conn = await per.serve()
    log("connected", conn, "mtu", conn.mtu)
    t, data = await per.leds(30000)
    log("host is listening (LEDs", data, "), encrypted", conn.encrypted)
    await asyncio.sleep_ms(200)
    steps = hid_script.STEPS
    if PLANT:
        text = steps[0][1]
        steps = (("type", text[0].lower()), ("type", text[1:])) + steps[1:]
    t0 = time.ticks_ms()
    await hid_script.perform(per, steps)
    log("script sent in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    # Let the host finish comparing, then time key presses.
    await per.leds(30000)
    rtt = []
    for i in range(LATENCY_N):
        await per.keyboard.send(0, (0x04,))
        start = per.last_send_us
        t, _ = await per.leds(5000)
        rtt.append(time.ticks_diff(t, start))
        await per.keyboard.send(0, ())
        await asyncio.sleep_ms(20)
    log("round trip, press to the host's LED write:", stats(rtt))
    await conn.disconnected(60000)
    log("host gone")


async def main():
    try:
        import os
        os.remove(LOG)
    except OSError:
        pass
    gc.collect()
    ble = bledev.mpble.get()
    if ENCRYPTED:
        ble.enable_bonding()
    per = hid.Peripheral(ble, name=NAME, encrypted=ENCRYPTED)
    log("advertising as", per.name, "appearance", hex(per.appearance), "plant", PLANT,
        "encrypted", ENCRYPTED, "map", len(per.report_map), "bytes")
    try:
        await one_host(per)
    finally:
        per.close()
        log("DONE")


asyncio.run(main())
