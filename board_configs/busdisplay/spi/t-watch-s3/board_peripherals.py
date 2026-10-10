"""Lazy constructors for the LILYGO T-Watch S3. PERIPHERALS = lazy roles only.

Every peripheral on this watch sits behind a rail of its AXP2101 power chip,
so each hook here switches its rail on before it builds the device:

    ALDO2  display backlight      ALDO3  display and touch
    ALDO4  LoRa radio             BLDO2  DRV2605 enable pin
    DLDO1  MAX98357A amplifier    VBACKUP  PCF8563 clock and its coin cell

(LILYGO's schematic T_WATCH-S3 25-03-24 and LilyGoLib's LilyGoWatchS3.cpp.)
The clock in particular does not answer on I2C until VBACKUP is on.

Pins are LILYGO's (TTGO_TWatch_Library, branch t-watch-s3, src/utilities.h),
and agree with CircuitPython's lilygo_twatch_s3 board definition:

    I2C (PMU, BMA423, PCF8563, DRV2605)  SDA 10, SCL 11
    MAX98357A                            BCLK 48, WS 15, DOUT 46
    PDM microphone                       CLK 44, DATA 47
    IR LED                               GPIO2
    SX1262 LoRa radio                    SCK 3, MOSI 1, MISO 4, CS 5, RESET 8,
                                         BUSY 7, DIO1 9
    interrupts                           PMU 21, RTC 17, BMA423 14, touch 16

``pcm_in`` needs firmware whose ``machine.I2S`` has PDM receive
(``I2S.PDM_RX``, in PyDevices' MicroPython builds), on I2S0, so the speaker
is on I2S1 and the two can run at once.

The battery charger is the AXP2101's own. There is no thermistor on this
watch, so ``pmu()`` turns the TS pin's temperature sensing off (as LILYGO's
firmware does; otherwise the charger never starts) and sets 125 mA charging
to 4.2 V, safe for any healthy single Li-ion cell. ``battery.charger(False)``
stops charging; ``battery.charger(True)`` starts it again.

``sleep()`` puts the watch into light or deep sleep until a wake source
fires: the crown, a touch, a wrist tilt or double tap (the BMA423's feature
engine, see ``accelerometer``), or the clock's alarm or countdown.
"""

import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "audio_power",
        "accelerometer",
        "rtc",
        "haptic",
        "ir",
        "lora",
        "pcm_in",
        "sleep",
        "battery",
        "boot_button",
        "wlan",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power", "sleep"})

from audiodev import AudioCapability, AudioFactory, AudioFormat, I2SWire, adapt_channels, negotiate
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

# Main I2C, shared with board_config (port 0). Hooks hand drivers the one bus
# object _i2c_bus() returns, never these pins. See docs/board-peripherals.md.
_I2C_PORT = 0
_I2C_SDA = 10
_I2C_SCL = 11
_IIS_BCLK = 48
_IIS_WS = 15
_IIS_DOUT = 46
_MIC_CLK = 44
_MIC_DATA = 47
_IR_PIN = 2
_IR_CARRIER = 38_000
_PMU_INT = 21
_RTC_INT = 17
_ACCEL_INT = 14
_TOUCH_INT = 16

# The microphone needs I2S0 (only it has the PDM-to-PCM filter), so the
# speaker takes I2S1.
_OUT_PORT = 1
_IN_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

_i2c_own = None
_pmu_obj = None
_accel = None
_rtc = None
_haptic = None
_lora = None

# --- what this board can actually do --------------------------------------
#
# A MAX98357A is an amplifier, not a codec: no I2C and no registers, and it
# clocks from BCLK, so the rate is whatever the I2S peripheral is asked for.
# Measured on this watch: 16000, 22050 and 44100 Hz each played out in real
# time (a known number of frames took its own duration through the paced
# write path). SD_MODE is pulled to the supply through 1 Mohm (schematic), so
# the amp plays (left + right) / 2 into its one speaker.
_OUT_DEFAULT = AudioFormat(16000, 2, 16)
AUDIO_OUT = AudioCapability(
    _OUT_DEFAULT,
    rates=None,
    channels=(1, 2),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(_OUT_PORT, sck=_IIS_BCLK, ws=_IIS_WS, sd=_IIS_DOUT),
)


# The PDM microphone, through I2S0's hardware PDM-to-PCM filter. Measured on
# this watch: 16000 Hz mono 16-bit, a 1 kHz tone from the watch's own speaker
# well above the room (see pcm_in). The filter has no gain control and leaves
# a DC offset of about -1550 (-26 dBFS) with the room at about -66 dBFS, so
# pcm_in removes the offset and adds gain in software: up to MIC_MAX_GAIN_DB,
# MIC_DEFAULT_GAIN percent of it to start.
MIC_MAX_GAIN_DB = 36
MIC_DEFAULT_GAIN = 83  # percent of MIC_MAX_GAIN_DB: about +30 dB
_IN_DEFAULT = AudioFormat(16000, 1, 16)
AUDIO_IN = AudioCapability(
    _IN_DEFAULT,
    rates=(16000,),
    channels=(1,),
    native_channels=1,
    bits=(16,),
)


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _i2c_bus():
    """The main I2C bus, shared with whatever already opened it.

    Never ``import board_config`` from here: a non-graphics app importing
    this module must not start the display. Without board_config, open that
    port once and hand out the same object after.
    """
    global _i2c_own

    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=400_000)
    return _i2c_own


def pmu():
    """The AXP2101, constructed once, with its ADC and the clock's supply on.

    Not a role (no app needs the chip itself), but board_config uses it to
    power the display, and every hook here uses it to power its device.
    """
    global _pmu_obj
    if _pmu_obj is None:
        from axp2101 import AXP2101

        _pmu_obj = AXP2101(_i2c_bus())
        _pmu_obj.enable_adc()
        _pmu_obj.set_backup_battery(3300)
        # No thermistor on the TS pin: without this the charger reads a cold
        # battery and never starts. Then LILYGO's currents, cut off at 4.2 V.
        # Whether the charger is on is left as it is (the chip powers up
        # with it on).
        _pmu_obj.set_ts_pin(False)
        _pmu_obj.charger(current_ma=125, precharge_ma=50, termination_ma=25, voltage_mv=4200)
    return _pmu_obj


def battery():
    """The AXP2101 itself: ``voltage`` (volts, ``None`` with no battery),
    ``percent`` (``None`` when missing or dead), ``charging``,
    ``battery_status`` ("missing", "dead", "charging", "full",
    "discharging"), ``charge_state``, ``charger(enable)``, ``vbus_voltage``,
    ``die_temperature``."""
    return pmu()


def accelerometer():
    """BMA423 (or BMA456 on later watches), ``acceleration`` in g.

    The chip sits on the underside of the board, so its axes are remapped:
    LILYGO's library selects Bosch's "bottom layer, top right corner" remap
    (register value 0x81 in SensorLib v0.2.6), which is board X = chip Y,
    board Y = chip X, board Z = -chip Z. Face up on a table reads +1 g on Z.

    For the step counter, wrist tilt and double tap, load the chip's
    feature firmware first (BMA423 only; about 200 ms)::

        from bma423 import STEP_COUNTER, WRIST_WEAR, DOUBLE_TAP
        accel.load_features()
        accel.enable_features(STEP_COUNTER | WRIST_WEAR | DOUBLE_TAP)
        accel.steps

    The firmware stays loaded while the watch has power, across resets
    and deep sleep; ``sleep(wake=("motion",))`` wakes on its interrupt.
    """
    global _accel
    if _accel is None:
        from bma423 import BMA423

        pmu()
        _accel = BMA423(_i2c_bus(), axes=(1, 0, ~2))
    return _accel


def rtc():
    """PCF8563: ``datetime()`` and ``datetime(t)`` as ``machine.RTC``,
    ``lost_power``."""
    global _rtc
    if _rtc is None:
        from pcf8563 import PCF8563

        pmu()  # VBACKUP feeds the clock
        _rtc = PCF8563(_i2c_bus())
    return _rtc


def haptic():
    """DRV2605 vibration motor: ``play(effect, ...)``, ``stop()``."""
    global _haptic
    if _haptic is None:
        import time

        from drv2605 import DRV2605

        pmu().set_rail("bldo2", 3300)  # the DRV2605's EN pin
        time.sleep_ms(1)
        _haptic = DRV2605(_i2c_bus())
    return _haptic


def ir():
    """The IR LED as an ``esp32.RMT`` channel with a 38 kHz carrier and 1 us
    ticks: ``write_pulses((9000, 4500, 560, 560, ...), True)`` sends marks and
    spaces in microseconds, starting with a mark."""
    import esp32
    from machine import Pin

    return esp32.RMT(0, pin=Pin(_IR_PIN), resolution_hz=1_000_000, tx_carrier=(_IR_CARRIER, 33, 1))


def lora():
    """The SX1262 LoRa radio (``sx1262.SX1262``), powered from ALDO4, reset
    and in standby. ``configure(freq_mhz, ...)`` before ``send()`` or
    ``receive()``; use a frequency your region allows."""
    global _lora
    if _lora is None:
        import time

        from machine import SPI, Pin
        from sx1262 import SX1262

        pmu().set_rail("aldo4", 3300)
        time.sleep_ms(5)
        spi = SPI(1, baudrate=8_000_000, sck=Pin(3), mosi=Pin(1), miso=Pin(4))
        _lora = SX1262(spi, cs=Pin(5), busy=Pin(7), reset=Pin(8), dio1=Pin(9))
    return _lora


WAKE_SOURCES = ("crown", "touch", "motion", "rtc")


def _sleep(ms=None, *, deep=False, wake=("crown",)):
    """Sleep until ``ms`` pass or one of ``wake`` fires; ``wake`` names come
    from ``WAKE_SOURCES``:

    * ``"crown"``: a press of the crown (the PMU's IRQ line; this routes only
      key events to it)
    * ``"touch"``: a finger on the screen (the FT6336's INT line)
    * ``"motion"``: the BMA423's INT1, after ``accelerometer.load_features()``
      and ``map_interrupts()`` for the gestures wanted
    * ``"rtc"``: the PCF8563's alarm or countdown, set on ``rtc`` first

    Light sleep (the default) returns the source that woke it, or
    ``"timer"``. Deep sleep restarts the watch on wake, so it never returns;
    ``machine.reset_cause()`` and ``wake_reason()`` say why it woke. The
    screen and backlight stay as they are: turn them off first to save power.
    """
    import esp32
    import machine
    from machine import Pin

    for name in wake:
        if name not in WAKE_SOURCES:
            raise ValueError("wake sources are %s" % (WAKE_SOURCES,))
    # Every wake line is active low: the PMU's IRQ, the touch and clock
    # interrupts (open drain), and the BMA423's INT1, set low-active here.
    lines = {"crown": _PMU_INT, "touch": _TOUCH_INT, "rtc": _RTC_INT, "motion": _ACCEL_INT}
    if "crown" in wake:
        pmu().irq_pin_only()
    if "motion" in wake:
        a = accelerometer()
        a.set_interrupt_pin(active_high=False)
        a.interrupt_status()  # release a latched INT1 first
    # A sleep leaves the pads held; hold=False lets them go, or a line keeps
    # its old level.
    nums = [lines[n] for n in WAKE_SOURCES if n in wake]
    pins = [Pin(n, Pin.IN, Pin.PULL_UP, hold=False) for n in nums]
    # Clear what an earlier call set (an empty tuple clears; None keeps).
    esp32.wake_on_gpio(pins=(), level=False)
    esp32.wake_on_ext0(pin=None, level=esp32.WAKEUP_ALL_LOW)
    esp32.wake_on_ext1(pins=(), level=esp32.WAKEUP_ALL_LOW)
    if deep:
        # Deep sleep wakes through the RTC controller: ext0 on the first line
        # (which also keeps the RTC pads powered, so their pull-ups hold) and
        # ext1 on the rest. The PMU's IRQ has no pull-up of its own and the
        # chip leaves GPIO21's RTC pull-down on, so set each pad's pull-up.
        for n in nums:
            reg = _RTC_PAD_REG[n]
            machine.mem32[reg] = (machine.mem32[reg] | (1 << 27)) & ~(1 << 28)
        if pins:
            esp32.wake_on_ext0(pin=pins[0], level=esp32.WAKEUP_ALL_LOW)
        if len(pins) > 1:
            esp32.wake_on_ext1(pins=tuple(pins[1:]), level=esp32.WAKEUP_ALL_LOW)
        machine.deepsleep(ms) if ms else machine.deepsleep()
    # Light sleep wakes on the GPIOs themselves, which keep their pull-ups.
    if pins:
        esp32.wake_on_gpio(pins=tuple(pins), level=False)
    machine.lightsleep(ms) if ms else machine.lightsleep()
    esp32.wake_on_gpio(pins=(), level=False)
    if machine.wake_reason() == machine.TIMER_WAKE:
        return "timer"
    # Crown, clock and gesture lines stay low until read; a finger may
    # already have lifted, so touch is what's left.
    for name in ("crown", "rtc", "motion", "touch"):
        if name in wake and not Pin(lines[name], Pin.IN, Pin.PULL_UP, hold=False).value():
            return name
    return "touch" if "touch" in wake else "unknown"


# RTC_IO pad registers on the ESP32-S3 (ESP-IDF soc/esp32s3 rtc_io_reg.h):
# bit 27 is the pad's pull-up in deep sleep, bit 28 its pull-down.
_RTC_PAD_REG = {14: 0x600084BC, 16: 0x600084C4, 17: 0x600084C8, 21: 0x600084D8}


sleep = _sleep


def _audio_power(enable=True, *, volume=None):
    """Switch the amplifier's rail (DLDO1) without opening an I2S stream.

    A MAX98357A has no volume register, so ``volume=`` is accepted and
    ignored: the loudness lives in the material. Unlike a board where one
    rail feeds everything, this rail feeds only the amplifier, so
    ``enable=False`` really does turn it off.
    """
    pmu().set_rail("dldo1", 3300, enable=bool(enable))
    return enable


def _out_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _OUT_PORT,
        sck=Pin(_IIS_BCLK),
        ws=Pin(_IIS_WS),
        sd=Pin(_IIS_DOUT),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """MAX98357A I2S amplifier: a raw, paced ``PCMOutput``. Push bytes with
    ``write()``; gate on ``space()`` when writing faster than realtime."""
    from audiodev import check_latency, pace_output, queue_bytes

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    _audio_power(True)
    device = I2SPCMOutput(
        lambda: _out_stream(ibuf, wire),
        wire,
        # For a consumer that drives the peripheral in C (the audio pump):
        # the pin map, and a way to bring the amplifier up without a stream.
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over the amplifier. Requires audiodsp; use
    ``pcm_out`` for raw PCM bytes, which has no DSP dependency."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _in_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _IN_PORT,
        sck=Pin(_MIC_CLK),
        sd=Pin(_MIC_DATA),
        mode=I2S.PDM_RX,
        bits=fmt.bits,
        format=I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _mic_filter():
    """A viper function that removes DC and rumble (a one-pole high-pass,
    pole 1 - 2**-shift: shift 5 is about 80 Hz at 16 kHz) and applies gain,
    in place, on 16-bit samples. ``state`` carries the filter across calls;
    ``gain`` is in 1/16ths."""
    import micropython

    @micropython.viper
    def run(buf, n: int, gain: int, state, shift: int) -> int:
        p = ptr16(buf)
        st = ptr32(state)
        x1 = st[0]
        y1 = st[1]  # 1/256ths
        for i in range(n):
            x = p[i]
            if x > 32767:
                x -= 65536
            y = ((x - x1) << 8) + y1 - (y1 >> shift)
            x1 = x
            y1 = y
            o = ((y >> 8) * gain) >> 4
            if o > 32767:
                o = 32767
            elif o < -32768:
                o = -32768
            p[i] = o & 0xFFFF
        st[0] = x1
        st[1] = y1
        return n

    return run


class _PDMInput(I2SPCMInput):
    """The microphone, with its DC offset removed and gain applied: what
    ``set_gain()`` sets here is a real gain, 0-100 % of ``MIC_MAX_GAIN_DB``."""

    def __init__(self, i2s, fmt):
        super().__init__(i2s, fmt, set_hardware_gain=self._apply_gain)
        from array import array

        self._run = _mic_filter()
        self._state = array("i", (0, 0))
        self._gain16 = 16
        self.highpass_shift = 5
        self.set_gain(MIC_DEFAULT_GAIN)

    def _apply_gain(self, percent):
        self._gain16 = int(16 * 10 ** (MIC_MAX_GAIN_DB * percent / 100 / 20) + 0.5)

    def _readinto(self, buf):
        n = super()._readinto(buf)
        if n:
            self._run(buf, n // 2, self._gain16, self._state, self.highpass_shift)
        return n

    async def _areadinto(self, buf):
        n = await super()._areadinto(buf)
        if n:
            self._run(buf, n // 2, self._gain16, self._state, self.highpass_shift)
        return n


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """The PDM microphone: a ``PCMInput`` of 16-bit mono with its DC offset
    removed and gain applied (``set_gain(percent)``; about +30 dB to start).
    Needs firmware with ``I2S.PDM_RX``."""
    from machine import I2S

    from audiodev import check_latency, queue_bytes

    if not hasattr(I2S, "PDM_RX"):
        raise OSError("this firmware's machine.I2S has no PDM_RX: the microphone needs a PyDevices build")
    check_latency(latency)
    wire, source = negotiate(AUDIO_IN, format)
    if source is not wire:
        raise ValueError("this watch captures %s; capture cannot be converted" % (wire,))
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    return _PDMInput(lambda: _in_stream(ibuf, wire), wire)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


def boot_button():
    """The BOOT button inside the case (GPIO0, ``value()`` 0 when pressed)."""
    from machine import Pin

    return Pin(0, Pin.IN, Pin.PULL_UP)


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/bledev.md). It also answers every bluetooth.BLE
    # method, so code written for the raw radio keeps working. Without bledev
    # (or aioble) installed, the raw radio, as before.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
