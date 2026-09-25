# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The BLE-MIDI gate and latency rig, board side: serve BLE-MIDI as ``bledev-midi``.

Run it from ``/main.py`` on one MicroPython board (mpftp soft-resets a board
before it runs a script, and a soft reset turns Bluetooth off, so ``mpftp run``
would lose it); on CircuitPython, ``mpftp run`` works. ``midi_client.py`` on another board or a laptop then connects and
asks for one of two sessions with a SysEx command, ``F0 7D 10 <mode> F7``:

* mode 1, the gate: this side reads 1,000 mixed messages (``mix()``) and
  checks them, sends back its verdict as ``F0 7D 11 <0 pass, 1 fail>
  <count, 2 bytes> <first bad index, 2 bytes> F7``, then sends the same 1,000
  messages down for the client to check.
* mode 2, echo: every message that arrives goes straight back, until the
  link closes. The client times the round trips.

It serves one connection after another until reset. ``PLANT`` breaks what
this side sends on the air: ``"drop"`` leaves out the 20th packet of the
gate's downstream, ``"flip"`` flips a bit in it. The client must then FAIL.
Logs to /midi_server.log.
"""
import asyncio
import sys

import bledev.midi as midi

if sys.implementation.name == "circuitpython":
    import bledev.cpble as backend  # mpftp run keeps Bluetooth on here
else:
    import bledev.mpble as backend

PLANT = None  # None, "drop" or "flip"
LOG = "/midi_server.log"
NAME = "bledev-midi"
COUNT = 1000


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def mix(count):
    """Notes, controllers, pitch bend, program changes, clock, and a
    300-byte SysEx every hundred messages, interleaved. Both ends build it."""
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
    """``(ok, first bad index)``. Real-time may slip into a SysEx on the air,
    so real-time and everything else are each compared in order."""
    if len(got) != len(want):
        bad = len(got)
    else:
        bad = -1
    for kind in (True, False):
        g = [m for m in got if (m[0] >= 0xF8) == kind]
        w = [m for m in want if (m[0] >= 0xF8) == kind]
        for i in range(max(len(g), len(w))):
            if i >= len(g) or i >= len(w) or g[i] != w[i]:
                bad = i if bad < 0 else min(bad, i)
                break
    return bad < 0, bad


def plant(port):
    if not PLANT:
        return
    send = port._send_packet
    count = [0]

    async def planted(packet):
        count[0] += 1
        if count[0] == 20:
            if PLANT == "drop":
                return
            packet = bytearray(packet)
            packet[-1] ^= 0x01
        await send(packet)

    port._send_packet = planted


async def gate(port):
    want = mix(COUNT)
    got = []
    while len(got) < COUNT:
        ts, message = await port.receive(timeout_ms=30000)
        got.append(message)
    ok, bad = verify(got, want)
    log("gate up:", "PASS" if ok else "FAIL", len(got), "messages, first bad", bad, "decode errors", port.decode_errors)
    b = max(bad, 0)
    port.send(bytes((0xF0, 0x7D, 0x11, 0 if ok else 1, len(got) >> 7, len(got) & 0x7F, b >> 7, b & 0x7F, 0xF7)))
    await port.drain()
    plant(port)
    for message in want:
        port.send(message)
    await port.drain()
    log("gate down: sent", COUNT, "plant", PLANT)


async def echo(port):
    n = 0
    try:
        while True:
            ts, message = await port.receive()
            port.send(message)
            n += 1
    except midi.DisconnectedError:
        pass
    log("echoed", n)


async def main():
    try:
        import os

        os.remove(LOG)
    except OSError:
        pass
    ble = backend.get()
    log("serving BLE-MIDI as", NAME, "plant", PLANT)
    while True:
        port = await midi.serve(ble, name=NAME)
        log("connected, mtu", port.connection.mtu)
        try:
            ts, command = await port.receive(timeout_ms=20000)
            if command[:3] == b"\xf0\x7d\x10" and command[3] == 1:
                await gate(port)
            elif command[:3] == b"\xf0\x7d\x10" and command[3] == 2:
                await echo(port)
            else:
                log("unknown command", command)
        except Exception as e:
            log("session ended:", type(e).__name__, e)
        try:
            await port.connection.disconnected(timeout_ms=30000)
        except Exception:
            await port.aclose()


if sys.implementation.name in ("micropython", "circuitpython"):
    asyncio.run(main())
