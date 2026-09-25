# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The pairing gate, board to board with a passkey: one board shows it, the other types it.

Runs on Windows Python with pyserial (``uart_rig.py``). The serving board has
a display and ``/pair_server.py``; the typing board has
``/files_pair_client.py``. Both have bledev in ``/lib``::

    python.exe passkey_gate.py --server COM17 --client COM4 right wrong --log gate.log

The passkey travels the way a person would carry it. The serving board draws
it on its screen and prints it on its console (``bledev: Bluetooth passkey
123 456``); this script reads that line off the serving board's UART. The
typing board asks with ``PASSKEY?`` on its own console, and this script types
the digits into that board's UART, where ``input()`` reads them. Nothing else
passes between the two.

Steps, each starting from hard resets and no bonds on either board:

``right``  type what the screen shows. The link must be encrypted,
           authenticated and bonded on both boards, 20 KB must cross both ways
           byte for byte (the serving board's copy hashed too), and a second
           connection must encrypt from the bond without asking again. After
           hard resets both boards must still hold one bond.
``wrong``  type the passkey one off. Pairing must be refused, and after hard
           resets neither board may hold a bond.

``--plant justworks`` starts the server with pair_server's ``justworks``
plant (it says passkey but pairs without one); ``wrong`` must then FAIL.
Ends with ``GATE PASS`` or ``GATE FAIL``.
"""
import re
import sys
import time

from uart_rig import Board, wait

BONDS = "from bledev import security; security.use_store(); print('BONDS', security.bonds())"


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def bonds(board):
    out = board.say(BONDS)
    m = re.search(r"BONDS (\d+)", out)
    return int(m.group(1)) if m else None


def fresh(server, client):
    for b in (server, client):
        b.hard_reset()
        b.say("from bledev import security; security.use_store(); security.forget()")
    server.say("import os; [os.remove(f) for f in os.listdir('/') if f == 'pair_20k.bin']")


def step(server, client, kind, plant, say):
    failures = []

    def check(ok, what):
        say(("PASS " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)

    fresh(server, client)
    check(bonds(server) == 0 and bonds(client) == 0, "both boards start with no bond")
    for b in (server, client):
        b.hard_reset()
    started = server.say("import pair_server; pair_server.start('passkey'{})".format(
        ", plant='justworks'" if plant else ""), 20)
    say("server:", started)
    client.mark()
    server.mark()
    client.line("import files_pair_client as c; c.run(passkey='console')")
    t0 = time.monotonic()
    shown = asked = None
    finished = lambda: b"RESULT" in client.buf and client.buf.rstrip().endswith(b">>>")

    def ready():
        nonlocal shown, asked
        m = re.search(rb"Bluetooth passkey (\d{3}) (\d{3})", server.buf)
        if m and shown is None:
            shown = int(m.group(1) + m.group(2))
            say("the server's console showed {:06d} after {:.2f} s".format(shown, time.monotonic() - t0))
        if b"PASSKEY?" in client.buf and asked is None:
            asked = time.monotonic() - t0
            say("the client asked for it after {:.2f} s".format(asked))
        return (shown is not None and asked is not None) or finished()

    wait([server, client], ready, 60)
    if shown is not None and asked is not None:
        typed = shown if kind == "right" else (shown + 1) % 1000000
        say("typing {:06d} into the client's console ({})".format(typed, "as shown" if typed == shown else "one off"))
        client.write(b"%06d\r" % typed)
    else:
        say("no passkey exchange: shown", shown, "asked", asked)
    wait([server, client], finished, 120)
    out = client.text()
    for line in out.split("\n"):
        if line.startswith(("PASS", "FAIL", "RESULT", "connected", "write", "reconnected", "sha256", "passkey asked",
                            "bonds after", "store")):
            say("client:", line.strip())
    status = server.say("pair_server.status()")
    say("server:", status)
    result = re.search(r"RESULT (.*)", out)
    result = result.group(1).strip() if result else None
    if kind == "right":
        check(result == "PASS", "the client's checks pass (paired, authenticated, 20 KB, reconnect from the bond)")
        check(shown is not None and asked is not None, "the passkey was shown and asked for")
        sha = re.search(r"sha256 ([0-9a-f]{64})", out)
        theirs = server.say("import hashlib, binascii; print(binascii.hexlify(hashlib.sha256("
                            "open('/pair_20k.bin','rb').read()).digest()).decode())")
        check(bool(sha) and sha.group(1) in theirs, "the serving board's copy has the same SHA-256")
        m = re.search(r"links \{(.*?)\}", status)
        say("server links:", m.group(1) if m else None)
    else:
        check(result is not None and result.startswith("FAIL") and "connect and pair" in result,
              "pairing is refused")
    for b in (server, client):
        b.hard_reset()
    n_server, n_client = bonds(server), bonds(client)
    say("after hard resets: server bonds", n_server, "client bonds", n_client)
    want = 1 if kind == "right" else 0
    check(n_server == want and n_client == want, "each board holds {} bond(s) after resets".format(want))
    return failures


def main():
    log = open(arg("--log", "passkey_gate.log"), "a", encoding="utf-8")
    server = Board(arg("--server", "COM17"), "SERVER", log)
    client = Board(arg("--client", "COM4"), "CLIENT", log)
    plant = arg("--plant")
    steps = [a for a in sys.argv[1:] if a in ("right", "wrong")]

    def say(*parts):
        line = " ".join(str(p) for p in parts)
        print(line, flush=True)
        log.write("#### " + line + "\n")
        log.flush()

    failed = []
    for kind in steps:
        say("==== step", kind, "plant", plant, time.strftime("%H:%M:%S"))
        failed += ["{}: {}".format(kind, f) for f in step(server, client, kind, plant, say)]
    for b in (server, client):
        b.say("from bledev import security; security.use_store(); security.forget()")
        b.hard_reset()
    say("GATE", "FAIL " + "; ".join(failed) if failed else "PASS")


main()
