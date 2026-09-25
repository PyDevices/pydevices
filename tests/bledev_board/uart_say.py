# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Type one line at a board's idle REPL over its UART and print the answer.

    python.exe uart_say.py COM17 "import pair_server; pair_server.status()"

Unlike ``mpftp exec``, which enters the raw REPL with a soft reset, this
types at the friendly prompt, so a BLE server running from interrupts keeps
running and its state can be read. Opens the port as mpremote does (pyserial's
defaults): on the LCD-7's CH343, opening with DTR and RTS released resets
the board.
"""
import sys
import time

import serial

port, line = sys.argv[1], sys.argv[2]
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 10
s = serial.Serial(port, 115200, timeout=0.05)
s.reset_input_buffer()
s.write(b"\r")
time.sleep(0.2)
s.reset_input_buffer()
s.write(line.encode() + b"\r")
out = b""
end = time.monotonic() + timeout
while time.monotonic() < end:
    out += s.read(512)
    body = out.split(b"\n", 1)[1] if b"\n" in out else b""
    if body.rstrip().endswith(b">>>"):
        break
s.close()
text = out.decode("utf-8", "replace").replace("\r", "")
print("\n".join(text.split("\n")[1:]).rstrip().removesuffix(">>>").rstrip())
