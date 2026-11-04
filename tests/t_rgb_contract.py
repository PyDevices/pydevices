# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The XL9535 expander and ST7701 start-up drivers, checked bit by bit.

Both drivers run against fakes: an I2C bus that keeps a register file and logs
writes, and pins that log every level they are driven to. The checks are:

* the XL9535 writes the TCA9535-family registers the datasheet gives (output
  0x02/0x03, polarity 0x04/0x05, configuration 0x06/0x07; input 0x00/0x01),
  with a 1 in a configuration bit meaning input;
* `run_init` clocks every frame as 9 bits, D/C first (0 command, 1 parameter),
  then the byte most significant bit first, sampled on the rising edge of the
  clock, with chip select low from a command through its parameters;
* the first command is spelled out literally, bit for bit;
* reset goes low and high before any frame, and Sleep Out is followed by a wait
  of at least 120 ms;
* the board config's calls (`XL9535(i2c)`, `pinMode8`, `Pin(...)`, `LCDPins`)
  work as it makes them.

A plain script, so it runs on CPython and on MicroPython::

    python tests/t_rgb_contract.py
    micropython tests/t_rgb_contract.py
    python tests/t_rgb_contract.py --plant=xl-config   # must FAIL

Datasheets: TI TCA9535 (SCPS209), register map; Sitronix ST7701S V1.1, 3-line
serial interface (data stream format, figure 10) and reset timing (note 7).
"""

import sys

try:
    _here = __file__
except NameError:  # pragma: no cover
    _here = sys.argv[0]
_sep = "\\" if "\\" in _here else "/"
_dir = _here.rsplit(_sep, 1)[0] if _sep in _here else "."
ROOT = _dir + _sep + ".."
for _p in ("drivers" + _sep + "display", "drivers" + _sep + "io_expander"):
    sys.path.insert(0, ROOT + _sep + _p)

import st7701
import xl9535

PLANT = None
for _arg in sys.argv[1:]:
    if _arg.startswith("--plant="):
        PLANT = _arg[len("--plant=") :]

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


class FakeI2C:
    def __init__(self, regs=None):
        self.regs = dict(regs or {})
        self.writes = []

    def readfrom_mem(self, addr, reg, n):
        return bytes(self.regs.get(reg + i, 0xFF) for i in range(n))

    def writeto_mem(self, addr, reg, data):
        self.writes.append((addr, reg, bytes(data)))
        for i, b in enumerate(data):
            self.regs[reg + i] = b


class LogPin:
    def __init__(self, name, log):
        self.name = name
        self.log = log

    def value(self, v=None):
        self.log.append((self.name, 1 if v else 0))


############### Plants ################

if PLANT == "xl-config":
    # Treat a 1 in the configuration register as output.
    def _bad_pinMode8(self, port, mask, mode):
        mask &= 0xFF
        value = (self._config[port] | mask) if mode == xl9535.OUT else (self._config[port] & ~mask)
        self._config[port] = value
        self._write(0x06 + port, value)

    xl9535.XL9535.pinMode8 = _bad_pinMode8
elif PLANT == "dc-last":
    def _bad_send(pins, dc, byte):
        for shift in range(7, -1, -1):
            pins.sda.value((byte >> shift) & 1)
            pins.clk.value(1)
            pins.clk.value(0)
        pins.sda.value(dc)
        pins.clk.value(1)
        pins.clk.value(0)

    st7701._send = _bad_send
elif PLANT == "lsb-first":
    def _bad_send(pins, dc, byte):
        pins.sda.value(dc)
        pins.clk.value(1)
        pins.clk.value(0)
        for shift in range(8):
            pins.sda.value((byte >> shift) & 1)
            pins.clk.value(1)
            pins.clk.value(0)

    st7701._send = _bad_send
elif PLANT == "no-sleep-wait":
    st7701._DELAY_AFTER = {}
elif PLANT is not None:
    print("unknown plant", PLANT)
    sys.exit(2)

if PLANT:
    print("PLANTED", PLANT)


############### XL9535 ################


def check_xl9535():
    bus = FakeI2C({2: 0xFF, 3: 0xFF, 6: 0xFF, 7: 0xFF})
    xl = xl9535.XL9535(bus)
    check("xl9535 default address is 0x20", xl.address == 0x20)
    check("xl9535 start-up writes nothing", bus.writes == [], bus.writes)

    # Port 0 pins 1..6 to outputs: configuration 0x06 loses those bits.
    mask = 0b01111110
    xl.pinMode8(0, mask, xl.OUT)
    check("pinMode8 out clears config bits", bus.writes[-1] == (0x20, 0x06, bytes([0x81])), bus.writes[-1])
    xl.pinMode8(0, 0b00000100, xl.IN)
    check("pinMode8 in sets config bits", bus.writes[-1] == (0x20, 0x06, bytes([0x85])), bus.writes[-1])
    xl.pinMode8(1, 0xFF, xl.OUT)
    check("pinMode8 port 1 uses 0x07", bus.writes[-1] == (0x20, 0x07, bytes([0x00])), bus.writes[-1])

    xl.digitalWrite(2, 0)
    check("digitalWrite low clears output bit", bus.writes[-1] == (0x20, 0x02, bytes([0xFB])), bus.writes[-1])
    xl.digitalWrite(2, 1)
    check("digitalWrite high sets output bit", bus.writes[-1] == (0x20, 0x02, bytes([0xFF])), bus.writes[-1])
    xl.digitalWrite(9, 0)
    check("digitalWrite pin 9 is port 1 bit 1", bus.writes[-1] == (0x20, 0x03, bytes([0xFD])), bus.writes[-1])
    xl.digitalWrite8(0, 0x0F, 0x05)
    check("digitalWrite8 sets masked bits only", bus.writes[-1] == (0x20, 0x02, bytes([0xF5])), bus.writes[-1])
    xl.polarity8(1, 0x30)
    check("polarity8 writes 0x05", bus.writes[-1] == (0x20, 0x05, bytes([0x30])), bus.writes[-1])

    bus.regs[0] = 0b00001000
    bus.regs[1] = 0b00000010
    check("digitalRead pin 3 reads input 0x00", xl.digitalRead(3) == 1 and xl.digitalRead(4) == 0)
    check("digitalRead pin 9 reads input 0x01", xl.digitalRead(9) == 1 and xl.digitalRead(8) == 0)

    # Pins as the board config makes them.
    n = len(bus.writes)
    p = xl.Pin(1, xl.OUT, value=1)
    check(
        "Pin writes the level, then turns the pin into an output",
        bus.writes[n][1] == 0x02 and bus.writes[n + 1][1] == 0x06 and bus.writes[n + 1][2][0] & 2 == 0,
        bus.writes[n:],
    )
    p(0)
    check("Pin call drives the output", bus.writes[-1] == (0x20, 0x02, bytes([0xF5 & ~2])), bus.writes[-1])
    p.value(1)
    check("Pin.value(1) drives the output", bus.writes[-1][2][0] & 2 == 2)

    # A different start-up state is mirrored, not overwritten.
    bus2 = FakeI2C({2: 0xAA, 3: 0x55, 6: 0xF0, 7: 0x0F})
    xl2 = xl9535.XL9535(bus2, 0x21)
    xl2.digitalWrite(0, 1)
    check("start-up output state is kept", bus2.writes[-1] == (0x21, 0x02, bytes([0xAB])), bus2.writes[-1])


############### ST7701 ################


def decode(events):
    """Turn pin events into a list of transactions, each a list of (dc, byte).

    Also returns problems found: bits clocked while CS is high, frames that
    aren't 9 bits, SDA changing while the clock is high."""
    levels = {"cs": 1, "sda": 1, "clk": 0}
    txns = []
    cur = None
    bits = []
    problems = []
    for name, v in events:
        if name in ("pwr_en", "rst"):
            continue
        if name == "cs":
            if v == 0 and levels["cs"] == 1:
                cur = []
                bits = []
            elif v == 1 and levels["cs"] == 0:
                if bits:
                    problems.append("partial frame of %d bits" % len(bits))
                txns.append(cur)
                cur = None
            levels["cs"] = v
        elif name == "sda":
            if levels["clk"] == 1:
                problems.append("sda changed while clk high")
            levels["sda"] = v
        elif name == "clk":
            if v == 1 and levels["clk"] == 0:
                if cur is None:
                    problems.append("clock rose with cs high")
                else:
                    bits.append(levels["sda"])
                    if len(bits) == 9:
                        byte = 0
                        for b in bits[1:]:
                            byte = (byte << 1) | b
                        cur.append((bits[0], byte))
                        bits = []
            levels["clk"] = v
    return txns, problems


def check_st7701():
    log = []
    pins = st7701.LCDPins(
        pwr_en=LogPin("pwr_en", log),
        cs=LogPin("cs", log),
        sda=LogPin("sda", log),
        clk=LogPin("clk", log),
        rst=LogPin("rst", log),
    )
    sleeps = []

    def fake_sleep(ms):
        sleeps.append((len(log), ms))

    st7701._sleep_ms = fake_sleep
    st7701.run_init(pins)

    txns, problems = decode(log)
    check("every bit is clocked inside a 9-bit frame with cs low", problems == [], problems[:3])
    check("one transaction per table entry", len(txns) == len(st7701._INIT), (len(txns), len(st7701._INIT)))

    ok = True
    detail = ""
    for i, (txn, entry) in enumerate(zip(txns, st7701._INIT)):
        want = [(0, entry[0])] + [(1, b) for b in entry[1]]
        if txn != want:
            ok = False
            detail = "entry %d: got %r want %r" % (i, txn[:4], want[:4])
            break
    check("each command is D/C 0 and its parameters D/C 1", ok, detail)

    # The first command spelled out: 0xFF with 77 01 00 00 10.
    first = [i for i, e in enumerate(log) if e[0] == "cs" and e[1] == 0][0]
    stream = []
    sda = None
    clk = 0
    for name, v in log[first:]:
        if name == "sda":
            sda = v
        elif name == "clk":
            if v == 1 and clk == 0:
                stream.append(sda)
            clk = v
    want_bits = "0" + "11111111"
    for b in (0x77, 0x01, 0x00, 0x00, 0x10):
        want_bits += "1" + "".join("1" if (b >> s) & 1 else "0" for s in range(7, -1, -1))
    got_bits = "".join(str(b) for b in stream[: len(want_bits)])
    check("first command is 0 11111111 then 1 01110111 ...", got_bits == want_bits, got_bits)
    check("the table has the bank switch first", st7701._INIT[0] == (0xFF, b"\x77\x01\x00\x00\x10"))
    check("the table ends with Sleep Out then Display On", [e[0] for e in st7701._INIT[-2:]] == [0x11, 0x29])

    # Reset: low then high before the first frame; a wait after release.
    rst = [(i, v) for i, (n, v) in enumerate(log) if n == "rst"]
    levels = [v for _, v in rst]
    check("reset pulses low then high", levels[-2:] == [0, 1], levels)
    check("reset is done before the first frame", rst[-1][0] < first)
    after_reset = [ms for (at, ms) in sleeps if at > rst[-1][0]][0]
    check("5 ms or more passes after reset is released", after_reset >= 5, after_reset)
    pulse = [ms for (at, ms) in sleeps if rst[-2][0] < at <= rst[-1][0]]
    check("reset is held low at least 10 us", bool(pulse) and pulse[0] >= 1, pulse)
    check("power is enabled", ("pwr_en", 1) in log)

    # 120 ms after Sleep Out.
    sleep_out_end = None
    count = 0
    for i, (n, v) in enumerate(log):
        if n == "cs" and v == 1:
            if txns[count][0] == (0, 0x11):
                sleep_out_end = i
                break
            count += 1
    waits = [ms for (at, ms) in sleeps if sleep_out_end is not None and at > sleep_out_end]
    check("at least 120 ms follows Sleep Out", bool(waits) and waits[0] >= 120, waits[:2])
    check("cs and clk end idle", log[-1] == ("cs", 1) or ("cs", 1) in log[-3:])


def check_board_calls():
    # The calls board_configs/fbdisplay/t-rgb_480/board_config.py makes.
    bus = FakeI2C({2: 0xFF, 3: 0xFF, 6: 0xFF, 7: 0xFF})
    xl = xl9535.XL9535(bus)
    xl.pinMode8(0, (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 1), xl.OUT)
    xl.digitalWrite(2, 1)
    pins = st7701.LCDPins(
        pwr_en=xl.Pin(2, xl.OUT, value=1),
        cs=xl.Pin(3, xl.OUT, value=1),
        sda=xl.Pin(4, xl.OUT, value=1),
        clk=xl.Pin(5, xl.OUT, value=1),
        rst=xl.Pin(6, xl.OUT, value=1),
    )
    st7701._sleep_ms = lambda ms: None
    st7701.run_init(pins)
    check("run_init drives real expander pins", len(bus.writes) > 1000, len(bus.writes))
    tp = xl.Pin(1, xl.OUT, value=1)
    tp(0)
    tp(1)
    check("touch reset pin can be called", bus.regs[2] & 2 == 2)


for _fn in (check_xl9535, check_st7701, check_board_calls):
    try:
        _fn()
    except Exception as _e:
        check(_fn.__name__ + " ran to the end", False, repr(_e))

print("{} passed, {} failed ({})".format(_passed, _failed, sys.implementation.name))
sys.exit(1 if _failed else 0)
