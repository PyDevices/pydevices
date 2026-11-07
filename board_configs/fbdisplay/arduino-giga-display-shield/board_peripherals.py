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

The shield's BMI270 sits on I2C4 at 0x68, beside the touch controller, so
``accelerometer`` and ``gyroscope`` are handed the bus ``board_config``
already opened. ``led`` is the GIGA's green LED and ``boot_button`` its
BOOT0 button, which the board leaves free to read once it has started.
"""
import boarddev
import sys
import time

from audiodev import AudioCapability, AudioFactory, AudioFormat, DACWire, negotiate

PERIPHERALS = frozenset(
    {"wlan", "audio_out", "pcm_out", "accelerometer", "gyroscope", "led", "boot_button"}
)

# What the two boards have that no role covers yet:
#   pcm_in: the jack's microphone ring (A7, PA0) and the shield's MP34DT06J
#     PDM microphone (DFSDM1, clock PD3, data PC1) wait for capture in the
#     firmware's audio driver.
#   ble: the Murata 1DX's Bluetooth waits for a firmware built with it.
#   usb_device: the USB-C port as a MIDI or HID device waits for the
#     firmware's machine.USBDevice.
#   camera: the 20-pin camera connector (DCMI) waits for a camera module in
#     the firmware.
#   can: FDCAN pins only (CANTX PB13, CANRX PB5); a transceiver is not fitted.
#   rtc: only the STM32's own RTC, kept by a battery on the VRTC pin; that's
#     machine.RTC.
#   i2c: no dedicated connector; the header buses are I2C(1) and I2C(2).
#   The shield's RGB LED (IS31FL3197 at 0x50 on I2C4) has no driver yet.

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out"})

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

_BMI270_ADDR = 0x68  # SDO tied to ground on the shield
# The shield's I2C: the same bus as board_config.i2c (port 4, which the touch
# controller uses). Hooks hand drivers that bus object; the port is only
# opened here when board_config isn't loaded. See docs/boards/board-contract.md.
_I2C_PORT = 4
_i2c_own = None
_imu = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def wlan():
    import network

    return network.WLAN(network.STA_IF)


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

        _i2c_own = I2C(_I2C_PORT, freq=400_000)
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


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """The headphone jack's DAC: a raw ``PCMOutput``. Push bytes with ``write()``.

    ``format`` is the write() contract; ``None`` is 22.05 kHz stereo 16-bit.
    ``latency`` and ``queue_ms`` are accepted for the role's call shape; the
    pump's ring is fixed. A caller writing faster than realtime should gate
    on ``space()``: what doesn't fit the stash is dropped rather than
    blocking the interpreter.
    """
    from audiodev import check_latency, pace_output
    from audiodev.pump import PumpPCMOutput

    check_latency(latency)
    wire, _source = negotiate(AUDIO_OUT, format)
    return pace_output(PumpPCMOutput(wire, wire=AUDIO_OUT.wire))


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


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
