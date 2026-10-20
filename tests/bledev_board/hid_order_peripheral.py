# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The report-order gate, the device: numbered reports from three HID functions.

Pair it with ``hid_order_central.py`` on a second board. It advertises as
``bledev-hid-order``, waits for the host to subscribe (the host's LED write),
then sends ``RUNS`` runs of ``N`` reports. Report ``i`` goes to function
``i % 3``: a mouse move of one unit to the right, a keyboard press, or a media
key. The host knows that pattern, so it can tell from each event which report
it was, and checks that they come out in the order they went in. A run's gap
is the pause after each report: 0 is a burst, as fast as the radio takes
them. Logs to /hid_order_peripheral.log and ends with ``DONE``.
"""
import asyncio, gc, struct
import bledev
import bledev.mpble as backend  # the port line: bledev.cpble on CircuitPython
import bledev.hid as hid

N = 300
RUNS = (0, 0, 0, 5, 5, 5, 30, 30, 30)  # the gap after each report, in ms, per run
NAME = "bledev-hid-order"
LOG = "/hid_order_peripheral.log"
MEDIA = (0xE9, 0xEA, 0xB5, 0xB6)


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


async def main():
    try:
        import os
        os.remove(LOG)
    except OSError:
        pass
    gc.collect()
    ble = backend.get()
    per = hid.Peripheral(ble, name=NAME)
    kbd, mouse, media = per.devices
    log("advertising as", NAME)
    try:
        conn = await per.serve()
        log("connected, mtu", conn.mtu)
        await per.leds(30000)  # the host has subscribed
        await bledev.sleep_ms(500)
        i = 0
        for run, gap in enumerate(RUNS):
            t0 = hid.ticks_us()
            for _ in range(N):
                f = i % 3
                j = i // 3
                if f == 0:
                    mouse.send_report(bytes((0, 1, 0, 0)))
                elif f == 1:
                    kbd.send_report(bytes((0, 0, 4 + j % 26, 0, 0, 0, 0, 0)))
                else:
                    media.send_report(struct.pack("<H", MEDIA[j % 4]))
                i += 1
                if gap:
                    await bledev.sleep_ms(gap)
            log("run", run, "gap", gap, "ms sent", N, "in", hid.ticks_diff(hid.ticks_us(), t0) // 1000, "ms")
            await bledev.sleep_ms(1500)
        await conn.disconnected(30000)
        log("host gone")
    finally:
        per.close()
        log("DONE")


asyncio.run(main())
