"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {"audio_out", "audio_in", "sdcard", "camera", "radio", "wlan", "ble", "usb_device"}
)

# Waveshare wiki I2S / ES8311 pin map (P4 panel family)
_MCLK = 13
_SCLK = 12
_ASDOUT = 11
_LRCK = 10
_DSDIN = 9
_PA_CTRL = 53

from audiodev import AudioFormat, AudioSession, check_latency, queue_bytes
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

# 24 kHz mono PCM. Firmware has no I2S mck= — PWM supplies MCLK.
# Bring-up (ear-verified): MCLK before ES8311 init; unmute + volume before I2S; MONO.
_RATE = 24000
_FORMAT = AudioFormat(_RATE, 1, 16)
_DEFAULT_VOLUME = 50

# I2S ring buffer. The default is the ear-verified bring-up value; leave it. A
# caller asking for latency="low" gets a shorter one instead (see queue_bytes),
# which is what an interactive synth needs and what buffered playback does not.
_IBUF = 20000

# Floor for that shortened buffer: I2S feeds from DMA blocks, so too small a ring
# underruns no matter how promptly the caller writes.
_MIN_IBUF = 4096
_SESSION = AudioSession(codec_factory=lambda: _codec(), duplex=False)
_INPUT_SESSION = AudioSession(codec_factory=lambda: _input_codec(), duplex=False)
_pa = None
_mclk = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _ensure_mclk(multiplier=512):
    """Drive the shared codec MCLK on GPIO13 (fixed at 512fs on this board)."""
    global _mclk
    from machine import PWM, Pin

    freq = _RATE * multiplier
    if _mclk is None:
        _mclk = PWM(Pin(_MCLK), freq=freq, duty_u16=32768)
    else:
        _mclk.freq(freq)
    return _mclk


def _stop_mclk():
    global _mclk
    if _mclk is None:
        return
    try:
        _mclk.deinit()
    except Exception:
        pass
    _mclk = None


def _codec():
    import board_config as bc
    from es8311 import ES8311

    _ensure_mclk(512)
    codec = ES8311(bc.i2c, mclk_multiplier=512)
    # Enable path before I2S starts (PCMOutput opens the stream next).
    codec.enable_output(True)
    codec.dac_mute(False)
    codec.set_dac_volume(_DEFAULT_VOLUME)
    return codec


def _input_codec():
    import board_config as bc
    from es7210 import ES7210

    _ensure_mclk(512)
    return ES7210(bc.i2c, profile="waveshare_p4")


def _output_stream(ibuf=_IBUF):
    from machine import I2S, Pin

    _ensure_mclk(512)
    return I2S(
        0,
        sck=Pin(_SCLK),
        ws=Pin(_LRCK),
        sd=Pin(_DSDIN),
        mode=I2S.TX,
        bits=16,
        format=I2S.MONO,
        rate=_RATE,
        ibuf=ibuf,
    )


def _input_stream(ibuf=_IBUF):
    from machine import I2S, Pin

    _ensure_mclk(512)
    return I2S(
        0,
        sck=Pin(_SCLK),
        ws=Pin(_LRCK),
        sd=Pin(_ASDOUT),
        mode=I2S.RX,
        bits=16,
        format=I2S.MONO,
        rate=_RATE,
        ibuf=ibuf,
    )


def _codec_call(name, value):
    return getattr(_SESSION.get_codec(), name)(value)


def _output_power(enable):
    global _pa
    from machine import Pin

    if _pa is None:
        _pa = Pin(_PA_CTRL, Pin.OUT, value=0)
    if enable:
        _ensure_mclk(512)
        _codec_call("enable_output", True)
        _pa.value(1)
    else:
        _pa.value(0)
        _codec_call("enable_output", False)


def audio_out(*, latency=None, queue_ms=None):
    """ES8311 sample player: ``play(sample, loop=)``/``stop()``/``pause()``/
    ``resume()``/``playing`` over any audiosample (``synthio.Synthesizer``,
    ``audiomixer.Mixer``, ``audiocore.RawSample``/``WaveFile``, effects),
    with hardware volume and mute.

    ``latency`` / ``queue_ms`` size the I2S ring buffer. Only these two of the
    shared audio keywords mean anything here: there is no software coalescing
    stage and no host device to name, so the rest raise rather than being
    accepted and ignored.
    """
    from audiodev.sample_out import AudioOut

    # The ring is a physical ceiling, not the latency governor: I2SPCMOutput
    # now reports queued_size() (a byte-clock over the DMA's exactly-realtime
    # drain), so the pump's lookahead governs note-to-sound latency and a
    # full-size ring simply guarantees writes never block. Shrinking the ring
    # for latency="low" only made every service call block against the DMA
    # (measured 88-160ms per call on this board - the interaction stutter).
    # Validate the profile even though the ring no longer varies with it.
    # queue_bytes() used to do this as a side effect of being handed `latency`;
    # passing None to stop it shrinking the ring also stopped it checking, so
    # every unknown value -- "fast", "nonsense" -- was silently accepted while
    # only "low" did anything. That contradicts this function's own docstring,
    # and silently accepting a latency keyword promises tuning that does not
    # happen. The check is explicit here so it cannot be lost again by
    # changing what queue_bytes is asked for.
    check_latency(latency)
    ibuf = queue_bytes(_FORMAT, None, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    transport = I2SPCMOutput(
        lambda: _output_stream(ibuf),
        _FORMAT,
        session=_SESSION,
        set_hardware_volume=lambda value: _codec_call("set_dac_volume", value),
        set_hardware_mute=lambda value: _codec_call("dac_mute", value),
        power=_output_power,
    )
    transport.set_volume(_DEFAULT_VOLUME)
    pump_kwargs = {}
    if latency == "low":
        # 10ms chunks, 4-chunk lookahead: a ~50ms schedule. The measured
        # worst pump gap under heavy interaction is 28ms (the ~33ms frame
        # render showing through), so 50ms keeps real margin while staying
        # tight enough for live pad response.
        pump_kwargs["chunk_ms"] = 10
        pump_kwargs["lookahead_chunks"] = 4
    return AudioOut(transport, **pump_kwargs)


def _input_power(enable):
    if enable:
        _ensure_mclk(512)
        _INPUT_SESSION.get_codec().enable_input(True)
    else:
        _INPUT_SESSION.get_codec().enable_input(False)


def audio_in(*, latency=None, queue_ms=None):
    """Portable ES8311 PCM capture device with hardware ADC gain.

    ``latency`` / ``queue_ms`` size the I2S ring buffer; see :func:`audio_out`.
    """
    ibuf = queue_bytes(_FORMAT, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    return I2SPCMInput(
        lambda: _input_stream(ibuf),
        _FORMAT,
        session=_INPUT_SESSION,
        set_hardware_gain=lambda value: _INPUT_SESSION.get_codec().set_gain(value),
        power=_input_power,
    )


def sdcard():
    """TF card via SDIO 3.0 (``machine.SDCard``)."""
    from machine import SDCard

    try:
        return SDCard()
    except TypeError:
        return SDCard(slot=0)


def camera():
    raise NotImplementedError(
        "MIPI CSI camera needs a native camera module in firmware; no single-file driver"
    )


def radio():
    """ESP32-C6 SDIO co-processor — same NIC as ``wlan`` on P4 builds."""
    return wlan()


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    import bluetooth

    return bluetooth.BLE()


def usb_device():
    from machine import USBDevice

    return USBDevice()
