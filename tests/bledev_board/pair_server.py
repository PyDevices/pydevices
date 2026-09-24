# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The pairing gate, board side: serve the REPL and files with pairing, and return.

Copy it to the board as ``/pair_server.py`` and start it from ``mpftp exec``::

    import pair_server; pair_server.start("passkey")

The board keeps serving from interrupts at its REPL. ``pair_client.py``
checks it from a laptop, ``files_pair_client.py`` from another board. The
passkey goes on the display (``board_config.display_drv``) and the console,
where the laptop's client reads it: the console is the one screen a script
can read. ``status()`` prints the bond store and every link's security.

Plants, each of which a client check must catch:

* ``start(..., plant="forget")``: forget every bond, as a chip erase would,
  so a bonded host can't reconnect without pairing.
* ``start(..., plant="justworks")``: say passkey but pair "just works"
  (no MITM, encryption-only characteristics), so a host with the wrong
  passkey gets in.
* ``start(..., plant="open")``: serve without protecting the
  characteristics, so an unpaired host can use them.
"""
import time

import bledev.filetransfer as ft
import bledev.repl as repl
from bledev import security

NAME = "bledev-pair"
PASSWORD = "bledev-gate-pw"

#: The last passkey the display was asked to show, and how many it showed.
last = None
shown = 0


#: With ``start(debug=True)``: every BLE IRQ but writes, as (ms, event, data).
L = []


def _log(event, data):
    if event != 3:
        if isinstance(data, tuple):
            data = tuple(bytes(x) if isinstance(x, memoryview) else x for x in data)
        L.append((time.ticks_ms(), event, data))


def start(mode="passkey", password=False, plant=None, name=NAME, debug=False):
    global last, shown
    if debug:
        from aioble import core

        core._irq_handlers.insert(0, _log)
    last = None
    shown = 0
    display = security.find_display()
    show0, hide0 = security.display_passkey(display)

    def show(passkey):
        global last, shown
        last = passkey
        shown += 1
        show0(passkey)

    if plant == "forget":
        security.use_store()
        security.forget()
    if plant == "open":
        repl._F_READ_ENC = repl._F_READ_AUTHN = repl._F_WRITE_ENC = repl._F_WRITE_AUTHN = 0
        repl._Server.secure = lambda self, conn: True
    configured = mode
    if plant == "justworks":
        # Declared a passkey, paired without one: no MITM, encryption-only
        # characteristics, and no password, the way a misconfigured board would.
        real = security.configure

        def configure(_mode, **options):
            real("justworks", **options)
            return "passkey"

        security.configure = configure
        repl._F_READ_AUTHN = repl._F_WRITE_AUTHN = 0
        repl._Server.secure = lambda self, conn: security.state(conn)[0]
    if password == "gate":
        password = PASSWORD
    t0 = time.ticks_ms()
    server = ft.start(password, name, pairing=configured, show=show, hide=hide0)
    print(
        "pair_server: serving", name, "pairing", server.pairing, "password", password is not False,
        "display", display is not None, "store", security.store().kind, "bonds", security.bonds(),
        "plant", plant, "in", time.ticks_diff(time.ticks_ms(), t0), "ms",
    )


def status():
    s = repl._server
    print(
        "pair_server: store", security.store().kind if security.store() else None, "bonds", security.bonds(),
        "shown", shown, "links", security._links, "conn", s.conn if s else None,
        "authed", s.authed if s else None,
    )
