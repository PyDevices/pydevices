"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "i2c", "wlan", "ble"})

# LilyGO examples/factory/pins.h
_SD_SCLK = 12
_SD_CMD = 11
_SD_DAT0 = 13


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """T-HMI TF via SDMMC 1-bit (SCLK/CMD/DAT0)."""
    from machine import SDCard

    try:
        return SDCard(slot=1, width=1, sck=_SD_SCLK, cmd=_SD_CMD, data=(_SD_DAT0,))
    except TypeError:
        return SDCard(slot=1)


def i2c():
    """Expansion I2C on free GPIOs (no onboard STEMMA; apps may remux)."""
    from machine import I2C, Pin

    return I2C(0, sda=Pin(17), scl=Pin(18), freq=400_000)


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/ble.md §2). It also answers every bluetooth.BLE
    # method, so code written for the raw radio keeps working. Without bledev
    # (or aioble) installed, the raw radio, as before.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()
