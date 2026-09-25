# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Drive boards' friendly REPLs over their UARTs, several at once, from Windows Python.

The board-to-board gates that need what mpftp can't give use this: a run
started at the friendly prompt keeps ESP-IDF's log on the console (the raw
REPL mutes it, so the P4's ``alloc_acl_from_ll failed`` only shows here), a
hard reset between runs (the P4 can't turn BLE on twice after a soft reset,
micropython-pydevices#13), and one board's console read while another board
is typed at, which is how ``passkey_gate.py`` carries a passkey from one
screen to another board's keyboard.

Ports open with pyserial's defaults (DTR and RTS asserted), as mpremote opens
them: on the LCD-7's CH343, opening with both released resets the board.
Everything each board prints goes to the log, prefixed with its name.
"""
import time

import serial


class Board:
    def __init__(self, port, name, log=None):
        self.s = serial.Serial(port, 115200, timeout=0)
        self.name = name
        self.log = log
        self.buf = b""  # since the last mark()
        self._partial = b""

    def pump(self):
        data = self.s.read(8192)
        if data:
            self.buf += data
            if self.log is not None:
                self._partial += data
                *lines, self._partial = self._partial.split(b"\n")
                for line in lines:
                    self.log.write("{:9.3f} {} | {}\n".format(
                        time.monotonic(), self.name, line.decode("utf-8", "replace").rstrip("\r")))
                self.log.flush()
        return data

    def mark(self):
        self.pump()
        self.buf = b""

    def text(self):
        return self.buf.decode("utf-8", "replace").replace("\r", "")

    def write(self, data):
        self.s.write(data)

    def line(self, text):
        self.s.write(text.encode() + b"\r")

    def prompt(self, timeout=5):
        """Stop whatever runs and get to the friendly prompt."""
        self.mark()
        self.write(b"\x03\x03")
        time.sleep(0.1)
        self.write(b"\r")
        return wait([self], lambda: self.buf.rstrip().endswith(b">>>"), timeout)

    def soft_reset(self, timeout=20):
        self.prompt()
        self.mark()
        self.write(b"\x04")
        return wait([self], lambda: b"soft reboot" in self.buf and self.buf.rstrip().endswith(b">>>"), timeout)

    def hard_reset(self, timeout=40):
        """machine.reset() from the prompt, then wait for the next prompt."""
        self.prompt()
        self.mark()
        self.line("import machine; machine.reset()")
        return wait([self], lambda: b"MicroPython v" in self.buf and self.buf.rstrip().endswith(b">>>"), timeout)

    def say(self, text, timeout=10):
        """Type one line at the prompt and return what it printed."""
        self.mark()
        self.line(text)
        wait([self], lambda: b"\n" in self.buf and self.buf.split(b"\n", 1)[1].rstrip().endswith(b">>>"), timeout)
        body = self.text().split("\n", 1)[1] if "\n" in self.text() else ""
        return body.rstrip().removesuffix(">>>").rstrip()

    def close(self):
        self.s.close()


def wait(boards, done, timeout):
    """Pump every board until ``done()`` or the timeout. True if done."""
    end = time.monotonic() + timeout
    while True:
        got = False
        for b in boards:
            if b.pump():
                got = True
        if done():
            return True
        if time.monotonic() > end:
            return False
        if not got:
            time.sleep(0.01)
