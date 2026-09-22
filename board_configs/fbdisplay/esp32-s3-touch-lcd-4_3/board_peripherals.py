"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "can", "rs485", "usb_device", "wlan", "ble"})

_SD_MOSI = 11
_SD_SCK = 12
_SD_MISO = 13
_SD_CS_EXIO = 4  # CH422G
# CAN rides the ESP32-S3's own USB pins: the FSUSB42UMX (U13) has ESP_USB_N/P
# on its common side and throws them either to the second USB-C connector or to
# the TJA1051, with EXIO5 choosing. So CAN TX/RX are GPIO20/19 -- the D+/D- pair
# -- not a separate pair.
_CAN_TX = 20
_CAN_RX = 19
_CAN_SEL_EXIO = 5  # CH422G: high = CAN mode
# RS485 is the SP3485 (U7) on GPIO15/16. Waveshare's net names are
# transceiver-centric and read backwards from the MCU: RS485_TXD is what the
# transceiver transmits *to* the ESP32, so it is our RX.
_RS485_TX = 16
_RS485_RX = 15


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """TF card SPI; CS on CH422G EXIO4."""
    import board_config as bc
    from machine import Pin, SoftSPI

    from sdcard import SDCard

    cs = bc.io_expander.Pin(_SD_CS_EXIO, Pin.OUT, value=1)
    spi = SoftSPI(
        baudrate=1_000_000,
        sck=Pin(_SD_SCK),
        mosi=Pin(_SD_MOSI),
        miso=Pin(_SD_MISO),
    )
    return SDCard(spi, cs)


def can():
    """TJA1051 on GPIO20/19; EXIO5 selects CAN vs USB.

    Driving EXIO5 high hands the second USB-C connector to the CAN transceiver,
    so the board's native USB goes away for as long as CAN is selected. Do not
    call this on a board being used as a USB host or reached over native USB.
    """
    import board_config as bc
    import canbus

    bc.io_expander.digital_write(_CAN_SEL_EXIO, 1)
    return canbus.open(_CAN_TX, _CAN_RX, baudrate=500_000)


def rs485():
    """SP3485 auto-direction UART (TX=16, RX=15 on this panel family).

    There is no DE pin to pass: the SP3485's DI is tied to ground and our TX
    drives DE/RE through an inverter, so the transceiver keys itself. Because
    RE is strapped to DE it stops receiving while it transmits, which means a
    loopback test sees no echo of what it just sent -- that is the circuit, not
    a fault.
    """
    from rs485 import RS485

    return RS485(1, tx=_RS485_TX, rx=_RS485_RX, baudrate=115200)


def usb_device():
    from machine import USBDevice

    return USBDevice()


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
