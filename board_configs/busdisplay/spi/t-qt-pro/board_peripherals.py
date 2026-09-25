"""Lazy constructors for T-QT Pro non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"battery", "wlan", "ble"})


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def battery():
    from battery_adc import BatteryADC

    return BatteryADC(4, scale=2.0)


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
