"""Lazy constructors for M5Stack Tab5 (ILI9881C). PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset({"audio_in", "audio_out", "sdcard", "camera", "i2c", "wlan", "ble"})

from audiodev import AudioFormat, AudioSession, queue_bytes
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

_FORMAT = AudioFormat(16000, 2, 16)
_SESSION = AudioSession(duplex=False)

# M5Unified Tab5 I2S / codec pin map
_MCLK = 30
_BCLK = 27
_LRCK = 29
_DOUT = 26
_DIN = 28
_RATE = 16000

# I2S ring buffer. The default is the value this board was brought up with;
# leave it. A caller asking for latency="low" gets a shorter one instead (see
# queue_bytes), which is what an interactive synth needs and buffered playback
# does not.
_IBUF = 20000

# Floor for that shortened buffer: I2S feeds from DMA blocks, so too small a
# ring underruns no matter how promptly the caller writes.
_MIN_IBUF = 4096


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    import board_config as bc

    return bc.i2c


def audio_in(*, latency=None, queue_ms=None):
    """ES7210 ADC + I2S RX.

    ``latency`` / ``queue_ms`` size the I2S ring buffer; see :func:`audio_out`.
    """
    from machine import I2S, Pin

    from es7210 import ES7210

    import board_config as bc

    codec = ES7210(bc.i2c, profile="m5")
    ibuf = queue_bytes(_FORMAT, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def stream():
        return I2S(
        0,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DIN),
        mck=Pin(_MCLK),
        mode=I2S.RX,
        bits=16,
        format=I2S.STEREO,
        rate=_RATE,
        ibuf=ibuf,
        )

    return I2SPCMInput(
        stream, _FORMAT, session=_SESSION, codec=codec,
        set_hardware_gain=codec.set_gain, power=codec.enable_input,
    )


def audio_out(*, latency=None, queue_ms=None):
    """ES8388 DAC + I2S TX (+ PI4IOE amp enable). Returns an AudioOut sample
    player: ``play(sample, loop=)``/``stop()``/``pause()``/``resume()``/
    ``playing`` over any audiosample.

    ``latency`` / ``queue_ms`` size the I2S ring buffer. Only these two of the
    shared audio keywords mean anything here: there is no software coalescing
    stage and no host device to name, so the rest raise rather than being
    accepted and ignored.
    """
    from machine import I2S, Pin

    from es8388 import ES8388
    from pi4ioe5v import tab5_set_amp

    import board_config as bc

    from audiodev.sample_out import AudioOut

    codec = ES8388(bc.i2c)
    ibuf = queue_bytes(_FORMAT, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)

    def stream():
        return I2S(
        0,
        sck=Pin(_BCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DOUT),
        mck=Pin(_MCLK),
        mode=I2S.TX,
        bits=16,
        format=I2S.STEREO,
        rate=_RATE,
        ibuf=ibuf,
        )

    def power(enable):
        codec.enable_output(enable)
        tab5_set_amp(bc.i2c, enable)

    return AudioOut(I2SPCMOutput(
        stream, _FORMAT, session=_SESSION, codec=codec,
        set_hardware_volume=codec.set_dac_volume,
        set_hardware_mute=codec.dac_mute, power=power,
    ))


def sdcard():
    from machine import SDCard

    return SDCard()


def camera():
    raise NotImplementedError("Tab5 camera needs native CSI support")


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()
