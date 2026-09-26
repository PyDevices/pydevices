"""Lazy constructors for FunHouse non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

from audiodev import AudioCapability
from audiodev.pwm_tone import PWMToneOutput

PERIPHERALS = frozenset(
    {"temperature", "humidity", "pressure", "light", "motion", "pixels", "audio_out", "wlan"}
)

# A PWM buzzer, not a PCM path: no sample rate, no channels, nothing to
# configure. kind="tone" says so, and negotiate() refuses a format here
# rather than accepting one and quietly ignoring it. audio_out stays a
# zero-argument role -- there is no format to pass, so it is not a factory.
AUDIO_OUT = AudioCapability(None, kind="tone")

_aht = None
_dps = None


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


def _dps310():
    global _dps
    if _dps is not None:
        return _dps
    import board_config as bc
    from dps310 import DPS310

    # The FunHouse barometer is a DPS310 at 0x77 (not a BMP280)
    _dps = DPS310(bc.i2c, address=0x77)
    return _dps


def temperature():
    """AHT20 on the shared board I2C."""
    return _aht20()


def humidity():
    """Same AHT20 instance as temperature."""
    return _aht20()


def pressure():
    """DPS310 on the board I2C: ``pressure`` in hPa, ``temperature`` in C."""
    return _dps310()


def light():
    """Ambient light sensor on GPIO18 (ADC2). ``read_u16()``: 0 dark .. 65535."""
    from machine import ADC, Pin

    return ADC(Pin(18), atten=ADC.ATTN_11DB)


def motion():
    """PIR motion sensor on GPIO16. ``value()``: 1 while it sees motion."""
    from machine import Pin

    return Pin(16, Pin.IN)


def pixels():
    """5x DotStar (APA102): clock GPIO15, data GPIO14. Starts dim (0.1).

    Hardware SPI with no MISO: the FunHouse has no spare pin for one, and
    GPIO21, which an earlier version claimed, is the TFT backlight.
    """
    from machine import Pin, SPI

    from dotstar import DotStar

    spi = SPI(2, baudrate=1_000_000, sck=Pin(15), mosi=Pin(14))
    return DotStar(spi, 5, brightness=0.1, auto_write=True)


def audio_out():
    """Onboard speaker DAC pin (GPIO42) — PWM/DAC endpoint."""
    from machine import Pin, PWM

    return PWMToneOutput(lambda: PWM(Pin(42), freq=440, duty=0))


def wlan():
    import network

    return network.WLAN(network.STA_IF)
