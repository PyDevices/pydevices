# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The page-addressed and grayscale OLED drivers, checked byte by byte.

Covers the SH1106, SH1107 and SSD1305 (one-bit pages) and the SSD1322, SSD1325
and SSD1327 (4-bit gray). Each driver is constructed against a recording fake
bus, and the checks look at what reached the bus:

* every command in the init sequence and in drawing is one the controller's
  datasheet defines, with the number of parameters the datasheet gives it,
  sent the way the datasheet wants them (with D/C low, or as data);
* the init configures the panel's size (multiplex ratio, offsets);
* drawing a known pattern puts the right page or column/row address and the
  right bytes on the bus, including RAM column offsets and nibble order;
* the board configs that use these drivers construct.

A plain script, not unittest, so the same file runs on CPython and on
MicroPython::

    python tests/oled_contract.py
    micropython tests/oled_contract.py
    python tests/oled_contract.py --plant=sh1106-colstart   # must FAIL

It prints one PASS/FAIL line per check and exits non-zero on any failure.
``tests/test_oled_drivers.py`` runs it both ways and runs every plant: a plant
breaks a driver the way a real mistake would, and checks that still pass under
it aren't checking anything.

Datasheets the command tables below come from:

* SH1106: Sino Wealth SH1106 V2.6, command table, pages 30-31.
* SH1107: Sino Wealth SH1107, command table, pages 41-42; RAM map, figure 10, page 18.
* SSD1305: Solomon Systech SSD1305 Rev 1.9, table 9-1, pages 33-38.
* SSD1322: Solomon Systech SSD1322 Rev 0.10, table 9-1, pages 31-35; GDDRAM, figure 10-5, page 38.
* SSD1325: Solomon Systech SSD1325 Rev 2.1, table 18, pages 30-33; GDDRAM, table 11, page 25.
* SSD1327: Solomon Systech SSD1327 Rev 1.1, table 9-1, pages 36-40; GDDRAM, tables 8-6 and 8-8, pages 30-31.
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
ROOT = _dir + _sep + ".."
for _p in ("lib", "utils", "drivers" + _sep + "display", "drivers" + _sep + "bus"):
    sys.path.insert(0, ROOT + _sep + _p)

import i2cbus
import sh1106
import sh1107
import ssd1305
import ssd1322
import ssd1325
import ssd1327

WHITE = 0xFFFF
BLACK = 0x0000

PLANT = None
for _arg in sys.argv[1:]:
    if _arg.startswith("--plant="):
        PLANT = _arg[len("--plant=") :]


############### Datasheet command sets ################
#
# {command byte: number of parameter bytes}. A single-byte command that
# carries its value in its low bits (a column address, a page, a start line)
# is listed once per value.


def _span(table, first, last, params=0):
    for c in range(first, last + 1):
        table[c] = params
    return table


# SH1106 V2.6, command table (pages 30-31).
SH1106_COMMANDS = {0x81: 1, 0xA8: 1, 0xAD: 1, 0xD3: 1, 0xD5: 1, 0xD9: 1, 0xDA: 1, 0xDB: 1}
_span(SH1106_COMMANDS, 0x00, 0x0F)  # lower column address
_span(SH1106_COMMANDS, 0x10, 0x1F)  # higher column address
_span(SH1106_COMMANDS, 0x30, 0x33)  # pump voltage
_span(SH1106_COMMANDS, 0x40, 0x7F)  # display start line
_span(SH1106_COMMANDS, 0xA0, 0xA1)  # segment re-map
_span(SH1106_COMMANDS, 0xA4, 0xA7)  # entire display, normal/reverse
_span(SH1106_COMMANDS, 0xAE, 0xAF)  # display off/on
_span(SH1106_COMMANDS, 0xB0, 0xB7)  # page address
_span(SH1106_COMMANDS, 0xC0, 0xCF)  # COM scan direction (low bits don't care)
SH1106_COMMANDS.update({0xE0: 0, 0xEE: 0, 0xE3: 0})

# SH1107, command table (pages 41-42).
SH1107_COMMANDS = {0x81: 1, 0xA8: 1, 0xD3: 1, 0xAD: 1, 0xD5: 1, 0xD9: 1, 0xDB: 1, 0xDC: 1}
_span(SH1107_COMMANDS, 0x00, 0x0F)  # lower column address
_span(SH1107_COMMANDS, 0x10, 0x17)  # higher column address (three bits)
_span(SH1107_COMMANDS, 0x20, 0x21)  # memory addressing mode
_span(SH1107_COMMANDS, 0xA0, 0xA1)
_span(SH1107_COMMANDS, 0xA4, 0xA7)
_span(SH1107_COMMANDS, 0xAE, 0xAF)
_span(SH1107_COMMANDS, 0xB0, 0xBF)  # page address (16 pages)
_span(SH1107_COMMANDS, 0xC0, 0xCF)
SH1107_COMMANDS.update({0xE0: 0, 0xEE: 0, 0xE3: 0})

# SSD1305 Rev 1.9, table 9-1 (pages 33-38).
SSD1305_COMMANDS = {
    0x20: 1,
    0x21: 2,
    0x22: 2,
    0x81: 1,
    0x82: 1,
    0x91: 4,
    0x92: 4,
    0xA3: 2,
    0xA8: 1,
    0xAD: 1,
    0xD3: 1,
    0xD5: 1,
    0xD8: 1,
    0xD9: 1,
    0xDA: 1,
    0xDB: 1,
}
_span(SSD1305_COMMANDS, 0x00, 0x0F)
_span(SSD1305_COMMANDS, 0x10, 0x1F)
_span(SSD1305_COMMANDS, 0x40, 0x7F)
_span(SSD1305_COMMANDS, 0xA0, 0xA1)
_span(SSD1305_COMMANDS, 0xA4, 0xA7)
_span(SSD1305_COMMANDS, 0xB0, 0xB7)
SSD1305_COMMANDS.update({0xAC: 0, 0xAE: 0, 0xAF: 0, 0xC0: 0, 0xC8: 0, 0xE0: 0, 0xE3: 0, 0xEE: 0, 0x2E: 0, 0x2F: 0})

# SSD1322 Rev 0.10, table 9-1 (pages 31-35). Parameters go with D/C high.
# B4h and D1h (display enhancement A and B, two parameters each) are not in
# Rev 0.10; Newhaven's NHD-3.12-25664 sample code and later revisions use them.
SSD1322_COMMANDS = {
    0x00: 0,
    0x15: 2,
    0x5C: 0,
    0x5D: 0,
    0x75: 2,
    0xA0: 2,
    0xA1: 1,
    0xA2: 1,
    0xA8: 2,
    0xA9: 0,
    0xAB: 1,
    0xB1: 1,
    0xB3: 1,
    0xB5: 1,
    0xB6: 1,
    0xB8: 15,
    0xB9: 0,
    0xBB: 1,
    0xBE: 1,
    0xC1: 1,
    0xC7: 1,
    0xCA: 1,
    0xFD: 1,
    0xB4: 2,
    0xD1: 2,
}
_span(SSD1322_COMMANDS, 0xA4, 0xA7)
_span(SSD1322_COMMANDS, 0xAE, 0xAF)
SSD1322_WRITE_RAM = 0x5C

# SSD1325 Rev 2.1, table 18 (pages 30-33). Parameters go with D/C low.
SSD1325_COMMANDS = {
    0x15: 2,
    0x75: 2,
    0x81: 1,
    0xA0: 1,
    0xA1: 1,
    0xA2: 1,
    0xA8: 1,
    0xAD: 1,
    0xB0: 1,
    0xB1: 1,
    0xB2: 1,
    0xB3: 1,
    0xB4: 1,
    0xB8: 8,
    0xBC: 1,
    0xBE: 1,
    0xBF: 1,
    0xE3: 0,
    0x2E: 0,
    0x2F: 0,
}
_span(SSD1325_COMMANDS, 0x84, 0x86)
_span(SSD1325_COMMANDS, 0xA4, 0xA7)
_span(SSD1325_COMMANDS, 0xAE, 0xAF)

# SSD1327 Rev 1.1, table 9-1 (pages 36-40). Parameters go with D/C low.
SSD1327_COMMANDS = {
    0x15: 2,
    0x75: 2,
    0x81: 1,
    0xA0: 1,
    0xA1: 1,
    0xA2: 1,
    0xA8: 1,
    0xAB: 1,
    0xB1: 1,
    0xB2: 0,
    0xB3: 1,
    0xB5: 1,
    0xB6: 1,
    0xB8: 15,
    0xB9: 0,
    0xBB: 0,
    0xBC: 1,
    0xBE: 1,
    0xD5: 1,
    0xFD: 1,
    0x2E: 0,
    0x2F: 0,
}
_span(SSD1327_COMMANDS, 0x84, 0x86)
_span(SSD1327_COMMANDS, 0xA4, 0xA7)
_span(SSD1327_COMMANDS, 0xAE, 0xAF)


############### Fake buses ################


class FakeI2C:
    """machine.I2C: writeto only."""

    def __init__(self):
        self.writes = []

    def writeto(self, address, buf):
        self.writes.append((address, bytes(buf)))


class FakeBusioI2C(FakeI2C):
    """busio.I2C: writes only while locked."""

    def __init__(self):
        super().__init__()
        self.locked = False

    def try_lock(self):
        if self.locked:
            return False
        self.locked = True
        return True

    def unlock(self):
        self.locked = False

    def writeto(self, address, buf):
        if not self.locked:
            raise RuntimeError("busio.I2C written while unlocked")
        super().writeto(address, buf)


class FakeSPIBus:
    """FourWire / SPIBus: send(command, data): the command with D/C low, data with D/C high."""

    def __init__(self):
        self.sent = []

    def send(self, command, data=b""):
        self.sent.append((command, bytes(data)))


class I2CDisplayBus:
    def send(self, command, data):
        pass


def i2c_events(writes):
    """[('cmd' | 'data', payload)] from I2C writes, by their control byte."""
    out = []
    for _addr, buf in writes:
        out.append(("cmd" if buf[0] == 0x00 else "data", buf[1:]))
    return out


def i2c_commands(writes):
    return [p for kind, p in i2c_events(writes) if kind == "cmd"]


def i2c_data(writes):
    return [p for kind, p in i2c_events(writes) if kind == "data"]


############### Results ################

_passed = 0
_failed = 0


def check(name, ok, detail=""):
    global _passed, _failed
    if ok:
        _passed += 1
        print("PASS", name)
    else:
        _failed += 1
        print("FAIL", name, detail)


def same(name, got, want):
    check(name, got == want, "got {!r}, want {!r}".format(got, want))


def raises(name, exc, fn):
    try:
        fn()
    except exc as e:
        check(name, True)
        return str(e)
    except Exception as e:
        check(name, False, "raised {!r}".format(e))
        return None
    check(name, False, "did not raise")
    return None


############### Datasheet parsing ################


def parse_i2c_commands(table, writes):
    """Each command write must be one datasheet command with its parameter count.

    Returns the list of problems (empty when every write parses).
    """
    problems = []
    for payload in i2c_commands(writes):
        i = 0
        while i < len(payload):
            c = payload[i]
            if c not in table:
                problems.append("unknown command 0x{:02x} in {!r}".format(c, payload))
                break
            i += 1 + table[c]
        if i != len(payload) and not problems:
            problems.append("parameter count off in {!r}".format(payload))
    return problems


def parse_spi_commands_low(table, sent, nop=None):
    """Parameters with D/C low: the stream of command bytes must parse.

    Data rides only on a no-op (``nop``) or as the last parameter's data.
    """
    problems = []
    need = 0
    for command, data in sent:
        if need:
            need -= 1
        elif command not in table:
            problems.append("unknown command 0x{:02x}".format(command))
        else:
            need = table[command]
        if data and (need or command != nop):
            problems.append("data after 0x{:02x}, not after the no-op".format(command))
    if need:
        problems.append("stream ended {} parameters short".format(need))
    return problems


def parse_spi_commands_high(table, sent, write_ram):
    """Parameters with D/C high (SSD1322): each send is a command and its parameters."""
    problems = []
    for command, data in sent:
        if command not in table:
            problems.append("unknown command 0x{:02x}".format(command))
        elif command == write_ram:
            continue
        elif len(data) != table[command]:
            problems.append("0x{:02x} sent {} parameters, datasheet has {}".format(command, len(data), table[command]))
    return problems


############### Plants ################
#
# Each breaks one driver the way a real mistake would. The contract must fail.

PLANTS = ("sh1106-colstart", "sh1106-init", "sh1107-mux", "nibble-order", "ssd1322-dc")

if PLANT == "sh1106-colstart":
    # Write a 128-wide panel from RAM column 0, ignoring the SH1106's 132 columns.
    _orig_sh1106_init = sh1106.SH1106.__init__

    def _plant_sh1106_init(self, bus, **kw):
        kw["colstart"] = 0
        _orig_sh1106_init(self, bus, **kw)

    sh1106.SH1106.__init__ = _plant_sh1106_init
elif PLANT == "sh1106-init":
    # Put back the memory-mode command the SH1106 doesn't have (0x20, from the SH1107).
    sh1106._INIT_SEQUENCE = sh1106._INIT_SEQUENCE[:-2] + b"\x20\x01\x20" + sh1106._INIT_SEQUENCE[-2:]
elif PLANT == "sh1107-mux":
    # Size the multiplex ratio from the segments, as if the columns were segments.
    _orig_sh1107_init = sh1107.SH1107.init

    def _plant_sh1107_init(self):
        self._init_sequence[sh1107._MUX] = self._height - 1
        _orig_sh1107_init(self)

    sh1107.SH1107.init = _plant_sh1107_init
elif PLANT == "nibble-order":
    # Pack the SSD1327's first pixel in the high nibble.
    ssd1327._EVEN_SHIFT = 4
elif PLANT == "ssd1322-dc":
    # Send the SSD1322's parameters as commands (D/C low), as the SSD1325 wants.
    def _plant_ssd1322_command(self, *values):
        for v in values:
            self._send(v, b"")

    ssd1322.SSD1322._command = _plant_ssd1322_command
elif PLANT is not None:
    print("unknown plant", PLANT)
    sys.exit(2)

if PLANT:
    print("PLANTED", PLANT)


############### SH1106 ################


def _sh1106(width=128, height=64, i2c=None, **kw):
    i2c = i2c or FakeI2C()
    drv = sh1106.SH1106(i2cbus.I2CBus(i2c, device_address=0x3C), width=width, height=height, quiet=True, **kw)
    return drv, i2c


def check_sh1106():
    drv, i2c = _sh1106()
    check("sh1106: init and drawing use only datasheet commands", not parse_i2c_commands(SH1106_COMMANDS, i2c.writes),
          parse_i2c_commands(SH1106_COMMANDS, i2c.writes))
    cmds = i2c_commands(i2c.writes)
    same("sh1106: first command is display off", cmds[0], b"\xae")
    check("sh1106: multiplex ratio 1/64", b"\xa8\x3f" in cmds)
    check("sh1106: DC-DC on (0xAD 0x8B)", b"\xad\x8b" in cmds)
    check("sh1106: display on", b"\xaf" in cmds)
    # The clear: eight pages, each addressed from RAM column 2 (132 - 128) / 2.
    page_cmds = [c for c in cmds if len(c) == 3 and 0xB0 <= c[0] <= 0xB7]
    same("sh1106: clear addresses pages 0-7 at column 2", page_cmds, [bytes((0xB0 | p, 0x10, 0x02)) for p in range(8)])
    same("sh1106: clear writes 128 zero bytes per page", i2c_data(i2c.writes), [bytes(128)] * 8)
    same("sh1106: reports the 565 API", (drv.width, drv.height, drv.color_depth), (128, 64, 16))

    i2c.writes.clear()
    drv.fill_rect(0, 0, 8, 8, WHITE)
    same("sh1106: fill page 0 columns 0-7: address", i2c_commands(i2c.writes), [b"\xb0\x10\x02"])
    same("sh1106: fill page 0 columns 0-7: bytes", i2c_data(i2c.writes), [b"\xff" * 8])

    i2c.writes.clear()
    drv.pixel(3, 10, WHITE)  # page 1, bit 2, RAM column 5
    same("sh1106: pixel (3, 10): address", i2c_commands(i2c.writes), [b"\xb1\x10\x05"])
    same("sh1106: pixel (3, 10): byte", i2c_data(i2c.writes), [b"\x04"])

    i2c.writes.clear()
    drv.pixel(127, 63, WHITE)  # last pixel: page 7, bit 7, RAM column 129 (0x81)
    same("sh1106: pixel (127, 63): address", i2c_commands(i2c.writes), [b"\xb7\x18\x01"])
    same("sh1106: pixel (127, 63): byte", i2c_data(i2c.writes), [b"\x80"])

    i2c.writes.clear()
    drv.fill_rect(0, 0, 4, 64, WHITE)
    drv.fill_rect(0, 2, 4, 3, BLACK)  # clears rows 2-4 of page 0
    same("sh1106: partial page keeps the other bits", i2c_data(i2c.writes)[-1], bytes([0b11100011]) * 4)

    drv, i2c = _sh1106(rotation=180)
    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)
    same("sh1106: rotation 180 puts (0, 0) at page 7 column 129", i2c_commands(i2c.writes), [b"\xb7\x18\x01"])

    drv, i2c = _sh1106(width=132)
    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)
    same("sh1106: a 132-wide panel starts at column 0", i2c_commands(i2c.writes), [b"\xb0\x10\x00"])

    drv, i2c = _sh1106(colstart=0)
    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)
    same("sh1106: colstart=0 is honoured", i2c_commands(i2c.writes), [b"\xb0\x10\x00"])

    i2c.writes.clear()
    drv.brightness = 0.5
    drv.invert_colors(True)
    drv.sleep()
    drv.wake()
    same("sh1106: contrast, invert, sleep, wake", i2c_commands(i2c.writes), [b"\x81\x7f", b"\xa7", b"\xae", b"\xaf"])

    bus = FakeSPIBus()
    drv = sh1106.SH1106(bus, width=128, height=64, quiet=True)
    check("sh1106 on SPI: command stream parses", not parse_spi_commands_low(SH1106_COMMANDS, bus.sent, 0xE3),
          parse_spi_commands_low(SH1106_COMMANDS, bus.sent, 0xE3))
    bus.sent.clear()
    drv.fill_rect(0, 0, 2, 8, WHITE)
    same("sh1106 on SPI: page, column, then pixels after a no-op", bus.sent,
         [(0xB0, b""), (0x10, b""), (0x02, b""), (0xE3, b"\xff\xff")])

    msg = raises("sh1106: I2CDisplayBus refused", TypeError, lambda: sh1106.SH1106(I2CDisplayBus(), width=128, height=64, quiet=True))
    check("sh1106: refusal names i2cbus.I2CBus", msg is not None and "i2cbus.I2CBus" in msg)

    i2c = FakeBusioI2C()
    _sh1106(i2c=i2c)
    check("sh1106: busio.I2C locked per write and released", bool(i2c.writes) and not i2c.locked)


############### SH1107 ################


def _sh1107(width=64, height=128, rotation=90, **kw):
    i2c = FakeI2C()
    drv = sh1107.SH1107(i2cbus.I2CBus(i2c, device_address=0x3C), width=width, height=height, rotation=rotation, quiet=True, **kw)
    return drv, i2c


def check_sh1107():
    drv, i2c = _sh1107()
    check("sh1107: init and drawing use only datasheet commands", not parse_i2c_commands(SH1107_COMMANDS, i2c.writes),
          parse_i2c_commands(SH1107_COMMANDS, i2c.writes))
    cmds = i2c_commands(i2c.writes)
    same("sh1107: first command is display off", cmds[0], b"\xae")
    check("sh1107: page addressing mode", b"\x20" in cmds)
    # The FeatherWing: 64 common lines (RAM columns), wired from COM 0x60.
    check("sh1107: multiplex ratio = 64 common lines", b"\xa8\x3f" in cmds, cmds)
    check("sh1107: display offset 0x60 for a 64-line panel", b"\xd3\x60" in cmds)
    same("sh1107: FeatherWing is 128x64 landscape at rotation 90", (drv.width, drv.height), (128, 64))
    page_cmds = [c for c in cmds if len(c) == 3 and 0xB0 <= c[0] <= 0xBF]
    same("sh1107: clear addresses all 16 pages at column 0", page_cmds, [bytes((0xB0 | p, 0x10, 0x00)) for p in range(16)])
    same("sh1107: clear writes 64 zero bytes per page", i2c_data(i2c.writes), [bytes(64)] * 16)

    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)  # logical top-left: segment 0, common line 63
    same("sh1107: pixel (0, 0): page 0, column 63", i2c_commands(i2c.writes), [b"\xb0\x13\x0f"])
    same("sh1107: pixel (0, 0): bit 0", i2c_data(i2c.writes), [b"\x01"])

    i2c.writes.clear()
    drv.pixel(127, 63, WHITE)  # logical bottom-right: segment 127, common line 0
    same("sh1107: pixel (127, 63): page 15, column 0", i2c_commands(i2c.writes), [b"\xbf\x10\x00"])
    same("sh1107: pixel (127, 63): bit 7", i2c_data(i2c.writes), [b"\x80"])

    i2c.writes.clear()
    drv.fill_rect(0, 0, 8, 2, WHITE)  # top two logical rows, x 0-7: page 0, columns 62-63
    same("sh1107: fill: address", i2c_commands(i2c.writes), [b"\xb0\x13\x0e"])
    same("sh1107: fill: bytes", i2c_data(i2c.writes), [b"\xff\xff"])

    drv, i2c = _sh1107(width=128, height=128, rotation=0)
    cmds = i2c_commands(i2c.writes)
    check("sh1107 128x128: multiplex ratio 128", b"\xa8\x7f" in cmds)
    check("sh1107 128x128: display offset 0", b"\xd3\x00" in cmds)
    i2c.writes.clear()
    drv.pixel(100, 9, WHITE)  # column 100 = 0x64, page 1, bit 1
    same("sh1107 128x128: high column nibble uses 0x10-0x17", i2c_commands(i2c.writes), [b"\xb1\x16\x04"])
    same("sh1107 128x128: byte", i2c_data(i2c.writes), [b"\x02"])

    drv, i2c = _sh1107(display_offset=0x20)
    check("sh1107: display_offset is honoured", b"\xd3\x20" in i2c_commands(i2c.writes))

    raises("sh1107: I2CDisplayBus refused", TypeError, lambda: sh1107.SH1107(I2CDisplayBus(), width=64, height=128, quiet=True))


############### SSD1305 ################


def _ssd1305(width=128, height=32, bus=None, **kw):
    i2c = FakeI2C()
    bus = bus or i2cbus.I2CBus(i2c, device_address=0x3C)
    drv = ssd1305.SSD1305(bus, width=width, height=height, quiet=True, **kw)
    return drv, i2c


def check_ssd1305():
    drv, i2c = _ssd1305()
    check("ssd1305: init and drawing use only datasheet commands", not parse_i2c_commands(SSD1305_COMMANDS, i2c.writes),
          parse_i2c_commands(SSD1305_COMMANDS, i2c.writes))
    cmds = i2c_commands(i2c.writes)
    same("ssd1305: first command is display off", cmds[0], b"\xae")
    check("ssd1305: multiplex ratio 1/32 for 32 rows", b"\xa8\x1f" in cmds)
    check("ssd1305: horizontal addressing", b"\x20\x00" in cmds)
    check("ssd1305: no charge pump command (the SSD1305 has none)", not [c for c in cmds if c[0] == 0x8D])
    check("ssd1305: clear covers columns 4-131 (a 128x32 starts at column 4)", b"\x21\x04\x83" in cmds)
    check("ssd1305: clear covers pages 0-3", b"\x22\x00\x03" in cmds)
    same("ssd1305: clear writes 128 zero bytes per page", i2c_data(i2c.writes), [bytes(128)] * 4)

    i2c.writes.clear()
    drv.pixel(3, 10, WHITE)
    same("ssd1305: pixel (3, 10): window", i2c_commands(i2c.writes), [b"\x21\x07\x07", b"\x22\x01\x01"])
    same("ssd1305: pixel (3, 10): byte", i2c_data(i2c.writes), [b"\x04"])

    drv, i2c = _ssd1305(height=64)
    cmds = i2c_commands(i2c.writes)
    check("ssd1305 128x64: multiplex 1/64", b"\xa8\x3f" in cmds)
    check("ssd1305 128x64: starts at column 0", b"\x21\x00\x7f" in cmds)

    bus = FakeSPIBus()
    drv, _ = _ssd1305(bus=bus)
    check("ssd1305 on SPI: command stream parses", not parse_spi_commands_low(SSD1305_COMMANDS, bus.sent, 0xE3),
          parse_spi_commands_low(SSD1305_COMMANDS, bus.sent, 0xE3))

    raises("ssd1305: I2CDisplayBus refused", TypeError, lambda: ssd1305.SSD1305(I2CDisplayBus(), width=128, height=32, quiet=True))


############### Grayscale ################

# RGB565 colors and the gray levels the drivers give them (luma, 0-15).
GRAYS = ((WHITE, 15), (BLACK, 0), (0xF800, 4), (0x07E0, 9), (0x001F, 2), (0x8410, 8))


def _row_writes(events):
    """[(column window, row, data)] from a gray driver's command/data events."""
    out = []
    col = None
    row = None
    for kind, payload in events:
        if kind == "cmd" and payload[0] == 0x15:
            col = (payload[1], payload[2])
        elif kind == "cmd" and payload[0] == 0x75:
            row = (payload[1], payload[2])
        elif kind == "data":
            out.append((col, row, payload))
    return out


def _ssd1327(width=128, height=128, **kw):
    i2c = FakeI2C()
    drv = ssd1327.SSD1327(i2cbus.I2CBus(i2c, device_address=0x3D), width=width, height=height, quiet=True, **kw)
    return drv, i2c


def check_ssd1327():
    drv, i2c = _ssd1327()
    check("ssd1327: init and drawing use only datasheet commands", not parse_i2c_commands(SSD1327_COMMANDS, i2c.writes),
          parse_i2c_commands(SSD1327_COMMANDS, i2c.writes))
    cmds = i2c_commands(i2c.writes)
    check("ssd1327: multiplex ratio 128", b"\xa8\x7f" in cmds)
    check("ssd1327: re-map 0x53 (column + nibble re-map)", b"\xa0\x53" in cmds)
    check("ssd1327: all writes to 0x3D", all(a == 0x3D for a, _ in i2c.writes))
    rows = _row_writes(i2c_events(i2c.writes))
    same("ssd1327: clear writes 128 rows", len(rows), 128)
    check("ssd1327: clear rows span columns 0-63, 64 zero bytes each",
          all(r[0] == (0, 63) and r[2] == bytes(64) for r in rows))
    same("ssd1327: clear rows go 0 to 127 in order", [r[1] for r in rows], [(y, y) for y in range(128)])
    same("ssd1327: reports the 565 API", (drv.width, drv.height, drv.color_depth), (128, 128, 16))

    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)
    same("ssd1327: pixel (0, 0): first pixel in the low nibble", _row_writes(i2c_events(i2c.writes)), [((0, 0), (0, 0), b"\x0f")])
    i2c.writes.clear()
    drv.pixel(1, 0, 0x8410)  # gray 8 in the high nibble of the same byte
    same("ssd1327: pixel (1, 0): high nibble, low kept", _row_writes(i2c_events(i2c.writes)), [((0, 0), (0, 0), b"\x8f")])

    i2c.writes.clear()
    drv.fill_rect(1, 5, 4, 2, WHITE)  # pixels 1-4: half of byte 0, byte 1, half of byte 2
    got = _row_writes(i2c_events(i2c.writes))
    same("ssd1327: fill (1, 5, 4x2): rows 5-6, columns 0-2",
         [(c, r) for c, r, _ in got], [((0, 2), (5, 5)), ((0, 2), (6, 6))])
    same("ssd1327: fill bytes split at nibble edges", [d for _, _, d in got], [b"\xf0\xff\x0f"] * 2)

    i2c.writes.clear()
    buf = bytearray()
    for c, _ in GRAYS:
        buf += bytes((c & 0xFF, c >> 8))
    drv.blit_rect(memoryview(buf), 10, 20, len(GRAYS), 1)
    levels = [g for _, g in GRAYS]
    want = bytes((levels[0] | levels[1] << 4, levels[2] | levels[3] << 4, levels[4] | levels[5] << 4))
    same("ssd1327: blit 565 to gray levels (white, black, red, green, blue, mid gray)",
         _row_writes(i2c_events(i2c.writes)), [((5, 7), (20, 20), want)])

    drv, i2c = _ssd1327(rotation=90)
    i2c.writes.clear()
    drv.pixel(0, 0, WHITE)  # rotation 90: logical (0, 0) is native (127, 0)
    same("ssd1327: rotation 90 puts (0, 0) at column 63, high nibble", _row_writes(i2c_events(i2c.writes)), [((63, 63), (0, 0), b"\xf0")])

    i2c.writes.clear()
    drv.brightness = 0.5
    drv.invert_colors(True)
    drv.invert_colors(False)
    drv.sleep()
    drv.wake()
    same("ssd1327: contrast, invert, normal (A4h), sleep, wake", i2c_commands(i2c.writes),
         [b"\x81\x7f", b"\xa7", b"\xa4", b"\xae", b"\xaf"])

    drv, i2c = _ssd1327(width=96, height=96, colstart=8)
    rows = _row_writes(i2c_events(i2c.writes))
    check("ssd1327 96x96: colstart 8 gives columns 8-55", rows[0][0] == (8, 55), rows[0])
    check("ssd1327 96x96: multiplex 96", b"\xa8\x5f" in i2c_commands(i2c.writes))

    bus = FakeSPIBus()
    ssd1327.SSD1327(bus, width=128, height=128, quiet=True)
    check("ssd1327 on SPI: command stream parses, pixels after a datasheet no-op",
          not parse_spi_commands_low(SSD1327_COMMANDS, bus.sent, 0xBB),
          parse_spi_commands_low(SSD1327_COMMANDS, bus.sent, 0xBB))

    raises("ssd1327: I2CDisplayBus refused", TypeError, lambda: ssd1327.SSD1327(I2CDisplayBus(), width=128, height=128, quiet=True))


def _spi_rows(sent, write_ram=None):
    """[(column window, row, data)] from SPI sends, parameters either as data or as commands."""
    out = []
    col = None
    row = None
    i = 0
    while i < len(sent):
        command, data = sent[i]
        if command == 0x15:
            if data:
                col = (data[0], data[1])
            else:
                col = (sent[i + 1][0], sent[i + 2][0])
                i += 2
        elif command == 0x75:
            if data:
                row = (data[0], data[1])
            else:
                row = (sent[i + 1][0], sent[i + 2][0])
                i += 2
        elif data and (write_ram is None or command == write_ram):
            out.append((col, row, data))
        i += 1
    return out


def check_ssd1325():
    bus = FakeSPIBus()
    drv = ssd1325.SSD1325(bus, width=128, height=64, quiet=True)
    check("ssd1325: init and drawing use only datasheet commands, parameters with D/C low",
          not parse_spi_commands_low(SSD1325_COMMANDS, bus.sent, 0xE3),
          parse_spi_commands_low(SSD1325_COMMANDS, bus.sent, 0xE3))
    stream = [c for c, _ in bus.sent]
    check("ssd1325: multiplex ratio 1/64", bytes(stream[:12]).find(b"\xa8\x3f") >= 0)
    rows = _spi_rows(bus.sent)
    same("ssd1325: clear writes 64 rows of 64 bytes over columns 0-63",
         (len(rows), all(r[0] == (0, 63) and r[2] == bytes(64) for r in rows)), (64, True))

    bus.sent.clear()
    drv.pixel(0, 0, WHITE)
    drv.pixel(3, 2, 0x07E0)  # green, gray 9, high nibble of byte 1
    same("ssd1325: pixels: low nibble first", _spi_rows(bus.sent),
         [((0, 0), (0, 0), b"\x0f"), ((1, 1), (2, 2), b"\x90")])

    bus.sent.clear()
    drv.brightness = 0.5
    drv.invert_colors(True)
    same("ssd1325: contrast is 7 bits (0.5 -> 63), invert", bus.sent, [(0x81, b""), (63, b""), (0xA7, b"")])

    raises("ssd1325: I2CDisplayBus refused", TypeError, lambda: ssd1325.SSD1325(I2CDisplayBus(), width=128, height=64, quiet=True))


def check_ssd1322():
    bus = FakeSPIBus()
    drv = ssd1322.SSD1322(bus, width=256, height=64, quiet=True)
    check("ssd1322: init and drawing use only datasheet commands, parameters as data",
          not parse_spi_commands_high(SSD1322_COMMANDS, bus.sent, SSD1322_WRITE_RAM),
          parse_spi_commands_high(SSD1322_COMMANDS, bus.sent, SSD1322_WRITE_RAM))
    check("ssd1322: multiplex ratio 1/64", (0xCA, b"\x3f") in bus.sent)
    check("ssd1322: re-map 0x14 with dual COM for 64 rows", (0xA0, b"\x14\x11") in bus.sent)
    check("ssd1322: gray scale table enabled after it is set", (0x00, b"") in bus.sent
          and bus.sent.index((0x00, b"")) > [c for c, _ in bus.sent].index(0xB8))
    rows = _spi_rows(bus.sent, SSD1322_WRITE_RAM)
    same("ssd1322: clear spans column addresses 28-91 (Newhaven's 256 pixels)", rows[0][0], (28, 91))
    same("ssd1322: clear writes 64 rows of 128 bytes", (len(rows), all(r[2] == bytes(128) for r in rows)), (64, True))

    bus.sent.clear()
    drv.pixel(0, 0, WHITE)
    same("ssd1322: pixel (0, 0): column 28, first pixel in the high nibble", _spi_rows(bus.sent, SSD1322_WRITE_RAM),
         [((28, 28), (0, 0), b"\xf0\x00")])
    bus.sent.clear()
    drv.pixel(7, 1, 0x8410)  # column address 29, pixel 3 of 4: low nibble of the second byte
    same("ssd1322: pixel (7, 1): column 29, fourth pixel", _spi_rows(bus.sent, SSD1322_WRITE_RAM),
         [((29, 29), (1, 1), b"\x00\x08")])

    bus.sent.clear()
    drv.invert_colors(True)
    drv.invert_colors(False)
    drv.brightness = 1.0
    same("ssd1322: invert A7h, normal A6h, contrast C1h", bus.sent, [(0xA7, b""), (0xA6, b""), (0xC1, b"\xff")])

    bus = FakeSPIBus()
    ssd1322.SSD1322(bus, width=256, height=128, quiet=True)
    check("ssd1322: 128 rows turns dual COM off (needs MUX <= 63)", (0xA0, b"\x14\x01") in bus.sent)

    raises("ssd1322: an I2C bus is refused", TypeError,
           lambda: ssd1322.SSD1322(i2cbus.I2CBus(FakeI2C(), device_address=0x3C), width=256, height=64, quiet=True))


############### Board configs ################


def _run_config(rel, modules):
    """Run a board_config.py with fake modules in place; return its globals."""
    saved = {}
    for name, mod in modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
    try:
        path = ROOT + _sep + rel.replace("/", _sep)
        with open(path) as f:
            src = f.read()
        g = {"__name__": "board_config"}
        exec(compile(src, path, "exec"), g)
        return g
    finally:
        for name, mod in saved.items():
            if mod is None:
                del sys.modules[name]
            else:
                sys.modules[name] = mod


class _Module:
    pass


def check_board_configs():
    recorded = []

    class I2C(FakeI2C):
        def __init__(self, *args, **kw):
            super().__init__()
            recorded.append(self)

    machine = _Module()
    machine.I2C = I2C
    machine.Pin = lambda *a, **k: a
    g = _run_config("board_configs/busdisplay/i2c/sh1107_oled_128x64/board_config.py", {"machine": machine})
    drv = g["display_drv"]
    same("config sh1107_oled_128x64 (MicroPython): 128x64 landscape", (drv.width, drv.height), (128, 64))
    cmds = i2c_commands(recorded[-1].writes)
    check("config sh1107_oled_128x64 (MicroPython): FeatherWing mux and offset",
          b"\xa8\x3f" in cmds and b"\xd3\x60" in cmds, cmds)

    busio_i2c = FakeBusioI2C()
    board = _Module()
    board.I2C = lambda: busio_i2c
    displayio = _Module()
    displayio.release_displays = lambda: None
    g = _run_config("board_configs/cp/busdisplay/i2c/sh1107_oled_128x64/board_config.py",
                    {"board": board, "displayio": displayio})
    drv = g["display_drv"]
    same("config sh1107_oled_128x64 (CircuitPython): 128x64 landscape", (drv.width, drv.height), (128, 64))
    check("config sh1107_oled_128x64 (CircuitPython): writes through busio.I2C, locked",
          bool(busio_i2c.writes) and not busio_i2c.locked)
    check("config sh1107_oled_128x64 (CircuitPython): pixels reach display RAM",
          len(i2c_data(busio_i2c.writes)) == 16)


############### Run ################

for _fn in (check_sh1106, check_sh1107, check_ssd1305, check_ssd1327, check_ssd1325, check_ssd1322, check_board_configs):
    try:
        _fn()
    except Exception as _e:
        check(_fn.__name__ + " ran to the end", False, repr(_e))

print("{} passed, {} failed ({})".format(_passed, _failed, sys.implementation.name))
sys.exit(1 if _failed else 0)
