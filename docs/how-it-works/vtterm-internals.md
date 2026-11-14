# vtterm internals

This page is for you if you're changing vtterm or wondering why it's built
the way it is; using it is in the [vtterm guide](../guides/vtterm.md).
vtterm is three small parts and two ways to join them to a Python prompt. It
is pure Python, so the same package runs on every interpreter, and it draws
with pygraphics, so it needs nothing from a display but `blit_rect`.

```text
bytes from the REPL, a program, or another device
            |
            v
        Parser ----- answers (cursor position, device type) back to the sender
            |
            v
        Screen: characters, colors, styles, cursor; dirty rows marked
            |
            v
       Renderer: each dirty row composed in one strip, one blit_rect
            |
            v
         the display
```

## The parser

`Parser.feed` is a byte-at-a-time state machine: ground, escape, CSI
parameters, strings and the character-set and `#` prefixes. It keeps its state
between calls, so a sequence split across two reads from a link finishes on
the second. Printable ASCII goes to the screen in runs, not a byte at a time,
which is most of what a REPL prints.

24-bit colors are kept as the nearest of the 256 ANSI colors, so every cell's
color fits in one byte. The palette needed for that is imported only when the
first 24-bit color arrives.

## The screen

Each row is four bytearrays the width of the screen: characters, foreground,
background and style flags. A scroll moves rows in a list rather than copying
bytes. A row that changes is marked dirty, and a whole-screen scroll is
counted, so the renderer knows what to draw.

The cursor follows the VT100 when a character lands in the last column: it
stays there with a wrap pending, and the next character starts the new row.
This matches xterm and a real VT100, and it's what the line editors in REPLs
expect.

## The renderer

The renderer keeps one strip buffer, a row high and the display wide, in
RGB565. For each dirty row it fills each run of cells that share colors, draws
their text with a pygraphics font, adds underline and the cursor, and sends
the strip with one `blit_rect`. A display that scrolls in hardware (an SPI
panel's scroll registers, or the desktop window) moves the picture on a
whole-screen scroll, and only the new rows are drawn.

The memory it needs is the screen, four bytes per cell, plus the strip, the
display's width times the font's height times two bytes.

## The two ways in

`Console` is a stream for `os.dupterm`. The REPL writes to it, and it reads
the bytes you push, or the bytes a key source returns, when the REPL looks
for input. While output streams it redraws at most every `interval_ms`, and
everything left is drawn when the REPL next waits.

`session.run` is an asyncio loop for a link to another device: bytes from the
link go to the parser, and key bytes and the parser's answers go back down
the link.

## Ctrl-C from a timer

A keyboard read from a timer pushes Ctrl-C from inside the timer's callback.
Raised there, the interrupt would land in the callback, and a busy program
wouldn't see it until it next waited. `Console.push` schedules the notify
with `micropython.schedule` instead, so the interrupt is raised in the
running program once the callback returns, as it is for Ctrl-C over USB.

## A soft reset with the console attached

On ESP32 firmware, a soft reset frees every object and then writes "soft
reboot" to the dupterm streams, before it clears them. With a Python stream
such as `Console` attached, that write runs on freed memory: the board prints
an error from some unrelated object, or panics and restarts. OmniPython MP
firmware clears the dupterm slots first, so a soft reset there is clean. On other ESP32 firmware, `detach()` the
console before Ctrl-D.
