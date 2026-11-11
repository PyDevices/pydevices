# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Vendor USB-serial chips for usb.host.cdc: CH34x, CP210x, FTDI and PL2303.

These chips don't speak CDC-ACM. Each has its own vendor requests for the
baud rate, the line format and the DTR and RTS lines, and the same pair of
bulk endpoints for the data. `find` says which chip a device is and returns a
driver with the three calls `usb.host.cdc.Serial` needs, so a program reads
any of them the same way.

The request values are the chips' own, as the Linux and FreeBSD drivers use
them (WCH, Silicon Labs, FTDI and Prolific publish no register documents for
most of this). The code is written for this package.

    chip = find(dev)
    chip.open()
    chip.line(115200, 8, 0, 0)
    chip.modem(True, True)
"""

import struct

# Vendor requests go to the device (CH34x), to the interface (CP210x) or to the
# device again (FTDI, PL2303); the direction bit is added per call.
_VENDOR_DEVICE = 0x40
_VENDOR_INTERFACE = 0x41
_VENDOR_DEVICE_IN = 0xC0
_CLASS_INTERFACE = 0x21

IDS_CH34X = ((0x1A86, 0x5523), (0x1A86, 0x7522), (0x1A86, 0x7523), (0x1A86, 0xE523), (0x4348, 0x5523),
         (0x2184, 0x0057), (0x9986, 0x7523))
IDS_CP210X = ((0x10C4, 0xEA60), (0x10C4, 0xEA61), (0x10C4, 0xEA63), (0x10C4, 0xEA70), (0x10C4, 0xEA71))
IDS_FTDI = ((0x0403, 0x6001), (0x0403, 0x6006), (0x0403, 0x6010), (0x0403, 0x6011), (0x0403, 0x6014),
        (0x0403, 0x6015), (0x0403, 0x6040), (0x0403, 0x6041), (0x0403, 0x6042), (0x0403, 0x6043),
        (0x0403, 0x6044), (0x0403, 0x6045))
IDS_PL2303 = ((0x067B, 0x2303), (0x067B, 0x2304), (0x067B, 0x23A3), (0x067B, 0x23B3), (0x067B, 0x23C3),
          (0x067B, 0x23D3), (0x067B, 0x23E3), (0x067B, 0x23F3))


def _bulk_pair(cfg):
    """(interface, bulk IN, bulk OUT, IN packet size) of the first interface
    with a bulk pair, or None."""
    i, cur, found = cfg[0], None, {}
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            cur = cfg[i + 2]
        elif cfg[i + 1] == 5 and cfg[i + 3] & 3 == 2 and cur is not None:
            row = found.setdefault(cur, [None, None, 64])
            if cfg[i + 2] & 0x80:
                row[0], row[2] = cfg[i + 2], cfg[i + 4] | cfg[i + 5] << 8
            else:
                row[1] = cfg[i + 2]
        i += cfg[i]
    for number in sorted(found):
        if found[number][0] is not None and found[number][1] is not None:
            return number, found[number][0], found[number][1], found[number][2]
    return None


class _Chip:
    """What every chip driver has: the device, its data endpoints, and a
    ``strip`` flag for chips that put status bytes in front of each IN packet."""

    name = "serial"
    strip = 0       # bytes each IN packet starts with that aren't data

    def __init__(self, dev, interface, ep_in, ep_out, mps):
        self.dev = dev
        self.interface = interface
        self.ep_in = ep_in
        self.ep_out = ep_out
        self.mps = mps

    def _out(self, request_type, request, value, index, data=None):
        return self.dev.ctrl_transfer(request_type, request, value, index, data, 1000)

    def _in(self, request, value, index, length, request_type=_VENDOR_DEVICE_IN):
        return bytes(self.dev.ctrl_transfer(request_type, request, value, index, length, 1000))

    def open(self):
        """Bring the chip up, as its vendor driver does, before any data moves."""

    def line(self, baudrate, bits, parity, stop):
        """Set the baud rate and format. ``parity`` is 0 none, 1 odd, 2 even,
        3 mark, 4 space; ``stop`` is 0 for one stop bit, 1 for 1.5 and 2 for two."""
        raise NotImplementedError

    def modem(self, dtr, rts):
        """Drive the DTR and RTS lines."""
        raise NotImplementedError


# -- CH340, CH341


def ch34x_divisor(baudrate):
    """The 16-bit value for the CH34x's prescaler and divisor registers: the
    divisor in the high byte, bit 7 (so the chip doesn't buffer) and the
    prescaler in the low."""
    if baudrate > 2000000:
        raise ValueError("the CH34x can't make %d baud" % baudrate)
    if baudrate == 921600:
        a, b = 0xF3, 7
    elif baudrate == 307200:
        a, b = 0xD9, 7
    else:
        if baudrate > 6000000 // 255:
            b, base = 3, 6000000
        elif baudrate > 750000 // 255:
            b, base = 2, 750000
        elif baudrate > 93750 // 255:
            b, base = 1, 93750
        else:
            b, base = 0, 11719
        a = base // baudrate
        if a == 0 or a == 0xFF:
            raise ValueError("the CH34x can't make %d baud" % baudrate)
        if base // a - baudrate > baudrate - base // (a + 1):
            a += 1
        a = 256 - a
    return a << 8 | 0x80 | b


def ch34x_lcr(bits, parity, stop):
    """The CH34x line control byte: receiver and transmitter on, then the format."""
    lcr = 0xC0 | (bits - 5)
    if parity == 1:
        lcr |= 0x08
    elif parity == 2:
        lcr |= 0x18
    elif parity == 3:
        lcr |= 0x28
    elif parity == 4:
        lcr |= 0x38
    if stop == 2:
        lcr |= 0x04
    return lcr


class CH34x(_Chip):
    name = "CH34x"

    def _write_reg(self, registers, value):
        self._out(_VENDOR_DEVICE, 0x9A, registers, value)

    def open(self):
        version = self._in(0x5F, 0, 0, 2)
        if version[0] >= 0x30:
            # Start at 9600 8N1: this request also carries the first format.
            self._out(_VENDOR_DEVICE, 0xA1, ch34x_lcr(8, 0, 0) << 8 | 0x9C, ch34x_divisor(9600))
            self._write_reg(0x0F2C, 0x0007)
            self._write_reg(0x2727, 0x0000)     # no hardware flow control

    def line(self, baudrate, bits, parity, stop):
        self._write_reg(0x1312, ch34x_divisor(baudrate))
        self._write_reg(0x2518, ch34x_lcr(bits, parity, stop))

    def modem(self, dtr, rts):
        # The chip's lines are active low.
        self._out(_VENDOR_DEVICE, 0xA4, ~((0x20 if dtr else 0) | (0x40 if rts else 0)) & 0xFF, 0)


# -- CP2102 and friends


class CP210x(_Chip):
    name = "CP210x"

    def open(self):
        self._out(_VENDOR_INTERFACE, 0x00, 0x0001, self.interface)     # enable the UART

    def line(self, baudrate, bits, parity, stop):
        self._out(_VENDOR_INTERFACE, 0x1E, 0, self.interface, struct.pack("<I", baudrate))
        self._out(_VENDOR_INTERFACE, 0x03, (bits & 0xF) << 8 | (parity & 0xF) << 4 | (stop & 0xF),
                  self.interface)

    def modem(self, dtr, rts):
        # The high byte says which of the two lines this request sets.
        self._out(_VENDOR_INTERFACE, 0x07, 0x0300 | (2 if rts else 0) | (1 if dtr else 0), self.interface)


# -- FT232, FT2232 and the rest of FTDI's range

# bcdDevice -> (chip, channels counted from the interface number, high-speed clock)
_FTDI_TYPES = {
    0x400: ("FT232B", False, False),
    0x500: ("FT2232C", True, False),
    0x600: ("FT232R", False, False),
    0x700: ("FT2232H", True, True),
    0x800: ("FT4232H", True, True),
    0x900: ("FT232H", True, True),
    0x1000: ("FT-X", True, False),
    0x2800: ("FT2233HP", True, True),
    0x2900: ("FT4233HP", True, True),
    0x3000: ("FT2232HP", True, True),
    0x3100: ("FT4232HP", True, True),
    0x3200: ("FT233HP", True, True),
    0x3300: ("FT232HP", True, True),
    0x3600: ("FT4232HA", True, True),
}
_FTDI_FRACTION = (0, 3, 2, 4, 1, 5, 6, 7)


def ftdi_divisor(baudrate, high_speed):
    """FTDI's baud divisor as one 32-bit number: the low 16 bits are the
    request's value, the high 16 its index."""
    if high_speed and baudrate >= 1200:
        three = (8 * 120000000 + 5 * baudrate) // (10 * baudrate)
    else:
        base = 48000000
        three = (base + baudrate) // (2 * baudrate)
    divisor = three >> 3 | _FTDI_FRACTION[three & 7] << 14
    if divisor == 1:
        divisor = 0
    elif divisor == 0x4001:
        divisor = 1
    if high_speed and baudrate >= 1200:
        divisor |= 0x00020000       # no divide by 2.5, so rates up to 12 Mbaud work
    return divisor


class FTDI(_Chip):
    name = "FTDI"
    strip = 2       # every IN packet starts with the modem and line status

    def open(self):
        version = self.dev.bcdDevice
        row = _FTDI_TYPES.get(version)
        if row is None:
            if version >= 0x200:
                raise OSError(95, "unknown FTDI chip, bcdDevice 0x%04x" % version)
            row = ("SIO", False, False)         # the oldest, with a fixed table of rates
        self.name, counted, self._fast = row
        self._channel = self.interface + 1 if counted else 0
        self._out(_VENDOR_DEVICE, 0x00, 0, self._channel)              # reset
        self._out(_VENDOR_DEVICE, 0x02, 0, self._channel)              # no flow control

    def line(self, baudrate, bits, parity, stop):
        divisor = ftdi_divisor(baudrate, self._fast)
        index = divisor >> 16
        if self._channel:
            index = index << 8 | self._channel
        self._out(_VENDOR_DEVICE, 0x03, divisor & 0xFFFF, index)
        self._out(_VENDOR_DEVICE, 0x04, (bits & 0xF) | (parity & 7) << 8 | (stop & 3) << 11, self._channel)

    def modem(self, dtr, rts):
        # The high byte is a mask of the lines being set; the low is their level.
        self._out(_VENDOR_DEVICE, 0x01, (0x0100 | (1 if dtr else 0)) | (0x0200 | (2 if rts else 0)), self._channel)


# -- PL2303

_PL_RATES = (75, 150, 300, 600, 1200, 1800, 2400, 3600, 4800, 7200, 9600, 14400, 19200, 28800, 38400,
             57600, 115200, 230400, 460800, 614400, 921600, 1228800, 2457600, 3000000, 6000000)


def pl2303_baud(baudrate, divisors=True, alt=False):
    """The four bytes of the PL2303's line coding that carry the baud rate: the
    number itself for a rate the chip makes directly, else a mantissa and an
    exponent (base 4, or base 2 on the TA and TB)."""
    if not divisors or baudrate in _PL_RATES:
        return struct.pack("<I", baudrate)
    mantissa = 12000000 * 32 // baudrate or 1
    exponent = 0
    if alt:
        while mantissa >= 2048:
            if exponent >= 15:
                mantissa = 2047
                break
            mantissa >>= 1
            exponent += 1
        return bytes((mantissa & 0xFF, (exponent & 0x1E) << 4 | mantissa >> 8, exponent & 1, 0x80))
    while mantissa >= 512:
        if exponent >= 7:
            mantissa = 511
            break
        mantissa >>= 2
        exponent += 1
    return bytes((mantissa & 0xFF, exponent << 1 | mantissa >> 8, 0, 0x80))


class PL2303(_Chip):
    name = "PL2303"

    def _read(self, value):
        return self._in(self._read_request, value, 0, 1)

    def _write(self, value, index):
        self._out(_VENDOR_DEVICE, self._write_request, value, index)

    def open(self):
        d = self.dev._device_desc()
        usb, version = d[2] | d[3] << 8, d[12] | d[13] << 8
        legacy = d[4] == 0x02 or d[7] != 0x40
        self._new = False
        self._alt = False
        if legacy:
            self.name = "PL2303H"
        elif usb in (0x101, 0x110):
            self.name = "PL2303HXD" if version == 0x400 else "PL2303HX"
        elif usb == 0x200:
            self._new = version in (0x100, 0x105, 0x300, 0x305, 0x400, 0x405, 0x500, 0x505, 0x600, 0x605,
                                    0x700, 0x705)
            self.name = "PL2303 (HXN)"
            if version in (0x300, 0x500):
                # The TA and TB answer a status read the others stall.
                try:
                    self._in(0x01, 0x8080, 0, 1)
                    self._new = False
                    self._alt = True
                    self.name = "PL2303TA" if version == 0x300 else "PL2303TB"
                except OSError:
                    pass
            if not self._new and not self._alt:
                raise OSError(95, "unknown PL2303, bcdDevice 0x%04x" % version)
        else:
            raise OSError(95, "unknown PL2303, bcdUSB 0x%04x" % usb)
        self._legacy = legacy
        self._read_request, self._write_request = (0x81, 0x80) if self._new else (0x01, 0x01)
        if not self._new:
            # The start-up writes and reads the chip's driver does, whatever each means.
            for step in ((0x8484,), (0x0404, 0), (0x8484,), (0x8383,), (0x8484,), (0x0404, 1), (0x8484,),
                         (0x8383,), (0, 1), (1, 0), (2, 0x24 if legacy else 0x44)):
                if len(step) == 1:
                    self._read(step[0])
                else:
                    self._write(step[0], step[1])
        if legacy:
            self._out(0x02, 0x01, 0, self.ep_out)       # CLEAR_FEATURE(ENDPOINT_HALT) on both
            self._out(0x02, 0x01, 0, self.ep_in)
        elif self._new:
            self._write(0x07, 0x03)             # reset both data pipes
        else:
            self._write(8, 0)
            self._write(9, 0)

    def line(self, baudrate, bits, parity, stop):
        coding = pl2303_baud(baudrate, not self._new, self._alt) + bytes((stop, parity, bits))
        self._out(_CLASS_INTERFACE, 0x20, 0, 0, coding)

    def modem(self, dtr, rts):
        self._out(_CLASS_INTERFACE, 0x22, (1 if dtr else 0) | (2 if rts else 0), 0)


def find(dev):
    """The driver for a vendor USB-serial adapter, or None if ``dev`` isn't one."""
    pair = (dev.idVendor, dev.idProduct)
    if pair in IDS_CH34X:
        kind = CH34x
    elif pair in IDS_CP210X:
        kind = CP210x
    elif pair in IDS_FTDI:
        kind = FTDI
    elif pair in IDS_PL2303:
        kind = PL2303
    else:
        return None
    bulk = _bulk_pair(dev.configuration_descriptor())
    return kind(dev, *bulk) if bulk else None
