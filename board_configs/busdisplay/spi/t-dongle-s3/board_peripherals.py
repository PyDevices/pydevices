"""Lazy constructors for T-Dongle-S3 non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"pixels", "wlan", "ble"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def pixels():
    """APA102 (DotStar) on LilyGO T-Dongle-S3 (CLK=39, DATA=40)."""
    from machine import Pin, SoftSPI

    from dotstar import DotStar

    spi = SoftSPI(baudrate=1_000_000, sck=Pin(39), mosi=Pin(40), miso=Pin(38))
    return DotStar(spi, 1, auto_write=True)


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
