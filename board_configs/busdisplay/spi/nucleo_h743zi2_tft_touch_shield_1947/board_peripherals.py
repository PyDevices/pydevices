# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"led", "sdcard", "ethernet"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def led():
    """Green user LED1."""
    from machine import Pin

    try:
        return Pin("LED1", Pin.OUT, value=0)
    except ValueError:
        return Pin("PB0", Pin.OUT, value=0)


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


def ethernet():
    """Onboard RMII Ethernet (``network.LAN``)."""
    import network

    try:
        return network.LAN()
    except TypeError:
        return network.LAN(0)
