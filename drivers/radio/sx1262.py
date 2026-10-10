# SPDX-FileCopyrightText: 2026 Brad Barnett / PyDevices
#
# SPDX-License-Identifier: MIT
"""Semtech SX1262 LoRa transceiver, in pure Python.

Point-to-point LoRa: configure, send a packet, receive one, and listen for
channel activity (CAD). No LoRaWAN, no FSK. Command opcodes and register
addresses are from Semtech's SX1261/2 datasheet (DS.SX1261-2, rev 2.1)::

    from machine import SPI, Pin
    spi = SPI(1, baudrate=8_000_000, sck=Pin(3), mosi=Pin(1), miso=Pin(4))
    radio = SX1262(spi, cs=Pin(5), busy=Pin(7), reset=Pin(8), dio1=Pin(9))
    radio.version                        # "SX1261 V2D 2D02"
    radio.configure(915.0, sf=9, power_dbm=10)
    radio.send(b"hello")                 # blocks until TX done; returns ms on air
    radio.receive(5000)                  # (payload, rssi_dbm, snr_db) or None
    radio.channel_active()               # True if LoRa preamble heard (CAD)

Pick a frequency your region allows (915 MHz in the Americas, 868 MHz in
Europe, 433 MHz in parts of Asia) and keep the power legal there.

Many SX1262 modules clock from a TCXO powered by the chip's DIO3 and switch
their antenna from DIO2: ``tcxo_volts`` and ``rf_switch`` cover both, and
both default to how LILYGO's T-Watch S3 and most SX1262 modules are wired.
Pass ``tcxo_volts=None`` for a module with a plain crystal.

Works with ``machine.SPI`` and ``machine.Pin`` (``busy`` and ``dio1`` as
inputs, ``cs`` and ``reset`` as outputs; the constructor sets the modes).
"""

import time

try:
    from micropython import const
except ImportError:  # CPython

    def const(x):
        return x


try:
    from time import sleep_ms, ticks_diff, ticks_ms
except ImportError:  # CPython, for host tests

    def sleep_ms(ms):
        time.sleep(ms / 1000)

    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


# Opcodes
_GET_STATUS = const(0xC0)
_WRITE_REGISTER = const(0x0D)
_READ_REGISTER = const(0x1D)
_WRITE_BUFFER = const(0x0E)
_READ_BUFFER = const(0x1E)
_SET_SLEEP = const(0x84)
_SET_STANDBY = const(0x80)
_SET_TX = const(0x83)
_SET_RX = const(0x82)
_SET_CAD = const(0xC5)
_SET_REGULATOR_MODE = const(0x96)
_CALIBRATE = const(0x89)
_CALIBRATE_IMAGE = const(0x98)
_SET_PA_CONFIG = const(0x95)
_SET_DIO_IRQ_PARAMS = const(0x08)
_GET_IRQ_STATUS = const(0x12)
_CLEAR_IRQ_STATUS = const(0x02)
_SET_DIO2_RF_SWITCH = const(0x9D)
_SET_DIO3_TCXO = const(0x97)
_SET_RF_FREQUENCY = const(0x86)
_SET_PACKET_TYPE = const(0x8A)
_SET_TX_PARAMS = const(0x8E)
_SET_MODULATION_PARAMS = const(0x8B)
_SET_PACKET_PARAMS = const(0x8C)
_SET_CAD_PARAMS = const(0x88)
_SET_BUFFER_BASE = const(0x8F)
_GET_RX_BUFFER_STATUS = const(0x13)
_GET_PACKET_STATUS = const(0x14)
_GET_DEVICE_ERRORS = const(0x17)
_CLEAR_DEVICE_ERRORS = const(0x07)

# Registers
_REG_VERSION = const(0x0320)  # 16 ASCII bytes
_REG_SYNC_WORD = const(0x0740)
_REG_TX_CLAMP = const(0x08D8)

# IRQ bits (get_irq_status)
IRQ_TX_DONE = const(0x0001)
IRQ_RX_DONE = const(0x0002)
IRQ_PREAMBLE = const(0x0004)
IRQ_SYNC_WORD = const(0x0008)
IRQ_HEADER_VALID = const(0x0010)
IRQ_HEADER_ERR = const(0x0020)
IRQ_CRC_ERR = const(0x0040)
IRQ_CAD_DONE = const(0x0080)
IRQ_CAD_DETECTED = const(0x0100)
IRQ_TIMEOUT = const(0x0200)
_IRQ_ALL = const(0x03FF)

MODES = ("unused", "unused", "standby (RC)", "standby (XOSC)", "frequency synthesis", "receive", "transmit", "unused")
ERRORS = {
    0x01: "RC64K calibration",
    0x02: "RC13M calibration",
    0x04: "PLL calibration",
    0x08: "ADC calibration",
    0x10: "image calibration",
    0x20: "crystal (XOSC) start",
    0x40: "PLL lock",
    0x100: "PA ramp",
}
_BANDWIDTHS = {7.8: 0x00, 10.4: 0x08, 15.6: 0x01, 20.8: 0x09, 31.25: 0x02, 41.7: 0x0A, 62.5: 0x03, 125: 0x04, 250: 0x05, 500: 0x06}
_TCXO = (1.6, 1.7, 1.8, 2.2, 2.4, 2.7, 3.0, 3.3)


class SX1262:
    def __init__(self, spi, cs, busy, reset, dio1=None, *, tcxo_volts=1.6, rf_switch=True):
        self._spi = spi
        self._cs = cs
        self._busy = busy
        self._rst = reset
        self._dio1 = dio1
        cs.init(cs.OUT, value=1)
        reset.init(reset.OUT, value=1)
        busy.init(busy.IN)
        if dio1 is not None:
            dio1.init(dio1.IN)
        self._tcxo = tcxo_volts
        self._rf_switch = rf_switch
        self._sf = 7
        self._bw = 125
        self.reset()

    # -- the SPI protocol -------------------------------------------------

    def _wait(self, timeout_ms=1000):
        t0 = ticks_ms()
        while self._busy.value():
            if ticks_diff(ticks_ms(), t0) > timeout_ms:
                raise OSError("SX1262 stays busy")

    def _cmd(self, op, data=b"", nread=0):
        """Send a command; return ``nread`` bytes clocked out after it."""
        self._wait()
        out = bytearray(1 + len(data) + nread)
        out[0] = op
        out[1 : 1 + len(data)] = data
        buf = bytearray(len(out))
        self._cs(0)
        try:
            self._spi.write_readinto(out, buf)
        finally:
            self._cs(1)
        return bytes(buf[1 + len(data) :])

    def read_register(self, addr, n=1):
        # opcode, address, then one status byte before the data
        return self._cmd(_READ_REGISTER, bytes((addr >> 8, addr & 0xFF, 0)), n)

    def write_register(self, addr, data):
        self._cmd(_WRITE_REGISTER, bytes((addr >> 8, addr & 0xFF)) + bytes(data))

    # -- identity and state ------------------------------------------------

    def reset(self):
        """Pulse NRESET, then bring up the clock source, calibrate, and stay
        in standby. Raises ``OSError`` if the chip reports a device error
        (a TCXO setting that doesn't match the module shows as a crystal
        start error)."""
        self._rst(0)
        sleep_ms(2)
        self._rst(1)
        sleep_ms(10)
        self._wait()
        self._cmd(_SET_STANDBY, b"\x00")
        if self._tcxo is not None:
            # 5 ms for the TCXO to settle, in 15.625 us steps
            self._cmd(_SET_DIO3_TCXO, bytes((_TCXO.index(self._tcxo), 0x00, 0x01, 0x40)))
        self._cmd(_CLEAR_DEVICE_ERRORS, b"\x00\x00")
        self._cmd(_CALIBRATE, b"\x7f")
        sleep_ms(5)
        self._wait()
        self._cmd(_SET_REGULATOR_MODE, b"\x01")  # DC-DC
        if self._rf_switch:
            self._cmd(_SET_DIO2_RF_SWITCH, b"\x01")
        errors = self.device_errors
        if errors:
            raise OSError("SX1262 device error: " + ", ".join(errors))

    @property
    def status(self):
        """``(mode, command_status)``: the chip mode as one of ``MODES`` and
        the last command's status code (bits 3-1 of the status byte)."""
        s = self._cmd(_GET_STATUS, b"", 1)[0]
        return MODES[(s >> 4) & 0x07], (s >> 1) & 0x07

    @property
    def version(self):
        """The version string in the chip's ROM, such as ``"SX1261 V2D 2D02"``
        (every SX1262 reports SX1261 here)."""
        raw = self.read_register(_REG_VERSION, 16)
        return raw.split(b"\x00", 1)[0].decode()

    @property
    def device_errors(self):
        """The names of any errors latched since the last reset (``[]`` when
        healthy)."""
        raw = self._cmd(_GET_DEVICE_ERRORS, b"", 3)
        bits = (raw[1] << 8) | raw[2]
        return [name for bit, name in ERRORS.items() if bits & bit]

    def irq_status(self, clear=True):
        raw = self._cmd(_GET_IRQ_STATUS, b"", 3)
        irq = (raw[1] << 8) | raw[2]
        if clear and irq:
            self._cmd(_CLEAR_IRQ_STATUS, bytes((irq >> 8, irq & 0xFF)))
        return irq

    def standby(self):
        self._cmd(_SET_STANDBY, b"\x00")

    def sleep(self, warm=True):
        """Sleep at about 1 uA (warm keeps the configuration; the next
        command wakes the chip, which then needs ``configure()`` again only
        after a cold sleep)."""
        self._cmd(_SET_SLEEP, b"\x04" if warm else b"\x00")
        sleep_ms(1)

    # -- configuration -----------------------------------------------------

    def configure(self, freq_mhz, *, sf=7, bw_khz=125, cr=5, power_dbm=14, preamble=8, sync_word=0x12, crc=True):
        """Set up LoRa: ``sf`` 5-12, ``bw_khz`` one of 7.8 ... 500, coding
        rate 4/``cr`` (5-8), ``power_dbm`` -9 to 22, ``sync_word`` 0x12
        (private networks) or 0x34 (public LoRaWAN)."""
        if not 5 <= sf <= 12:
            raise ValueError("sf is 5-12")
        if bw_khz not in _BANDWIDTHS:
            raise ValueError("bw_khz is one of %s" % sorted(_BANDWIDTHS))
        if not 5 <= cr <= 8:
            raise ValueError("cr is 5-8 (4/5 to 4/8)")
        if not -9 <= power_dbm <= 22:
            raise ValueError("power_dbm is -9 to 22")
        self._sf, self._bw, self._crc = sf, bw_khz, crc
        self._preamble = preamble
        self.standby()
        self._cmd(_SET_PACKET_TYPE, b"\x01")  # LoRa
        f = freq_mhz
        # image calibration for the band the frequency is in (datasheet table 9-2)
        for lo, hi, a, b in ((430, 440, 0x6B, 0x6F), (470, 510, 0x75, 0x81), (779, 787, 0xC1, 0xC5), (863, 870, 0xD7, 0xDB), (902, 928, 0xE1, 0xE9)):
            if lo <= f <= hi:
                self._cmd(_CALIBRATE_IMAGE, bytes((a, b)))
                break
        step = int(f * 1_000_000 * (1 << 25) / 32_000_000)
        self._cmd(_SET_RF_FREQUENCY, step.to_bytes(4, "big"))
        self._cmd(_SET_PA_CONFIG, b"\x04\x07\x00\x01")  # SX1262 high-power PA, up to +22 dBm
        self._cmd(_SET_TX_PARAMS, bytes((power_dbm & 0xFF, 0x04)))  # 200 us ramp
        # TX clamp fix (datasheet 15.2): better tolerance of antenna mismatch
        self.write_register(_REG_TX_CLAMP, bytes((self.read_register(_REG_TX_CLAMP)[0] | 0x1E,)))
        ldro = 1 if (1 << sf) / bw_khz > 16 else 0  # symbols longer than 16 ms
        self._cmd(_SET_MODULATION_PARAMS, bytes((sf, _BANDWIDTHS[bw_khz], cr - 4, ldro)))
        self._packet_params(255)
        self._cmd(_SET_BUFFER_BASE, b"\x00\x00")
        self.write_register(_REG_SYNC_WORD, bytes(((sync_word & 0xF0) | 0x04, ((sync_word & 0x0F) << 4) | 0x04)))
        # every IRQ visible in the status; TX/RX done, timeout and CAD on DIO1
        dio1 = IRQ_TX_DONE | IRQ_RX_DONE | IRQ_TIMEOUT | IRQ_CAD_DONE
        self._cmd(_SET_DIO_IRQ_PARAMS, bytes((_IRQ_ALL >> 8, _IRQ_ALL & 0xFF, dio1 >> 8, dio1 & 0xFF, 0, 0, 0, 0)))
        self.irq_status()

    def _packet_params(self, length):
        p = self._preamble
        self._cmd(_SET_PACKET_PARAMS, bytes((p >> 8, p & 0xFF, 0x00, length, 1 if self._crc else 0, 0x00)))

    def _airtime_ms(self, n):
        # Semtech AN1200.13 time-on-air, explicit header
        sym = (1 << self._sf) / self._bw  # ms
        de = 1 if sym > 16 else 0
        payload = 8 + max(0, -(-(8 * n - 4 * self._sf + 28 + 16 * self._crc) // (4 * (self._sf - 2 * de)))) * 5
        return (self._preamble + 4.25 + payload) * sym

    def _wait_irq(self, mask, timeout_ms):
        t0 = ticks_ms()
        while True:
            if self._dio1 is None or self._dio1.value():
                irq = self.irq_status()
                if irq & mask:
                    return irq
            if ticks_diff(ticks_ms(), t0) > timeout_ms:
                return 0
            sleep_ms(1)

    # -- packets -----------------------------------------------------------

    def send(self, data, timeout_ms=None):
        """Transmit ``data`` (up to 255 bytes) and wait for TX done. Returns
        the measured time on air in ms; raises ``OSError`` on timeout."""
        if not 0 < len(data) <= 255:
            raise ValueError("a LoRa packet is 1-255 bytes")
        self.standby()
        self._packet_params(len(data))
        self._cmd(_WRITE_BUFFER, b"\x00" + bytes(data))
        self.irq_status()
        if timeout_ms is None:
            timeout_ms = int(self._airtime_ms(len(data)) * 2) + 500
        t0 = ticks_ms()
        self._cmd(_SET_TX, b"\x00\x00\x00")  # no chip timeout: we time it here
        irq = self._wait_irq(IRQ_TX_DONE, timeout_ms)
        elapsed = ticks_diff(ticks_ms(), t0)
        if not irq & IRQ_TX_DONE:
            self.standby()
            raise OSError("SX1262 TX did not finish in %d ms" % timeout_ms)
        return elapsed

    def receive(self, timeout_ms=None):
        """Listen for one packet. Returns ``(payload, rssi_dbm, snr_db)``, or
        ``None`` on timeout or a CRC error. ``timeout_ms=None`` waits
        indefinitely."""
        self.standby()
        self._packet_params(255)
        self.irq_status()
        self._cmd(_SET_RX, b"\xff\xff\xff")  # continuous; we stop it
        irq = self._wait_irq(IRQ_RX_DONE, 1 << 30 if timeout_ms is None else timeout_ms)
        self.standby()
        if not irq & IRQ_RX_DONE or irq & (IRQ_CRC_ERR | IRQ_HEADER_ERR):
            return None
        st = self._cmd(_GET_RX_BUFFER_STATUS, b"", 3)
        length, start = st[1], st[2]
        payload = self._cmd(_READ_BUFFER, bytes((start, 0)), length)
        ps = self._cmd(_GET_PACKET_STATUS, b"", 4)
        snr = (ps[2] - 256 if ps[2] > 127 else ps[2]) / 4
        return payload, -ps[1] / 2, snr

    def channel_active(self, symbols=4):
        """Channel activity detection: True if a LoRa preamble is on the air
        at this frequency and spreading factor. Takes a few symbol times."""
        self.standby()
        n = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}[symbols]
        # detection thresholds from Semtech AN1200.48 for SF7-SF12
        peak = 22 + min(max(self._sf - 7, 0), 5)
        self._cmd(_SET_CAD_PARAMS, bytes((n, peak, 10, 0x00, 0, 0, 0)))
        self.irq_status()
        self._cmd(_SET_CAD)
        irq = self._wait_irq(IRQ_CAD_DONE, int(symbols * (1 << self._sf) / self._bw) + 500)
        if not irq & IRQ_CAD_DONE:
            raise OSError("SX1262 CAD did not finish")
        return bool(irq & IRQ_CAD_DETECTED)
