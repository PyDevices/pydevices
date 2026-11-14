# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Join a `Terminal <vtterm.Terminal>` to another device's console.

`run` is an asyncio loop: bytes from the link are drawn, and key presses and
the terminal's reports go back down the link. A link is anything with async
``read(n)`` and ``write(data)``: a ``bledev.nus.Link`` from
``bledev.repl.connect``, or an asyncio stream from a TCP socket or a UART.

Example:
    >>> import asyncio, bledev.repl
    >>> from vtterm.session import run
    >>> link = await bledev.repl.connect(ble, "password", name="mpy-repl")
    >>> await run(term, link, keys)
"""

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio


async def run(terminal, link, keys=None, poll_ms=20, stop=None):
    """Show the link's output and send it keys until it closes or ``stop`` is set.

    Args:
        terminal (Terminal): Where the output is drawn.
        link: The other device, with async ``read(n)`` and ``write(data)``.
        keys: A key source with ``read()`` returning bytes or ``None``.
        poll_ms (int): How often keys are read and the display is redrawn.
        stop (asyncio.Event): Set it to end the session. Optional.

    Returns:
        int: Bytes received from the link.
    """
    received = 0
    closed = False

    async def reader():
        nonlocal received, closed
        while True:
            data = await link.read(512)
            if not data:
                closed = True
                return
            received += len(data)
            terminal.feed(data)

    task = asyncio.create_task(reader())
    try:
        while not closed and (stop is None or not stop.is_set()):
            out = keys.read() if keys is not None else None
            answers = terminal.answers()
            if answers:
                out = answers if out is None else out + answers
            if out:
                await link.write(out)
            terminal.render()
            await asyncio.sleep(poll_ms / 1000)
    finally:
        task.cancel()
        terminal.render()
    return received
