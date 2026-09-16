"""Lazy constructors for PyPortal non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"sdcard", "radio", "audio_out", "i2c", "wlan"})

# A PWM buzzer, not a PCM path: no sample rate, no channels, nothing to
# configure. kind="tone" says so, and negotiate() refuses a format here
# rather than accepting one and quietly ignoring it. audio_out stays a
# zero-argument role -- there is no format to pass, so it is not a factory.
AUDIO_OUT = AudioCapability(None, kind="tone")

from audiodev import AudioCapability
from audiodev.pwm_tone import PWMToneOutput


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def sdcard():
    """microSD on SPI (CS=PB30 when named; else pin 30)."""
    from machine import Pin, SoftSPI

    from sdcard import SDCard

    try:
        cs = Pin("SD_CS", Pin.OUT, value=1)
    except ValueError:
        cs = Pin(30, Pin.OUT, value=1)
    spi = SoftSPI(
        baudrate=1_000_000,
        sck=Pin(13),
        mosi=Pin(12),
        miso=Pin(14),
    )
    return SDCard(spi, cs)


def radio():
    """ESP32 AirLift co-processor — same NIC as ``wlan`` when nina-fw is linked."""
    return wlan()


def audio_out():
    from machine import Pin, PWM

    try:
        enable = Pin("SPEAKER_ENABLE", Pin.OUT, value=0)
        speaker = Pin("SPEAKER")
    except ValueError:
        enable = None
        speaker = Pin(2)
    power = None if enable is None else lambda value: enable.value(value)
    return PWMToneOutput(lambda: PWM(speaker, freq=440, duty=0), power=power)


def i2c():
    """STEMMA / touch I2C — re-export UI-shared bus."""
    import board_config as bc

    return bc.i2c


def wlan():
    """AirLift / board default station interface."""
    import network

    return network.WLAN(network.STA_IF)
