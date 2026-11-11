# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# MicroPython USB DFU host: read the flash of a microcontroller that is sitting
# in its DFU bootloader, such as an Arduino GIGA after a double tap of reset or
# an STM32 held in its system bootloader.
# MIT license; Copyright (c) 2026 Brad Barnett
#
#     import hashlib
#     import usb.core
#     from usb.host.dfu import Dfu
#
#     dfu = Dfu(usb.core.find(custom_match=Dfu.match))
#     print(dfu.alternates())               # [(0, "Internal Flash"), (1, "External Flash"), ...]
#     digest = hashlib.sha256()
#     for chunk in dfu.chunks(0x08000000, 0x1000):
#         digest.update(chunk)
#
# DFU is the standard way a bootloader takes new firmware over USB. Each
# alternate setting of its interface is one memory (internal flash, option
# bytes, an external flash chip), and an upload request reads it a block at a
# time. For an STM32's DfuSe variant (bcdDFUVersion 0x011A) block 2 is the
# first address the alternate names and each block after it is `transfer_size`
# bytes further on; for plain DFU 1.1 block 0 is the start. A bootloader reads
# from its own address pointer, which only a set-address (a download) moves,
# and this package never sends one. An STM32's ROM bootloader starts the pointer
# at the memory's first address. An Arduino GIGA's bootloader starts it at the
# firmware (0x08040000), so there `chunks(0x08000000, ...)` returns firmware0's
# first bytes, not the bootloader's.
#
# This only reads. Nothing here sends a download request, erases, or tells the
# bootloader to leave, so a board that is read stays in its bootloader and
# unchanged until it's reset.
import usb.core

_DFU_UPLOAD = 2
_DFU_GETSTATUS = 3
_DFU_CLRSTATUS = 4
_DFU_ABORT = 6
_SET_INTERFACE = 0x0B

_STATE_IDLE = 2
_STATE_ERROR = 10

DFUSE = 0x011A


def _interfaces(dev):
    """[(interface, alternate, name string index)] of the DFU-mode interfaces
    (class 0xFE, subclass 1, protocol 2), and the DFU functional descriptor's
    (attributes, transfer size, version), or ([], None)."""
    cfg = dev.configuration_descriptor()
    i, found, functional, cur = cfg[0], [], None, False
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            cur = cfg[i + 5] == 0xFE and cfg[i + 6] == 1 and cfg[i + 7] == 2
            if cur:
                found.append((cfg[i + 2], cfg[i + 3], cfg[i + 8]))
        elif cfg[i + 1] == 0x21 and cur and cfg[i] >= 9:
            functional = (cfg[i + 2], cfg[i + 5] | cfg[i + 6] << 8, cfg[i + 7] | cfg[i + 8] << 8)
        i += cfg[i]
    return found, functional


class Dfu:
    @staticmethod
    def match(dev):
        """For usb.core.find(custom_match=...): a device in DFU mode."""
        return bool(_interfaces(dev)[0])

    def __init__(self, dev, alternate=0):
        if dev is None:
            raise ValueError("no device")
        found, functional = _interfaces(dev)
        if not found or functional is None:
            raise ValueError("not a device in DFU mode")
        self.dev = dev
        self.interface = found[0][0]
        self._names = {alt: index for itf, alt, index in found if itf == self.interface}
        self.attributes, self.transfer_size, self.version = functional
        if not self.attributes & 0x02:
            raise ValueError("this DFU device can't be read")
        self.dfuse = self.version == DFUSE
        self._buf = bytearray(self.transfer_size)
        self._label = {}
        self.alternate = None
        self.select(alternate)

    def _string(self, index):
        if not index:
            return ""
        buf = bytearray(128)
        n = self.dev.ctrl_transfer(0x80, 6, 0x0300 | index, 0x0409, buf, 1000)
        # No slice step: MicroPython's bytearray doesn't take one.
        return "".join(chr(buf[i] | buf[i + 1] << 8) for i in range(2, n - 1, 2))

    def alternates(self):
        """[(alternate setting, name)] for each memory the bootloader offers.
        A DfuSe name is cut at its first slash: "Internal Flash"."""
        out = []
        for alt in sorted(self._names):
            label = self._label.get(alt)
            if label is None:
                label = self._label[alt] = self._string(self._names[alt])
            out.append((alt, label[1:].split("/")[0].strip() if label[:1] == "@" else label))
        return out

    def layout(self, alternate=None):
        """The memory an alternate setting holds, as the bootloader describes it:
        (start address, [(sector count, sector size in bytes)]) for DfuSe, or
        (0, []) for a bootloader that gives no layout."""
        alt = self.alternate if alternate is None else alternate
        label = self._label.get(alt)
        if label is None:
            label = self._label[alt] = self._string(self._names[alt])
        parts = label.split("/")
        if label[:1] != "@" or len(parts) < 3:
            return 0, []
        start = int(parts[1], 16)
        sectors = []
        for group in parts[2].split(","):
            count, _, rest = group.partition("*")
            unit = 1
            digits = ""
            for ch in rest:
                if ch.isdigit():
                    digits += ch
                else:
                    unit = {"K": 1024, "M": 1 << 20}.get(ch, 1)
                    break
            if digits and count.strip().isdigit():
                sectors.append((int(count), int(digits) * unit))
        return start, sectors

    def select(self, alternate):
        """Choose which memory to read (an alternate setting from alternates())."""
        if alternate not in self._names:
            raise ValueError("no alternate setting %d" % alternate)
        self.dev.ctrl_transfer(0x01, _SET_INTERFACE, alternate, self.interface, None, 3000)
        self.alternate = alternate
        self._base = self.layout(alternate)[0] if self.dfuse else 0
        self._settle()

    # -- state

    def status(self):
        """(status code, state) from GETSTATUS; status 0 is OK, state 2 is idle."""
        data = self.dev.ctrl_transfer(0xA1, _DFU_GETSTATUS, 0, self.interface, 6, 1000)
        return data[0], data[4]

    def _settle(self):
        """Back to the idle state, clearing an error left by an earlier request."""
        _, state = self.status()
        if state == _STATE_ERROR:
            self.dev.ctrl_transfer(0x21, _DFU_CLRSTATUS, 0, self.interface, None, 1000)
        elif state != _STATE_IDLE:
            self.dev.ctrl_transfer(0x21, _DFU_ABORT, 0, self.interface, None, 1000)

    # -- reading

    def chunks(self, address, length):
        """Yield what's at ``address`` for ``length`` bytes, a block at a time,
        as a memoryview that is reused for the next block: use or copy it before
        asking for the next. For DfuSe the address is a flash address and must be
        a multiple of ``transfer_size`` from the start of the memory; for plain DFU it's an
        offset from the start of the image."""
        size = self.transfer_size
        if (address - self._base) % size:
            raise ValueError("start on a multiple of %d from %#x" % (size, self._base))
        block = (address - self._base) // size + (2 if self.dfuse else 0)
        view = memoryview(self._buf)
        left = length
        try:
            while left > 0:
                want = min(size, left)
                got = self.dev.ctrl_transfer(0xA1, _DFU_UPLOAD, block, self.interface, view[:want], 5000)
                if got <= 0:
                    return
                yield view[:got]
                left -= got
                block += 1
                if got < want:
                    return
        finally:
            self._settle()

    def readinto(self, address, buf):
        """Read ``len(buf)`` bytes from ``address`` into ``buf``; returns how many arrived."""
        mv = memoryview(buf)
        done = 0
        for chunk in self.chunks(address, len(buf)):
            mv[done:done + len(chunk)] = chunk
            done += len(chunk)
        return done

    def read(self, address, length):
        """``length`` bytes from ``address``, as bytes."""
        out = bytearray(length)
        return bytes(out[:self.readinto(address, out)])

    def close(self):
        self.dev._release_all()
