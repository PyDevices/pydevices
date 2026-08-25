"""Lazy constructors for M5Stack CoreS3 non-UI devices. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_in",
        "audio_out",
        "sdcard",
        "camera",
        "accelerometer",
        "gyroscope",
        "i2c",
        "wlan",
        "ble",
    }
)

from audiodev import AudioFormat, AudioSession
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

_FORMAT = AudioFormat(16000, 2, 16)
_SESSION = AudioSession(duplex=False)

# M5Unified CoreS3 I2S / codec pin map
_MCLK = 0
_BCLK = 34
_LRCK = 33
_DOUT = 13
_DIN = 14
_BMI270_ADDR = 0x69
_RATE = 16000

_imu = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    import board_config as bc

    return bc.i2c


def _bmi270():
    global _imu
    if _imu is not None:
        return _imu
    from bmi270 import BMI270

    import board_config as bc

    _imu = BMI270(bc.i2c, address=_BMI270_ADDR)
    return _imu


def audio_in():
    """ES7210 ADC + I2S RX (dual MEMS)."""
    from machine import I2S, Pin

    from es7210 import ES7210

    import board_config as bc

    codec = ES7210(bc.i2c, profile="m5")

    def stream():
        return I2S(
        1,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DIN),
        mck=Pin(_MCLK),
        mode=I2S.RX,
        bits=16,
        format=I2S.STEREO,
        rate=_RATE,
        ibuf=20000,
        )

    return I2SPCMInput(
        stream, _FORMAT, session=_SESSION, codec=codec,
        set_hardware_gain=codec.set_gain, power=codec.enable_input,
    )


def audio_out():
    """AW88298 amp + I2S TX (AW9523 speaker enable). Returns an AudioOut
    sample player: ``play(sample, loop=)``/``stop()``/``pause()``/
    ``resume()``/``playing`` over any audiosample."""
    from machine import I2S, Pin

    from aw88298 import AW88298

    import board_config as bc

    from audiodev.sample_out import AudioOut

    codec = AW88298(bc.i2c, sample_rate=_RATE, enable_aw9523=True)

    def stream():
        return I2S(
        1,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DOUT),
        mode=I2S.TX,
        bits=16,
        format=I2S.STEREO,
        rate=_RATE,
        ibuf=20000,
        )

    return AudioOut(I2SPCMOutput(
        stream, _FORMAT, session=_SESSION, codec=codec,
        set_hardware_mute=codec.mute, power=codec.enable_output,
    ))


def sdcard():
    """CoreS3 microSD via SDMMC when firmware exposes machine.SDCard."""
    from machine import SDCard

    return SDCard()


def camera():
    raise NotImplementedError("CoreS3 camera needs native CSI / GC0308 support")


def accelerometer():
    """BMI270 accel (same instance as gyroscope)."""
    return _bmi270()


def gyroscope():
    """BMI270 gyro (same instance as accelerometer)."""
    return _bmi270()


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
