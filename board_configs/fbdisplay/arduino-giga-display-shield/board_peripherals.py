# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for the Arduino GIGA R1 WiFi with the GIGA Display Shield. PERIPHERALS = lazy roles only.

Audio is the headphone jack, which the STM32H747's DAC drives directly:
left on PA5 (DAC1, A13), right on PA4 (DAC0, A12), as Arduino's schematic
wires them. The firmware's ``audioio.AudioOut``
plays it, with the audio pump under it. ``audio_out`` is a sample player
over it and ``pcm_out`` takes raw PCM; both reach the same DAC, and
anything playing on both at once is summed. The DAC has 12 bits, so each
16-bit sample loses its low four, and there is no codec, so volume is
scaled in software.

``pcm_in`` records from either of the board's two microphones, mono
16-bit. By default it's the Display Shield's MP34DT06J, a PDM microphone
the STM32H747's DFSDM decimates in hardware; ``pcm_in(mic="jack")`` is a
headset's microphone in the jack instead, on the ring the board wires to
A7 (PA0) and sampled by the ADC. Neither shares a clock with the DAC, so
either records while ``audio_out`` plays. One records at a time.

The shield's BMI270 sits on I2C4 at 0x68, beside the touch controller, so
``accelerometer`` and ``gyroscope`` are handed the bus ``board_config``
already opened. ``led`` is the GIGA's green LED and ``boot_button`` its
BOOT0 button, which the board leaves free to read once it has started.

The USB-C port has no host side, so it's free to be a device: ``usb_midi``
makes the board a MIDI port the computer plays, beside the REPL's serial port.

``ble`` is Bluetooth LE through the GIGA's Murata 1DX, on firmware built with
Bluetooth, as a bledev adapter when bledev and aioble are installed.
"""
import boarddev
import sys
import time

from audiodev import (
    AnalogWire,
    AudioCapability,
    AudioFactory,
    AudioFormat,
    DACWire,
    PDMWire,
    negotiate,
)

PERIPHERALS = frozenset(
    {
        "wlan",
        "ble",
        "audio_out",
        "pcm_out",
        "pcm_in",
        "accelerometer",
        "gyroscope",
        "led",
        "boot_button",
        "usb_device",
        "usb_midi",
    }
)

# What the two boards have that no role covers yet:
#   camera: the 20-pin camera connector (DCMI) waits for a camera module in
#     the firmware.
#   can: FDCAN pins only (CANTX PB13, CANRX PB5); a transceiver is not fitted.
#   rtc: only the STM32's own RTC, kept by a battery on the VRTC pin; that's
#     machine.RTC.
#   i2c: no dedicated connector; the header buses are I2C(1) and I2C(2).
#   The shield's RGB LED (IS31FL3197 at 0x50 on I2C4) has no driver yet.

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in"})

# TIM6 paces the DAC from the timer clock, so any rate opens. Both channels
# are wired to the jack; a mono stream plays on both.
AUDIO_OUT = AudioCapability(
    AudioFormat(22050, 2, 16),
    rates=None,
    channels=(1, 2),
    native_channels=2,
    bits=(16,),
    wire=DACWire("PA5", "PA4"),
)

# The shield's microphone: DFSDM1 clocks it from PD3 and reads PC1. Its
# divider lands exactly on these rates from the 120 MHz APB2 clock; others
# would run a fraction of a percent off.
AUDIO_IN = AudioCapability(
    AudioFormat(16000, 1, 16),
    rates=(8000, 16000, 24000, 32000, 48000),
    channels=(1,),
    native_channels=1,
    bits=(16,),
    wire=PDMWire("PD3", "PC1"),
)

# The jack's microphone ring, on A7 (PA0): ADC1, triggered by TIM15.
AUDIO_IN_JACK = AudioCapability(
    AudioFormat(16000, 1, 16),
    rates=None,
    channels=(1,),
    native_channels=1,
    bits=(16,),
    wire=AnalogWire("PA0"),
)

# What each input's samples are raised by, in dB, before the gain a caller
# sets: enough that speech at arm's length reads well above the noise.
_MIC_GAIN_DB = {"shield": 24, "jack": 0}

_BMI270_ADDR = 0x68  # SDO tied to ground on the shield
# The shield's I2C: the same bus as board_config.i2c (port 4, which the touch
# controller uses). Hooks hand drivers that bus object; the port is only
# opened here when board_config isn't loaded. See docs/boards/board-contract.md.
_I2C_PORT = 4
# 400 kHz Fast mode for an I2C kernel clock of 120 MHz (APB4). The stm32
# port's I2C(freq=400_000) writes a value worked out for 54 MHz, which runs
# this bus near 1 MHz (micropython-pydevices#278). With PRESC=2 a tick is
# 25 ns: SCLL=59 holds SCL low 1.5 us (Fast mode needs 1.3), SCLH=33 high
# 0.85 us (needs 0.6), SCLDEL=15 gives 400 ns of data setup, SDADEL=2 50 ns
# of hold. The period is 2.35 us plus the rise, fall and sync delays.
I2C_TIMINGR = 0x20F2213B
_i2c_own = None
_imu = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/guides/bluetooth-le.md) over the Murata 1DX's
    # Bluetooth LE. It also answers every bluetooth.BLE method, so code written
    # for the raw radio keeps working. Without bledev (or aioble) installed,
    # the raw radio.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()


def _i2c_bus():
    """I2C4, shared with whatever already opened it.

    Never ``import board_config`` from here: a program that wants only the IMU
    must not start the display. Without board_config, open the port once and
    hand out the same object after, never a second controller on these pins.
    """
    global _i2c_own

    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    if _i2c_own is None:
        from machine import I2C

        _i2c_own = I2C(_I2C_PORT, timingr=I2C_TIMINGR)
    return _i2c_own


def _bmi270():
    global _imu
    if _imu is None:
        from bmi270 import BMI270

        _imu = BMI270(_i2c_bus(), address=_BMI270_ADDR)
        # The gyroscope takes about 45 ms to start once the configuration
        # loads; reading before then returns zeros.
        time.sleep_ms(50)
    return _imu


def accelerometer():
    """The shield's BMI270: ``accel()`` in g (same object as ``gyroscope``)."""
    return _bmi270()


def gyroscope():
    """The shield's BMI270: ``gyro()`` in degrees per second (same object as
    ``accelerometer``)."""
    return _bmi270()


def led():
    """The GIGA's green LED (PJ13), as a ``machine.Signal``: ``on()`` lights it.

    It's one of the three in the board's RGB LED, wired active low; red is
    ``Pin("LED_RED")`` and blue ``Pin("LED_BLUE")``.
    """
    from machine import Pin, Signal

    return Signal(Pin("LED_GREEN", Pin.OUT, value=1), invert=True)


def boot_button():
    """The BOOT0 button, read on PC13: ``value()`` is 1 while it's pressed.

    Held through a reset, it starts the STM32's own bootloader instead.
    """
    from machine import Pin

    return Pin("PC13", Pin.IN, Pin.PULL_DOWN)


def usb_device():
    """The USB-C port's ``machine.USBDevice``, for interfaces beyond the REPL's."""
    from machine import USBDevice

    return USBDevice()


def usb_midi():
    """The USB-C port as a MIDI device: ``(midi_in, midi_out)``.

    The board re-enumerates on the computer as a MIDI port and keeps its
    serial port, which may come back under a new name. Needs midiports and
    micropython-lib's ``usb-device-midi``.
    """
    from midiports import usb_device

    return usb_device.ports()


# How much the DAC's ring holds for latency="buffered", in milliseconds. The
# default, about 93 ms, suits an instrument; a player can ride out longer
# stalls of the interpreter (a garbage collection over a screen redraw).
BUFFERED_MS = 250


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """The headphone jack's DAC: a raw ``PCMOutput``. Push bytes with ``write()``.

    ``format`` is the write() contract; ``None`` is 22.05 kHz stereo 16-bit.
    The DAC's ring holds about 93 ms. ``queue_ms`` asks for another length,
    and ``latency="buffered"`` for `BUFFERED_MS`. A caller writing faster than
    realtime should gate on ``space()``: what doesn't fit the stash is
    dropped rather than blocking the interpreter.
    """
    from audiodev import check_latency, pace_output
    from audiodev.pump import PumpPCMOutput

    check_latency(latency)
    if queue_ms is None and latency == "buffered":
        queue_ms = BUFFERED_MS
    wire, _source = negotiate(AUDIO_OUT, format)
    return pace_output(PumpPCMOutput(wire, wire=AUDIO_OUT.wire, buffer_ms=queue_ms))


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over the DAC: ``play(sample, loop=)``,
    ``stop()``, ``pause()``, ``resume()`` and ``playing`` over any audiosample.
    """
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _pcm_in(format=None, *, mic="shield", latency=None, queue_ms=None):
    """A microphone: a raw ``PCMInput``, mono 16-bit. ``readinto()`` fills a buffer.

    ``mic="shield"`` (the default) is the Display Shield's PDM microphone,
    at 8, 16, 24, 32 or 48 kHz; ``mic="jack"`` is a headset's microphone in
    the jack, at any rate. ``None`` is 16 kHz. The firmware keeps about a
    quarter of a second at 16 kHz, so a reader may fall that far behind
    before ``stats()["dropped"]`` counts what it lost. ``set_gain()``
    lowers the level in software from where the board sets it.
    """
    from audiodev import check_latency
    from audiodev.pump import PumpPCMInput, driver

    check_latency(latency)
    if mic not in _MIC_GAIN_DB:
        raise ValueError('mic is "shield" or "jack"')
    capability = AUDIO_IN if mic == "shield" else AUDIO_IN_JACK
    wire, source = negotiate(capability, format)
    if source is not wire:
        raise ValueError("this board records one channel")

    def before_open():
        mod = driver()
        if mod is not None and hasattr(mod, "rx_gain"):
            mod.rx_gain(_MIC_GAIN_DB[mic])

    return PumpPCMInput(wire, wire=capability.wire, before_open=before_open)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
