"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"pixels", "audio_out", "audio_in", "sdcard", "battery", "i2c", "wlan", "ble"})

from audiodev import AudioFormat
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

_FORMAT = AudioFormat(16000, 2, 16)

# LilyGO T-Embed pin_config.h
_APA102_CLK = 45
_APA102_DI = 42
_IIS_BCLK = 7
_IIS_WCLK = 5
_IIS_DOUT = 6
_ES7210_BCLK = 47
_ES7210_LRCK = 21
_ES7210_DIN = 14
_ES7210_MCLK = 48
_SD_CS = 39
_SD_SCK = 40
_SD_MOSI = 41
_SD_MISO = 38
_BAT_VOLT = 4
_IIC_SDA = 18
_IIC_SCL = 8


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def pixels():
    """7× APA102 ring (DotStar)."""
    from machine import Pin, SoftSPI

    from dotstar import DotStar

    spi = SoftSPI(baudrate=1_000_000, sck=Pin(_APA102_CLK), mosi=Pin(_APA102_DI), miso=Pin(3))
    return DotStar(spi, 7, auto_write=True)


def audio_out():
    """MAX98357A I2S amplifier (no codec chip). Returns an AudioOut sample
    player: ``play(sample, loop=)``/``stop()``/``pause()``/``resume()``/
    ``playing`` over any audiosample."""
    from machine import I2S, Pin

    from audiodev.sample_out import AudioOut

    def stream():
        return I2S(
        1,
        sck=Pin(_IIS_BCLK),
        ws=Pin(_IIS_WCLK),
        sd=Pin(_IIS_DOUT),
        mode=I2S.TX,
        bits=16,
        format=I2S.STEREO,
        rate=16000,
        ibuf=20000,
        )

    return AudioOut(I2SPCMOutput(stream, _FORMAT))


def audio_in():
    """ES7210 ADC + I2S RX (dual MEMS)."""
    from machine import I2C, I2S, Pin

    from es7210 import ES7210

    i2c = I2C(0, sda=Pin(_IIC_SDA), scl=Pin(_IIC_SCL), freq=400_000)
    codec = ES7210(i2c)

    def stream():
        return I2S(
        0,
        sck=Pin(_ES7210_BCLK),
        ws=Pin(_ES7210_LRCK),
        sd=Pin(_ES7210_DIN),
        mck=Pin(_ES7210_MCLK),
        mode=I2S.RX,
        bits=16,
        format=I2S.STEREO,
        rate=16000,
        ibuf=20000,
        )

    return I2SPCMInput(
        stream, _FORMAT, codec=codec,
        set_hardware_gain=codec.set_gain, power=codec.enable_input,
    )


def sdcard():
    """MicroSD on dedicated SPI pins (sdcard.py)."""
    from machine import Pin, SoftSPI

    from sdcard import SDCard

    spi = SoftSPI(
        baudrate=1_000_000,
        sck=Pin(_SD_SCK),
        mosi=Pin(_SD_MOSI),
        miso=Pin(_SD_MISO),
    )
    return SDCard(spi, Pin(_SD_CS, Pin.OUT, value=1))


def battery():
    from battery_adc import BatteryADC

    return BatteryADC(_BAT_VOLT, scale=2.0)


def i2c():
    """T-Embed Qwiic / expansion I2C (LilyGO PIN_IIC_*)."""
    from machine import I2C, Pin

    return I2C(0, sda=Pin(_IIC_SDA), scl=Pin(_IIC_SCL), freq=400_000)


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
