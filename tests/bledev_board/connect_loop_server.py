# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Connect reliability, the peripheral: advertise, take a connection, wait for
it to end, and advertise again, forever. Pair with ``connect_loop_client.py``.

Prints ``accepted N`` for each connection.
"""
import asyncio

import bledev
import bledev.mpble

NAME = "bledev-conn-loop"


async def main():
    ble = bledev.mpble.get()
    n = 0
    while True:
        conn = await ble.advertise(name=NAME)
        n += 1
        print("accepted", n)
        try:
            await conn.disconnected(30000)
        except bledev.BLEError as e:
            print("still connected after 30 s:", e)
            await conn.disconnect()


asyncio.run(main())
