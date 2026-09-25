# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The REPL gate, client side: log in over BLE, run code, interrupt a loop.

Needs ``repl_server.py`` started on a board. Runs on a laptop (bleak) or a
board (mpble); see gatt_central.py for the command line. Checks, in order:

1. The right password gets a prompt, and ``123 * 456`` evaluates to 56088.
2. A wrong password, sent together with a line of code that would create
   ``/pwned``, gets ``Access denied`` and a disconnect, and never a prompt.
3. Logged in again, ``/pwned`` does not exist: the code never ran.
4. ``while True`` runs until Ctrl-C, which interrupts it, and the REPL still
   answers afterwards.

Ends with ``RESULT PASS`` or ``RESULT FAIL``.
"""
import asyncio
import sys

import bledev
import bledev.nus as nus
import bledev.repl as repl

MICROPYTHON = sys.implementation.name == "micropython"
PASSWORD = "bledev-gate-pw"
NAME = "bledev-repl"

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


async def drain(link, ms):
    """Everything that arrives within ``ms``."""
    got = bytearray()
    try:
        while True:
            chunk = await bledev.wait_ms(link.read(), ms, "drain")
            if not chunk:
                break
            got.extend(chunk)
    except bledev.BLETimeoutError:
        pass
    return bytes(got)


async def main():
    ble = adapter()

    link = await repl.connect(ble, PASSWORD, name=NAME, timeout_ms=15000)
    out = await repl.run(link, "123 * 456")
    check(out.strip() == "56088", "the right password gets a working prompt", repr(out))
    await repl.run(link, "import os")
    await repl.run(link, "exec(\"try:\\n os.remove('/pwned')\\nexcept OSError:\\n pass\")")
    out = await repl.run(link, "'pwned' in os.listdir('/')")
    check(out.strip() == "False", "no /pwned before the attack", repr(out))
    await link.close()
    await bledev.sleep_ms(1500)

    link = await nus.connect(ble, name=NAME, timeout_ms=15000)
    await link.write(b"\r")
    got = await drain(link, 1500)
    check(repl.PROMPT in got, "the board asks for a password", repr(got))
    await link.write(b"not-the-password\rimport os; open('/pwned', 'w').write('1')\r")
    got = await drain(link, 3000)
    check(b"Access denied" in got, "a wrong password is refused", repr(got))
    check(b">>>" not in got, "a wrong password never gets a prompt", repr(got))
    try:
        await link.connection.disconnected(timeout_ms=3000)
        check(True, "the board hangs up after a wrong password")
    except bledev.BLETimeoutError:
        check(False, "the board hangs up after a wrong password")
        await link.close()
    await bledev.sleep_ms(1500)

    try:
        wrong = await repl.connect(ble, "wrong-again", name=NAME, timeout_ms=15000)
        check(False, "repl.connect() raises AuthError for a wrong password")
        await wrong.close()
    except repl.AuthError:
        check(True, "repl.connect() raises AuthError for a wrong password")
    await bledev.sleep_ms(1500)

    link = await repl.connect(ble, PASSWORD, name=NAME, timeout_ms=15000)
    out = await repl.run(link, "'pwned' in os.listdir('/')")
    check(out.strip() == "False", "the code sent with the wrong password never ran", repr(out))

    await repl.run(link, "n = 0")
    await link.write(b"while True: n += 1\r\r")
    got = await drain(link, 1500)
    check(b">>> " not in got, "the loop is running", repr(got))
    await link.write(b"\x03")
    got = await drain(link, 2000)
    check(b"KeyboardInterrupt" in got and got.rstrip().endswith(b">>>"), "Ctrl-C interrupts it", repr(got[-80:]))
    out = await repl.run(link, "n > 1000")
    check(out.strip() == "True", "the loop ran, and the REPL answers after the interrupt", repr(out))
    await link.close()


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
