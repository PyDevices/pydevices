"""Lazy constructors for FunHouse non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"temperature", "humidity", "pressure", "pixels", "audio_out", "wlan"})

# A PWM buzzer, not a PCM path: no sample rate, no channels, nothing to
# configure. kind="tone" says so, and negotiate() refuses a format here
# rather than accepting one and quietly ignoring it. audio_out stays a
# zero-argument role -- there is no format to pass, so it is not a factory.
AUDIO_OUT = AudioCapability(None, kind="tone")

from audiodev import AudioCapability
from audiodev.pwm_tone import PWMToneOutput

_aht = None
_bmp = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _aht20():
    global _aht
    if _aht is not None:
        return _aht
    import board_config as bc
    from ahtx0 import AHT20

    _aht = AHT20(bc.i2c)
    return _aht


def _bmp280():
    global _bmp
    if _bmp is not None:
        return _bmp
    import board_config as bc
    from bmp280 import BMP280

    # FunHouse BMP280 is at 0x77
    _bmp = BMP280(bc.i2c, addr=0x77)
    return _bmp


def temperature():
    """AHT20 on the shared board I2C."""
    return _aht20()


def humidity():
    """Same AHT20 instance as temperature."""
    return _aht20()


def pressure():
    """BMP280 on the shared board I2C."""
    return _bmp280()


def pixels():
    """5× DotStar (APA102) on GPIO14/15."""
    from machine import Pin, SoftSPI

    from dotstar import DotStar

    spi = SoftSPI(baudrate=1_000_000, sck=Pin(15), mosi=Pin(14), miso=Pin(21))
    return DotStar(spi, 5, auto_write=True)


def audio_out():
    """Onboard speaker DAC pin (GPIO42) — PWM/DAC endpoint."""
    from machine import Pin, PWM

    return PWMToneOutput(lambda: PWM(Pin(42), freq=440, duty=0))


def wlan():
    import network

    return network.WLAN(network.STA_IF)
