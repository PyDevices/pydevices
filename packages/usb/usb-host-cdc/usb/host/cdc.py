# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# MicroPython USB CDC host: a USB serial device on the host port.
# MIT license; Copyright (c) 2026 Brad Barnett
#
#     import usb.core
#     from usb.host.cdc import Serial
#
#     port = Serial(usb.core.find(custom_match=Serial.match))
#     port.write(b"print(1 + 1)\r\n")      # another MicroPython board's REPL
#     print(port.read(64))
#
# CDC-ACM, the class a USB serial adapter or a microcontroller's own USB
# console uses (not the network functions, ECM and NCM, which share its class).
# Serial finds the data interface's bulk pair, raises DTR and
# RTS (a MicroPython board's console stays silent until DTR says a terminal
# is attached), and reads and writes the way machine.UART does. Line coding
# (baud rate and framing) is sent when given, for a real adapter; a
# microcontroller's console ignores it.
import struct
import time

import usb.core

from usb.host import _chips as cdc_chips

_SET_LINE_CODING = 0x20
_SET_CONTROL_LINE_STATE = 0x22


def _strip_status(buf, n, packet, skip):
    """Drop the ``skip`` status bytes each ``packet``-sized piece of an IN transfer
    starts with (FTDI's), keeping the data in place; returns the data's length."""
    kept = 0
    for start in range(0, n, packet):
        data = buf[start + skip:min(start + packet, n)]
        buf[kept:kept + len(data)] = data
        kept += len(data)
    return kept


def _find(dev):
    """(control interface, data interface, bulk IN, bulk OUT, IN packet), or None.

    Only a CDC-ACM communication interface counts (class 2, subclass 2): a
    network function (ECM, NCM) has the same class and a data interface of its
    own, and isn't a serial port. Each ACM interface is paired with the data
    interface its Union descriptor names, else the next one after it, so a
    composite device with a network function ahead of its serial function
    gives the serial function's interfaces.
    """
    cfg = dev.configuration_descriptor()
    i, cur, comm = cfg[0], None, None
    comms = []      # [communication interface, union's data interface or None, datas met before it]
    datas = []      # [data interface, bulk IN, bulk OUT, IN packet], in the order met
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        kind = cfg[i + 1]
        if kind == 4:
            cur = cfg[i + 2]
            comm = None
            if cfg[i + 5] == 0x02 and cfg[i + 6] == 0x02:
                comm = [cur, None, len(datas)]
                comms.append(comm)
            elif cfg[i + 5] == 0x0A and not [d for d in datas if d[0] == cur]:
                datas.append([cur, None, None, 64])
        elif kind == 0x24 and comm is not None and cfg[i] >= 5 and cfg[i + 2] == 0x06:
            comm[1] = cfg[i + 4]    # Union: the control interface, then its first subordinate
        elif kind == 5 and cfg[i + 3] & 3 == 2:
            for d in datas:
                if d[0] == cur:
                    if cfg[i + 2] & 0x80:
                        d[1], d[3] = cfg[i + 2], cfg[i + 4] | cfg[i + 5] << 8
                    else:
                        d[2] = cfg[i + 2]
        i += cfg[i]
    for comm, union, before in comms:
        for d in (datas if union is not None else datas[before:]):
            if d[1] is not None and d[2] is not None and (union is None or d[0] == union):
                return comm, d[0], d[1], d[2], d[3]
    return None


class Serial:
    @staticmethod
    def match(dev):
        """For usb.core.find(custom_match=...): a CDC-ACM device, or a vendor
        USB-serial adapter (CH34x, CP210x, FTDI, PL2303)."""
        return _find(dev) is not None or cdc_chips.find(dev) is not None

    def __init__(self, dev, *, baudrate=None, timeout=0, dtr=True):
        """``timeout`` in ms: how long a read waits for the first byte (0: a
        poll that returns at once). ``baudrate`` is sent as the line coding;
        a vendor adapter always gets one (115200 if none is given), because
        it has no other default."""
        found = _find(dev) if dev is not None else None
        self._chip = None
        if found is not None:
            self._comm, self._data, self._in, self._out, mps = found
        else:
            self._chip = cdc_chips.find(dev) if dev is not None else None
            if self._chip is None:
                raise ValueError("not a CDC-ACM device or a known USB-serial adapter")
            chip = self._chip
            self._comm = self._data = chip.interface
            self._in, self._out, mps = chip.ep_in, chip.ep_out, chip.mps
        self.dev = dev
        self.timeout = timeout
        self._buf = bytearray(mps)
        self._pending = memoryview(self._buf)[:0]
        if self._chip is not None:
            self._chip.open()
            self.init(baudrate or 115200)
        elif baudrate:
            self.init(baudrate)
        self.dtr(dtr)

    @property
    def chip(self):
        """The adapter's chip, such as "CH34x" or "FT232R"; "CDC-ACM" for a
        device that speaks the standard class."""
        return self._chip.name if self._chip is not None else "CDC-ACM"

    def init(self, baudrate=115200, bits=8, parity=None, stop=1):
        stop_code = {1: 0, 1.5: 1, 2: 2}[stop]
        parity_code = {None: 0, 1: 1, 0: 2}.get(parity, 0)
        if self._chip is not None:
            self._chip.line(baudrate, bits, parity_code, stop_code)
            return
        self.dev.ctrl_transfer(0x21, _SET_LINE_CODING, 0, self._comm,
                               struct.pack("<IBBB", baudrate, stop_code, parity_code, bits), 1000)

    def dtr(self, on=True, rts=True):
        if self._chip is not None:
            self._chip.modem(on, rts)
            return
        self.dev.ctrl_transfer(0x21, _SET_CONTROL_LINE_STATE, (1 if on else 0) | (2 if rts else 0),
                               self._comm, None, 1000)

    def _fill(self, timeout):
        if self._pending:
            return True
        end = time.ticks_add(time.ticks_ms(), max(1, timeout))
        while True:
            left = time.ticks_diff(end, time.ticks_ms())
            try:
                n = self.dev.read(self._in, self._buf, max(1, left))
            except usb.core.USBTimeoutError:
                return False
            skip = self._chip.strip if self._chip is not None else 0
            if skip:
                n = _strip_status(self._buf, n, len(self._buf), skip)
            if n > 0:
                self._pending = memoryview(self._buf)[:n]
                return True
            # A status-only packet, or an empty one: keep waiting out the timeout.
            if left <= 1:
                return False

    def any(self):
        """Bytes ready to read without waiting (what's arrived, at least)."""
        self._fill(1)
        return len(self._pending)

    def readinto(self, buf, nbytes=None):
        want = len(buf) if nbytes is None else min(nbytes, len(buf))
        got = 0
        timeout = self.timeout
        while got < want and self._fill(timeout):
            take = min(want - got, len(self._pending))
            buf[got:got + take] = self._pending[:take]
            self._pending = self._pending[take:]
            got += take
            timeout = 1     # after the first bytes, take only what's already here
        return got or None

    def read(self, nbytes=None):
        buf = bytearray(nbytes or 256)
        n = self.readinto(buf)
        return bytes(buf[:n]) if n else None

    def write(self, buf):
        return self.dev.write(self._out, buf, 1000)

    def close(self):
        self.dev._release_all()

    deinit = close
