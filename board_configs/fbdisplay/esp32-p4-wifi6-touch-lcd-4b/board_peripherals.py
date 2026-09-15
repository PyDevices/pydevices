"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {"audio_out", "audio_in", "sdcard", "camera", "radio", "wlan", "ble", "usb_device"}
)

# audio_out / audio_in are factories: first board_config access does not
# construct. GUI: import board_config, then board_config.audio_out(format=...).
# Non-GUI: import board_peripherals and call the same factory.
FACTORY_ROLES = frozenset({"audio_out", "audio_in"})

# Waveshare wiki I2S / ES8311 pin map (P4 panel family)
_MCLK = 13
_SCLK = 12
_ASDOUT = 11
_LRCK = 10
_DSDIN = 9
_PA_CTRL = 53

# Panel I2C (touch, ES8311, ES7210, camera SCCB). Same bus object as
# board_config.i2c when that module is already imported.
_I2C_PORT = 1
_I2C_SCL = 8
_I2C_SDA = 7

from audiodev import (
    AudioFormat,
    AudioSession,
    AudioFactory,
    adapt_channels,
    pace_output,
    check_latency,
    queue_bytes,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

# Default when format=None. Codec init still needs a clock before I2S exists,
# so PWM bootstraps GPIO13; once I2S opens it takes mck=Pin(13) from the same
# PLL as BCLK/LRCK and PWM is released. Dual PWM+I2S on that pin beats and
# sounds like irregular skips. IDF I2S MCLK is 256fs; match the codec to that.
# Rate is app-chosen; this board's DAC/speaker are mono 16-bit signed LE.
# Discover channels without opening: audio_out.max_channels (from ES8311.channels).
_RATE = 24000
_FORMAT = AudioFormat(_RATE, 1, 16)
_MAX_CHANNELS = 1
_DEFAULT_VOLUME = 50
_MCLK_FS = 256

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
_mclk_rate = _RATE
_i2c_own = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def _require_format(format):
    """Return the PCM format this factory will open, or raise.

    ``format=None`` is the board default. Same shape as ``audiodev.auto.audio_out``.
    This hardware is a mono 16-bit signed LE speaker. ``format.channels`` is
    the write() contract and the I2S slot mode: 1 is the 24 kHz bring-up
    path (I2S.MONO); 2 opens I2S.STEREO so the ES8311 two-slot clock tree
    matches. The DAC still has one speaker (left). Widths other than 16-bit
    signed LE raise. I2S MCLK is ``rate * 256`` once the stream is open.
    """
    if format is None:
        return _FORMAT
    if not isinstance(format, AudioFormat):
        raise TypeError("format must be AudioFormat")
    if format.channels not in (1, 2):
        raise ValueError("channel count must be 1 or 2")
    if format.bits != 16 or not format.signed or format.byteorder != "little":
        raise ValueError("this board's I2S/ES8311 path is 16-bit signed little-endian")
    return format


def _wire_format(fmt):
    """I2S format: app rate and channel count (1 or 2 slots)."""
    return fmt


def _i2c():
    """Panel I2C without forcing a board_config import.

    GUI apps import board_config first (eager display); reuse that bus.
    Non-GUI apps import this module only and we open I2C(1) on the panel
    pins. Never ``import board_config`` from here: on this board that
    module inits MIPI DSI at import and stalls the VM.
    """
    global _i2c_own

    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400_000)
    return _i2c_own


def _ensure_mclk(multiplier=_MCLK_FS, rate=None):
    """PWM-bootstrap the shared codec MCLK on GPIO13 until I2S takes the pin."""
    global _mclk, _mclk_rate
    from machine import PWM, Pin

    if rate is not None:
        _mclk_rate = int(rate)
    freq = _mclk_rate * multiplier
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
    from es8311 import ES8311

    _ensure_mclk(_MCLK_FS)
    codec = ES8311(_i2c(), mclk_multiplier=_MCLK_FS)
    # Enable path before I2S starts (PCMOutput opens the stream next).
    codec.enable_output(True)
    codec.dac_mute(False)
    codec.set_dac_volume(_DEFAULT_VOLUME)
    return codec


def _input_codec():
    from es7210 import ES7210

    _ensure_mclk(_MCLK_FS)
    return ES7210(_i2c(), profile="waveshare_p4")


def _i2s(mode, sd_pin, ibuf, fmt):
    """Open I2S and move MCLK off PWM onto the I2S PLL (same as BCLK/LRCK)."""
    from machine import I2S, Pin

    _stop_mclk()
    return I2S(
        0,
        sck=Pin(_SCLK),
        ws=Pin(_LRCK),
        sd=Pin(sd_pin),
        mck=Pin(_MCLK),
        mode=mode,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _output_stream(ibuf, fmt):
    from machine import I2S

    return _i2s(I2S.TX, _DSDIN, ibuf, fmt)


def _input_stream(ibuf, fmt):
    from machine import I2S

    return _i2s(I2S.RX, _ASDOUT, ibuf, fmt)


def _codec_call(name, value):
    return getattr(_SESSION.get_codec(), name)(value)


def _output_power(enable, rate):
    global _pa
    from machine import Pin

    if _pa is None:
        _pa = Pin(_PA_CTRL, Pin.OUT, value=0)
    if enable:
        # Stream already owns GPIO13 via I2S mck=. PWM here fights that PLL.
        _codec_call("enable_output", True)
        _pa.value(1)
    else:
        _pa.value(0)
        _codec_call("enable_output", False)


def audio_out(format=None, *, latency=None, queue_ms=None):
    """ES8311 sample player: ``play(sample, loop=)``/``stop()``/``pause()``/
    ``resume()``/``playing`` over any audiosample (``synthio.Synthesizer``,
    ``audiomixer.Mixer``, ``audiocore.RawSample``/``WaveFile``, effects),
    with hardware volume and mute.

    ``format`` is an ``AudioFormat`` or ``None`` (board default: 24 kHz
    mono 16-bit). Same shape as ``audiodev.auto.audio_out``: ``format`` is
    the write() contract. Discover ``audio_out.max_channels`` for the
    speaker (this board: 1). Asking for 2 channels opens I2S.STEREO so the
    ES8311 two-slot clocks match; the DAC still feeds one speaker. I2S
    drives MCLK at ``format.rate * 256`` on GPIO13.

    GUI apps: ``import board_config`` then
    ``board_config.audio_out(format=...)``. Non-GUI apps:
    ``import board_peripherals`` and the same call — this factory never
    imports ``board_config``.

    ``latency`` / ``queue_ms`` size the I2S ring buffer. Only these two of the
    shared audio keywords mean anything here: there is no software coalescing
    stage and no host device to name, so the rest raise rather than being
    accepted and ignored.
    """
    from audiodev.sample_out import AudioOut

    global _mclk_rate

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
    fmt = _require_format(format)
    wire = _wire_format(fmt)
    _mclk_rate = wire.rate
    check_latency(latency)
    ibuf = queue_bytes(wire, None, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    transport = I2SPCMOutput(
        lambda: _output_stream(ibuf, wire),
        wire,
        session=_SESSION,
        set_hardware_volume=lambda value: _codec_call("set_dac_volume", value),
        set_hardware_mute=lambda value: _codec_call("dac_mute", value),
        power=lambda enable: _output_power(enable, wire.rate),
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
    transport = adapt_channels(transport, fmt)
    # Connect attaches .transport and slams write(). Without this, I2S.write
    # blocks with the GIL held once DMA is full (measured 88-160ms) and the
    # C6 SDIO Wi-Fi path starves — audible skips. AudioOut.play already
    # paces; this covers attach().
    transport = pace_output(transport, queue_ms=80)
    return AudioOut(transport, **pump_kwargs)


def _input_power(enable, rate):
    if enable:
        _INPUT_SESSION.get_codec().enable_input(True)
    else:
        _INPUT_SESSION.get_codec().enable_input(False)


def audio_in(format=None, *, latency=None, queue_ms=None):
    """Portable ES7210 PCM capture device with hardware ADC gain.

    ``format`` / ``latency`` / ``queue_ms`` match :func:`audio_out`.
    """
    global _mclk_rate

    fmt = _require_format(format)
    if fmt.channels > _MAX_CHANNELS:
        raise ValueError(
            "this board's ES7210 path supports at most %d channel(s)"
            % _MAX_CHANNELS
        )
    _mclk_rate = fmt.rate
    ibuf = queue_bytes(fmt, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    return I2SPCMInput(
        lambda: _input_stream(ibuf, fmt),
        fmt,
        session=_INPUT_SESSION,
        set_hardware_gain=lambda value: _INPUT_SESSION.get_codec().set_gain(value),
        power=lambda enable: _input_power(enable, fmt.rate),
    )


audio_out = AudioFactory(audio_out, _MAX_CHANNELS)
audio_in = AudioFactory(audio_in, _MAX_CHANNELS)


def sdcard():
    """TF card via SDIO 3.0 (``machine.SDCard``)."""
    from machine import SDCard

    try:
        return SDCard()
    except TypeError:
        return SDCard(slot=0)


# MIPI-CSI camera control shares the panel's I2C bus (GPIO7/8, alongside
# touch, the ES8311 and the ES7210). The board exposes no reset, power-down
# or XCLK pin for the camera connector, so the module's defaults stand.
#
# Sharing means sharing the *bus object*, not just the pins. board_config
# already opened this bus as machine.I2C(1, ...) for the GT911, so the port
# is named here and cameraif attaches to what is already there. Letting it
# open its own master on the same two pins is not an error anyone reports:
# both peripherals reach the wires through the pin matrix, the camera works
# perfectly, and the touchscreen then times out on every read.
_CAM_SDA = _I2C_SDA
_CAM_SCL = _I2C_SCL
_CAM_I2C_PORT = _I2C_PORT


def camera(**kwargs):
    """MIPI-CSI camera on the panel's camera connector.

    Any ``cameraif.Camera`` keyword passes straight through, so a caller can
    pick a format, set exposure and gain, or turn on the sensor's test
    pattern without this function growing a parameter per feature::

        cam = boarddev.camera(exposure=400, gain=8)
        cam = boarddev.camera(test_pattern=True)   # proves the MIPI link

    The board facts -- which pins the SCCB bus is on -- are supplied here
    because that is what this file is for. cameraif itself knows nothing
    about any board, which is what lets the same module drive a different
    camera on different wiring.
    """
    import cameraif

    if not cameraif.available():
        raise NotImplementedError(
            "cameraif is not in this firmware, or this is not an ESP32-P4"
        )
    kwargs.setdefault("sda", _CAM_SDA)
    kwargs.setdefault("scl", _CAM_SCL)
    kwargs.setdefault("i2c", _CAM_I2C_PORT)
    return cameraif.Camera(**kwargs)


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
