# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The BLE-MIDI codec, checked against the shared vectors.

A plain script, not unittest, so the same file runs on CPython and on
MicroPython::

    python tests/bledev_midi_codec.py
    micropython tests/bledev_midi_codec.py
    python tests/bledev_midi_codec.py --plant=rollover   # must FAIL

The vectors are ``tests/bledev_midi_vectors.json``, worked out by hand from
the packet format. Then a seeded round trip: thousands of random messages
(notes, controllers, pitch bend, SysEx, real-time, system common) through the
encoder at random packet sizes and back through the decoder.

``--plant=NAME`` loads the codec with one fault written into its source (see
``PLANTS``), so the checks are shown to catch it. ``tests/test_bledev_midi.py``
runs every plant.
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
_LIB = _dir + _sep + ".." + _sep + "lib" + _sep + "bledev" + _sep + "midi_codec.py"
_VECTORS = _dir + _sep + "bledev_midi_vectors.json"

import json
from binascii import hexlify, unhexlify

MICROPYTHON = sys.implementation.name == "micropython"

#: Faults a check must catch: (text in midi_codec.py, what replaces it).
PLANTS = {
    # The decoder misses a rollover of the timestamp's low seven bits.
    "rollover": ("high = (high + 1) & 0x3F", "high = high"),
    # The decoder forgets running status at each packet.
    "running": ("        high = packet[0] & 0x3F\n", "        high = packet[0] & 0x3F\n        self._running = 0\n"),
    # The encoder skips one byte of every SysEx fragment after the first.
    "sysex": ("            index += take\n", "            index += take + (1 if index > 1 else 0)\n"),
    # The encoder writes a header without the timestamp's high bits.
    "header": ("self.buf[0] = 0x80 | high", "self.buf[0] = 0x80"),
    # The decoder lets a real-time message end a SysEx.
    "realtime": (
        "                if b >= 0xF8:\n                    out.append((ts, bytes((b,))))\n",
        "                if b >= 0xF8:\n                    self._sysex = None\n                    out.append((ts, bytes((b,))))\n",
    ),
}


def load_codec(plant=None):
    with open(_LIB) as f:
        source = f.read()
    if plant:
        old, new = PLANTS[plant]
        if old not in source:
            raise SystemExit("plant {!r} no longer matches midi_codec.py".format(plant))
        source = source.replace(old, new)
        print("PLANTED", plant)
    namespace = {"__name__": "midi_codec"}
    exec(source, namespace)

    class Codec:
        pass

    codec = Codec()
    for name in ("Decoder", "Encoder", "Splitter", "encode", "decode", "data_length", "TIMESTAMP_MASK"):
        setattr(codec, name, namespace[name])
    return codec


def h(text):
    return unhexlify(text.replace(" ", ""))


def show(data):
    return hexlify(data).decode()


passed = 0
failed = []


def check(ok, what, detail=""):
    global passed
    if ok:
        passed += 1
    else:
        failed.append(what)
        print("FAIL", what, detail)


def run_vectors(codec, vectors):
    for case in vectors["decode"]:
        d = codec.Decoder()
        got = []
        for p in case["packets"]:
            got.extend(d.decode(h(p)))
        want = [(ts, h(m)) for ts, m in case["messages"]]
        check(got == want, "decode: " + case["name"], "got {}".format([(ts, show(m)) for ts, m in got]))
        check(d.errors == case["errors"], "decode errors: " + case["name"], "got {} errors".format(d.errors))
    for case in vectors["encode"]:
        messages = [(ts, h(m)) for ts, m in case["messages"]]
        got = codec.encode(messages, case["size"], case["running_status"])
        want = [h(p) for p in case["packets"]]
        check(got == want, "encode: " + case["name"], "got {}".format([show(p) for p in got]))
        back = codec.decode(got)
        check(
            [m for _, m in back if m[0] < 0xF8] == [m for _, m in messages if m[0] < 0xF8],
            "encode then decode: " + case["name"],
        )


def run_splitter(codec):
    s = codec.Splitter()
    out = []
    for chunk in (b"\x90\x3c", b"\x64\x3e\x64", b"\xf0\x01\xf8\x02", b"\x03\xf7\xb0\x07", b"\xfa\x40\xc0\x05\x06"):
        out.extend(s.feed(chunk))
    want = [b"\x90\x3c\x64", b"\x90\x3e\x64", b"\xf8", b"\xf0\x01\x02\x03\xf7", b"\xfa", b"\xb0\x07\x40", b"\xc0\x05", b"\xc0\x06"]
    check(out == want, "splitter: running status, split writes, real-time inside SysEx and a message", repr(out))
    check(s.desync == 0, "splitter: no desync on a clean stream")
    s.feed(b"\x3c\x64")
    s2 = codec.Splitter()
    s2.feed(b"\x3c\x64")
    check(s2.desync == 2, "splitter: data with no status is counted, not guessed")


class Rand:
    """A small LCG, so both interpreters make the same stream."""

    def __init__(self, seed):
        self.state = seed

    def next(self, n):
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return (self.state >> 8) % n


def random_messages(r, count):
    """``count`` messages with timestamps that move forward and wrap."""
    ts = r.next(8192)
    out = []
    for _ in range(count):
        ts = (ts + (0 if r.next(3) == 0 else r.next(300))) & 0x1FFF
        kind = r.next(20)
        ch = r.next(16)
        if kind < 7:
            m = bytes((0x90 | ch, r.next(128), r.next(128)))
        elif kind < 9:
            m = bytes((0x80 | ch, r.next(128), r.next(128)))
        elif kind < 11:
            m = bytes((0xB0 | ch, r.next(128), r.next(128)))
        elif kind < 12:
            m = bytes((0xE0 | ch, r.next(128), r.next(128)))
        elif kind < 13:
            m = bytes((0xC0 | ch, r.next(128)))
        elif kind < 14:
            m = bytes((0xD0 | ch, r.next(128)))
        elif kind < 16:
            m = bytes((0xF8 + r.next(8),))
        elif kind < 17:
            m = (bytes((0xF1, r.next(128))), bytes((0xF2, r.next(128), r.next(128))), bytes((0xF6,)))[r.next(3)]
        else:
            m = bytes([0xF0] + [r.next(128) for _ in range(r.next(400))] + [0xF7])
        out.append((ts, m))
    return out


def run_round_trip(codec, streams, per_stream):
    r = Rand(20260924)
    total = 0
    bad = 0
    first = None
    for n in range(streams):
        messages = random_messages(r, per_stream)
        size = 5 + r.next(240)
        running = r.next(2) == 0
        packets = codec.encode(messages, size, running)
        for p in packets:
            if len(p) > size and first is None:
                first = "packet of {} bytes at size {}".format(len(p), size)
        got = codec.decode(packets)
        # Real-time may slip ahead into a SysEx; everything else keeps its
        # order, and every message keeps its bytes. Timestamps survive,
        # except a SysEx's, which is its F7's.
        want_rt = [(ts, m) for ts, m in messages if m[0] >= 0xF8]
        got_rt = [(ts, m) for ts, m in got if m[0] >= 0xF8]
        want_other = [(ts if m[0] != 0xF0 else None, m) for ts, m in messages if m[0] < 0xF8]
        got_other = [(ts if m[0] != 0xF0 else None, m) for ts, m in got if m[0] < 0xF8]
        total += len(messages)
        if got_rt != want_rt or got_other != want_other:
            bad += 1
            if first is None:
                first = "stream {} at size {}: {} messages in, {} out".format(n, size, len(messages), len(got))
    check(bad == 0 and first is None, "round trip: {} messages in {} streams".format(total, streams), first or "")
    return total


def main():
    plant = None
    for arg in sys.argv[1:]:
        if arg.startswith("--plant="):
            plant = arg.split("=", 1)[1]
    codec = load_codec(plant)
    with open(_VECTORS) as f:
        vectors = json.load(f)
    run_vectors(codec, vectors)
    run_splitter(codec)
    total = run_round_trip(codec, 150 if MICROPYTHON else 400, 60)
    print(
        "bledev.midi codec ({}): {} passed, {} failed; {} decode and {} encode vectors, {} round-trip messages".format(
            sys.implementation.name, passed, len(failed), len(vectors["decode"]), len(vectors["encode"]), total
        )
    )
    if failed:
        sys.exit(1)


main()
