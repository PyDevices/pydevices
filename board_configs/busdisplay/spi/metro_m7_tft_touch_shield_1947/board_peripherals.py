# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"pixels", "led", "sdcard", "radio", "wlan", "i2c"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def pixels():
    """Onboard NeoPixel (``NEOPIXEL`` / GPIO_00)."""
    from machine import Pin
    from neopixel import NeoPixel

    return NeoPixel(Pin("NEOPIXEL"), 1)


def led():
    """User LED (``LED`` / D13)."""
    from machine import Pin

    try:
        return Pin("LED", Pin.OUT, value=0)
    except ValueError:
        return Pin("D13", Pin.OUT, value=0)


def sdcard():
    """Shield microSD on D11–D13, CS=D4 (``sdcard.py``)."""
    from machine import Pin, SoftSPI

    from sdcard import SDCard

    spi = SoftSPI(
        baudrate=1_000_000,
        sck=Pin("D13"),
        mosi=Pin("D11"),
        miso=Pin("D12"),
    )
    return SDCard(spi, Pin("D4", Pin.OUT, value=1))


def radio():
    """AirLift ESP32 (nina-fw) co-processor NIC."""
    return wlan()


def wlan():
    """AirLift / NINA station interface (board firmware default NIC)."""
    import network

    return network.WLAN(network.STA_IF)


def i2c():
    """Shield / STEMMA I2C — re-export UI bus when already constructed."""
    import board_config as bc

    return bc.i2c
