# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The BLE-MIDI gate and latency rig, client side.

Needs ``midi_server.py`` serving on a board. Runs on a board (mpftp probe)
or on a laptop (bleak, Windows Python)::

    PYTHONPATH="$(wslpath -w lib)" python.exe "$(wslpath -w tests/bledev_board/midi_client.py)" [gate] [latency] [--fast] [--plant]

``gate``: 1,000 mixed messages (notes, CC, pitch bend, program change, clock
and a 300-byte SysEx every hundred) go up and are checked by the server, then
come back down and are checked here. ``--plant`` flips a bit in one packet
of what this side sends; the server's verdict must then be FAIL.

``latency``: note-on round trips through the server's echo, one note at a
time at a random phase (0-20 ms apart), then chords of four. Half the round
trip is what BLE adds one way. ``--fast`` asks for a 7.5 ms connection
interval (on a laptop, Windows' throughput parameters) instead of the
default. Prints median, p90, p99 and max, and ends ``RESULT PASS`` or
``RESULT FAIL``.
"""
import asyncio
import sys

import bledev
import bledev.midi as midi

MICROPYTHON = sys.implementation.name == "micropython"
NAME = "bledev-midi"
PINGS = 400
CHORDS = 100

if MICROPYTHON:
    import time

    def now_us():
        return time.ticks_us()

    def elapsed_us(t0):
        return time.ticks_diff(time.ticks_us(), t0)

    ARGS = []
    try:
        import midi_client_args

        ARGS = midi_client_args.ARGS
    except ImportError:
        pass
else:
    import time

    def now_us():
        return time.perf_counter_ns() // 1000

    def elapsed_us(t0):
        return now_us() - t0

    ARGS = sys.argv[1:]

LOG = "/midi_client.log" if MICROPYTHON else None
failures = []


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    if LOG:
        with open(LOG, "a") as f:
            f.write(line + "\n")


def check(ok, what, detail=""):
    log("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


def adapter():
    if MICROPYTHON:
        import bledev.mpble

        return bledev.mpble.get()
    import bledev.bleak

    return bledev.bleak.BleakBLE()


def options(fast):
    if not fast:
        return {}
    if MICROPYTHON:
        return {"min_conn_interval_us": 7500, "max_conn_interval_us": 7500}
    return {"priority": "throughput"}


def mix(count):
    # The same as midi_server.mix(); kept in step by hand.
    out = []
    for i in range(count):
        k = i % 10
        if i % 100 == 9:
            out.append(bytes([0xF0] + [(i + j) % 128 for j in range(298)] + [0xF7]))
        elif k in (0, 1, 2):
            out.append(bytes((0x90 | (i % 16), i % 128, 1 + i % 127)))
        elif k == 3:
            out.append(bytes((0x80 | (i % 16), i % 128, 0)))
        elif k in (4, 5):
            out.append(bytes((0xB0 | (i % 16), 7, i % 128)))
        elif k == 6:
            out.append(bytes((0xE0 | (i % 16), i % 128, (i >> 7) % 128)))
        elif k in (7, 8):
            out.append(b"\xf8")
        else:
            out.append(bytes((0xC0 | (i % 16), i % 128)))
    return out


def verify(got, want):
    bad = len(got) if len(got) != len(want) else -1
    for kind in (True, False):
        g = [m for m in got if (m[0] >= 0xF8) == kind]
        w = [m for m in want if (m[0] >= 0xF8) == kind]
        for i in range(max(len(g), len(w))):
            if i >= len(g) or i >= len(w) or g[i] != w[i]:
                bad = i if bad < 0 else min(bad, i)
                break
    return bad < 0, bad


def plant(port):
    send = port._send_packet
    count = [0]

    async def planted(packet):
        count[0] += 1
        if count[0] == 20:
            packet = bytearray(packet)
            packet[-1] ^= 0x01
        await send(packet)

    port._send_packet = planted


async def gate(ble, fast, planted):
    port = await midi.connect(ble, name=NAME, timeout_ms=15000, **options(fast))
    log("gate: connected, mtu", port.connection.mtu)
    t0 = now_us()
    port.send(b"\xf0\x7d\x10\x01\xf7")
    await port.drain()
    if planted:
        plant(port)
    want = mix(1000)
    for message in want:
        port.send(message)
    await port.drain()
    ts, verdict = await port.receive(timeout_ms=30000)
    up_ms = elapsed_us(t0) / 1000
    ok = verdict[:4] == b"\xf0\x7d\x11\x00"
    count = (verdict[4] << 7) | verdict[5] if len(verdict) > 7 else -1
    first = (verdict[6] << 7) | verdict[7] if len(verdict) > 7 else -1
    check(ok, "gate up: the server got 1,000 messages complete, in order, intact", "server counted {}, first bad {}".format(count, first if not ok else "-"))
    got = []
    t0 = now_us()
    try:
        while len(got) < 1000:
            ts, message = await port.receive(timeout_ms=15000)
            got.append(message)
    except bledev.BLEError as e:
        log("gate down: stopped after", len(got), type(e).__name__, e)
    down_ms = elapsed_us(t0) / 1000
    ok, bad = verify(got, want)
    check(ok, "gate down: 1,000 messages complete, in order, intact", "got {}, first bad {}, decode errors {}".format(len(got), bad, port.decode_errors))
    log("gate: up took {:.0f} ms, down {:.0f} ms".format(up_ms, down_ms))
    await port.aclose()


def stats(samples_us):
    s = sorted(samples_us)
    n = len(s)

    def pct(p):
        return s[min(n - 1, int(p * n))] / 1000

    return "n={} median {:.1f} ms, p90 {:.1f}, p99 {:.1f}, max {:.1f}".format(n, pct(0.5), pct(0.9), pct(0.99), s[-1] / 1000)


class Rand:
    def __init__(self, seed):
        self.state = seed

    def next(self, n):
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return (self.state >> 8) % n


async def latency(ble, fast):
    port = await midi.connect(ble, name=NAME, timeout_ms=15000, **options(fast))
    label = "7.5 ms interval" if fast and MICROPYTHON else ("throughput parameters" if fast else "default parameters")
    log("latency ({}): connected, mtu {}".format(label, port.connection.mtu))
    port.send(b"\xf0\x7d\x10\x02\xf7")
    await port.drain()
    r = Rand(7)
    await bledev.sleep_ms(500)
    one_way = []
    lost = 0
    for i in range(PINGS):
        await bledev.sleep_ms(r.next(21))
        note = i % 128
        t0 = now_us()
        port.write(bytes((0x90, note, 100)))
        try:
            while True:
                ts, message = await port.receive(timeout_ms=2000)
                if message == bytes((0x90, note, 100)):
                    break
        except bledev.BLETimeoutError:
            lost += 1
            continue
        one_way.append(elapsed_us(t0) // 2)
    log("latency ({}), one note, half the round trip: {}".format(label, stats(one_way)))
    chord = []
    for i in range(CHORDS):
        await bledev.sleep_ms(r.next(21))
        base = 36 + (i % 60)
        notes = [bytes((0x91, base + k, 90)) for k in (0, 4, 7, 12)]
        t0 = now_us()
        port.write(b"".join(notes))
        seen = 0
        try:
            while seen < 4:
                ts, message = await port.receive(timeout_ms=2000)
                if message in notes:
                    seen += 1
        except bledev.BLETimeoutError:
            lost += 1
            continue
        chord.append(elapsed_us(t0) // 2)
    log("latency ({}), a four-note chord, half the round trip to the last note: {}".format(label, stats(chord)))
    check(lost == 0, "latency ({}): every echo came back".format(label), "lost {}".format(lost))
    check(port.decode_errors == 0, "latency ({}): no decode errors".format(label))
    await port.aclose()
    return one_way


async def main():
    if LOG:
        open(LOG, "w").close()
    ble = adapter()
    fast = "--fast" in ARGS
    planted = "--plant" in ARGS
    if "gate" in ARGS or not any(a in ARGS for a in ("gate", "latency")):
        await gate(ble, fast, planted)
        await bledev.sleep_ms(1500)
    if "latency" in ARGS or not any(a in ARGS for a in ("gate", "latency")):
        await latency(ble, fast)


async def guarded():
    try:
        await main()
    except Exception as e:
        failures.append("exception")
        log("EXCEPTION", type(e).__name__, e)
    log("RESULT", "FAIL {}".format(failures) if failures else "PASS")


asyncio.run(guarded())
if not MICROPYTHON:
    sys.exit(1 if failures else 0)
