"""board_peripherals for the LILYGO T-Watch S3, on CircuitPython.

The same roles as the MicroPython config in busdisplay/spi/t-watch-s3, whose
board_peripherals.py has the rail map and the pin sources. CircuitPython's
board.c switches most of the AXP2101's rails on at boot, but not VBACKUP,
which feeds the PCF8563 clock, and a previous program may have switched any
of them off, so each role here powers its own rail first.

``audio_out()`` is CircuitPython's ``audiobusio.I2SOut`` into the MAX98357A
amplifier, and ``audio_in()`` is ``audiobusio.PDMIn`` on the PDM microphone
(CLK 44, DATA 47): a tone played on the speaker reads about 60 dB above the
room on the microphone.
The chip roles (accelerometer, rtc, haptic, battery) use the same drivers as
MicroPython, over the board I2C, so they answer to the same calls.
"""

import sys

import board
import boarddev

PERIPHERALS = frozenset(
    {
        "audio_out",
        "audio_in",
        "audio_power",
        "accelerometer",
        "rtc",
        "haptic",
        "ir",
        "battery",
        "boot_button",
    }
)

# Audio roles are factories: board_config.audio_out is the callable, so the
# I2S pins are claimed only when an app asks for the player.
FACTORY_ROLES = frozenset({"audio_out", "audio_in", "audio_power"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


_i2c = None
_pmu_obj = None
_accel = None
_rtc = None
_haptic = None


class _I2CMem:
    """machine.I2C's register calls over a busio.I2C, for the drivers written
    for MicroPython (AXP2101, BMA423, PCF8563, DRV2605, FT6x36)."""

    def __init__(self, bus):
        self._bus = bus

    def _lock(self):
        while not self._bus.try_lock():
            pass

    def writeto_mem(self, addr, reg, buf):
        self._lock()
        try:
            self._bus.writeto(addr, bytes([reg]) + bytes(buf))
        finally:
            self._bus.unlock()

    def readfrom_mem(self, addr, reg, n):
        buf = bytearray(n)
        self.readfrom_mem_into(addr, reg, buf)
        return buf

    def readfrom_mem_into(self, addr, reg, buf):
        self._lock()
        try:
            self._bus.writeto_then_readfrom(addr, bytes([reg]), buf)
        finally:
            self._bus.unlock()


def _driver(name):
    """Import one of our drivers from /lib, ahead of a frozen namesake.

    CircuitPython's lilygo_twatch_s3 firmware freezes community libraries
    called ``axp2101`` and ``bma423``, and ``.frozen`` comes before ``/lib``
    on ``sys.path``, so a plain import finds those instead. Ours switch the
    rails this config needs (VBACKUP among them) and answer to the same calls
    as on MicroPython, so /lib goes first for the length of the import.
    """
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "__file__", "").startswith("/lib/"):
        return mod
    sys.modules.pop(name, None)
    sys.path.insert(0, "/lib")
    try:
        return __import__(name)
    finally:
        sys.path.pop(0)


def _bus():
    """The board I2C (SDA 10, SCL 11) as register calls: PMU, BMA423,
    PCF8563 and DRV2605 all sit on it."""
    global _i2c
    if _i2c is None:
        _i2c = _I2CMem(board.I2C())
    return _i2c


def pmu():
    """The AXP2101, once, with its ADC and the clock's supply on. Not a role;
    board_config uses it to power the display, the hooks here their devices."""
    global _pmu_obj
    if _pmu_obj is None:
        _pmu_obj = _driver("axp2101").AXP2101(_bus())
        _pmu_obj.enable_adc()
        _pmu_obj.set_backup_battery(3300)
        # No thermistor on the TS pin (the charger would read a cold battery
        # and never start); LILYGO's currents, cut off at 4.2 V. As on
        # MicroPython, whether the charger is on is left as it is.
        _pmu_obj.set_ts_pin(False)
        _pmu_obj.charger(current_ma=125, precharge_ma=50, termination_ma=25, voltage_mv=4200)
    return _pmu_obj


def battery():
    """The AXP2101: ``voltage`` (volts, ``None`` with no battery), ``percent``
    (``None`` when missing or dead), ``charging``, ``battery_status``,
    ``charge_state``, ``charger(enable)``, ``vbus_voltage``."""
    return pmu()


def accelerometer():
    """BMA423 (or BMA456), ``acceleration`` in g, remapped to the board's axes
    as on MicroPython: face up reads +1 g on Z."""
    global _accel
    if _accel is None:
        pmu()
        _accel = _driver("bma423").BMA423(_bus(), axes=(1, 0, ~2))
    return _accel


def rtc():
    """PCF8563: ``datetime()`` and ``datetime(t)`` in ``machine.RTC``'s
    8-tuple, ``lost_power``."""
    global _rtc
    if _rtc is None:
        from pcf8563 import PCF8563

        pmu()  # VBACKUP feeds the clock
        _rtc = PCF8563(_bus())
    return _rtc


def haptic():
    """DRV2605 vibration motor: ``play(effect, ...)``, ``stop()``."""
    global _haptic
    if _haptic is None:
        import time

        from drv2605 import DRV2605

        pmu().set_rail("bldo2", 3300)  # the DRV2605's EN pin
        time.sleep(0.001)
        _haptic = DRV2605(_bus())
    return _haptic


def ir():
    """The IR LED (GPIO2) as ``pulseio.PulseOut`` with a 38 kHz carrier:
    ``send(array.array('H', [9000, 4500, 560, ...]))`` in microseconds,
    starting with a mark."""
    import pulseio

    return pulseio.PulseOut(board.IR_LED, frequency=38000, duty_cycle=2**15)


def audio_power(enable=True, *, volume=None):
    """Switch the amplifier's rail (DLDO1). The MAX98357A has no volume
    register, so ``volume=`` is accepted and ignored."""
    pmu().set_rail("dldo1", 3300, enable=bool(enable))
    return enable


def audio_out(*args, **kwargs):
    """The MAX98357A as ``audiobusio.I2SOut``, amplifier powered. Arguments
    are accepted and ignored: I2SOut plays whatever format each sample
    carries."""
    import audiobusio

    audio_power(True)
    return audiobusio.I2SOut(board.I2S_BCK, board.I2S_WS, board.I2S_DOUT)


def audio_in(sample_rate=16000):
    """The PDM microphone as ``audiobusio.PDMIn``: ``record(buf, n)`` fills a
    16-bit ``'H'`` array. On this port the samples are signed (read each as
    ``x - 65536 if x & 0x8000 else x``), carry a DC offset that settles over
    the first few hundred milliseconds, and ``record()`` returns a count of
    bytes, not samples."""
    import audiobusio

    return audiobusio.PDMIn(board.MIC_SCLK, board.MIC_DATA, sample_rate=sample_rate, bit_depth=16)


def boot_button():
    """The BOOT button inside the case (GPIO0, ``value`` False when pressed)."""
    import digitalio

    button = digitalio.DigitalInOut(board.BOOT)
    button.switch_to_input(pull=digitalio.Pull.UP)
    return button
