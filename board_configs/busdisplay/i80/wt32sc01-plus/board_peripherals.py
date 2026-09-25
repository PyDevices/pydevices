"""Lazy constructors for WT32-SC01 Plus non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "wlan", "ble"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """SPI microSD when present (CS=GPIO41 common on WT32-SC01 Plus)."""
    from machine import Pin, SoftSPI

    from sdcard import SDCard

    spi = SoftSPI(baudrate=1_000_000, sck=Pin(12), mosi=Pin(11), miso=Pin(13))
    return SDCard(spi, Pin(41, Pin.OUT, value=1))


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
