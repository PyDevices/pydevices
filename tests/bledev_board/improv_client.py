# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Improv gate, client side, on a laptop (bleak) or a board (mpble).

Needs ``improv_server.py`` on a board.

``--wrong`` (or ``WRONG = True`` on a board) sends a network that doesn't
exist, and passes only if the board answers "unable to connect" and goes back
to "authorized".

Without it, the network comes from this board's own ``secrets.py``
(``WIFI_SSID``/``WIFI_PASSWORD``, as ``wifi.connect_from_secrets()`` reads
it), imported here and never printed, and it passes when the board reports
"provisioned" with a redirect URL. That mode is for a board: on a laptop there
is no ``secrets`` module to read.
"""
import asyncio
import sys

import bledev
import bledev.improv as improv

MICROPYTHON = sys.implementation.name == "micropython"
WRONG = "--wrong" in sys.argv
NAME = "bledev-improv"
failures = []


def check(ok, what, detail=""):
    print("PASS" if ok else "FAIL", what, detail)
    if not ok:
        failures.append(what)


def adapter():
    if MICROPYTHON:
        import bledev.mpble

        return bledev.mpble.get()
    import bledev.bleak

    return bledev.bleak.BleakBLE()


async def main():
    client = await improv.Client.connect(adapter(), NAME, timeout_ms=20000)
    try:
        info = await client.device_info()
        check(len(info) >= 4 and info[3] == NAME, "device info", info)
        state = await client.state()
        check(state == improv.STATE_AUTHORIZED, "the board starts authorized", state)
        if WRONG:
            try:
                await client.send_wifi("bledev-no-such-network", "not-a-real-password", timeout_ms=60000)
                check(False, "a network that doesn't exist is refused")
            except improv.ImprovError as e:
                check(e.code == improv.ERROR_UNABLE_TO_CONNECT, "the board reports unable to connect", e)
            error = await client.error()
            check(error == improv.ERROR_UNABLE_TO_CONNECT, "the error characteristic says so", error)
            state = await client.state()
            check(state == improv.STATE_AUTHORIZED, "and the board is back to authorized", state)
        else:
            import secrets

            ssid = getattr(secrets, "WIFI_SSID", None) or getattr(secrets, "ssid", None)
            password = getattr(secrets, "WIFI_PASSWORD", None) or getattr(secrets, "password", None) or ""
            url = await client.send_wifi(ssid, password, timeout_ms=60000)
            del ssid, password
            check(url.startswith("http://"), "the board joined and sent a redirect", url)
            state = await client.state()
            check(state == improv.STATE_PROVISIONED, "the board reports provisioned", state)
    finally:
        await client.close()


async def guarded():
    try:
        await main()
    except Exception as e:
        failures.append("exception")
        print("EXCEPTION", type(e).__name__, e)
    print("RESULT", "FAIL {}".format(failures) if failures else "PASS")


asyncio.run(guarded())
if not MICROPYTHON:
    sys.exit(1 if failures else 0)
