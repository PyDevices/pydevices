"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "battery", "wlan", "ble"})

# LilyGO utilities.h
_SDMMC_EN = 7  # XL9535
_SDMMC_SCK = 39
_SDMMC_CMD = 40
_SDMMC_DAT = 38
_ADC_DET = 4


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """TF via SDMMC 1-bit; power enable on XL9535 IO7."""
    import board_config as bc
    from machine import SDCard

    bc.xl.digitalWrite(_SDMMC_EN, 1)
    try:
        return SDCard(
            slot=1,
            width=1,
            sck=_SDMMC_SCK,
            cmd=_SDMMC_CMD,
            data=(_SDMMC_DAT,),
        )
    except TypeError:
        # Fallback SPI naming on some ports
        return SDCard(
            slot=2,
            sck=_SDMMC_SCK,
            mosi=_SDMMC_CMD,
            miso=_SDMMC_DAT,
            cs=_SDMMC_DAT,
        )


def battery():
    from battery_adc import BatteryADC

    return BatteryADC(_ADC_DET, scale=2.0)


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
