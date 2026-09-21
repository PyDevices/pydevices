"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "pcm_in",
        "audio_power",
        "sdcard",
        "camera",
        "radio",
        "wlan",
        "ble",
        "usb_device",
    }
)

# Audio roles are factories: first board_config access does not construct.
# GUI: import board_config, then board_config.pcm_out(format=...).
# Non-GUI: import board_peripherals and call the same factory.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power"})

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
    AudioCapability,
    AudioFactory,
    AudioFormat,
    AudioSession,
    I2SWire,
    adapt_channels,
    check_latency,
    negotiate,
    pace_output,
    queue_bytes,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

# Default when format=None. Codec init still needs a clock before I2S exists,
# so PWM bootstraps GPIO13; once I2S opens it takes mck=Pin(13) from the same
# PLL as BCLK/LRCK and PWM is released. Dual PWM+I2S on that pin beats and
# sounds like irregular skips. IDF I2S MCLK is 256fs; match the codec to that.
# Rate is app-chosen; this board's DAC/speaker are mono 16-bit signed LE.
# Discover what it takes without opening: pcm_out.capability.
_RATE = 24000
_FORMAT = AudioFormat(_RATE, 1, 16)
_DEFAULT_VOLUME = 50
_MCLK_FS = 256

# --- what this board can actually do --------------------------------------
#
# The speaker is mono. The wire is not: the ES8311 clocks two slots and feeds
# one of them to one speaker, so stereo content opens I2S.STEREO and nothing
# is mixed down. That is why ``channels`` and ``native_channels`` differ, and
# it is the whole reason the two are separate fields.
#
# This replaces a _MAX_CHANNELS = 1 that sat beside an audio_out accepting 2
# channels while audio_in raised on the same request -- the file contradicted
# itself, which is what happens when every board writes its own validation.
_MAX_CHANNELS = 1
AUDIO_OUT = AudioCapability(
    _FORMAT,
    rates=None,          # I2S PLL; MCLK follows at rate * 256
    channels=(1, 2),
    native_channels=_MAX_CHANNELS,
    bits=(16,),
    wire=I2SWire(0, sck=_SCLK, ws=_LRCK, sd=_DSDIN, mck=_MCLK, mck_fs=_MCLK_FS),
)

# Capture is the ES7210 on the SAME I2S port and the same clocks as playback,
# with AudioSession(duplex=False) below. That is why this board cannot run the
# acoustic loopback in tools/audio_rig/ and the T-Embed can: there, output and
# input are separate peripherals on separate pins.
AUDIO_IN = AudioCapability(
    _FORMAT,
    rates=None,
    channels=(1,),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(0, sck=_SCLK, ws=_LRCK, sd=_ASDOUT, mck=_MCLK, mck_fs=_MCLK_FS),
)

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


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """ES8311 speaker: a raw ``PCMOutput``. Push bytes with ``write()``.

    ``format`` is the write() contract; ``None`` is the board default
    (24 kHz mono 16-bit). Ask ``pcm_out.capability`` what it takes. Asking
    for 2 channels opens ``I2S.STEREO`` so the ES8311's two-slot clock tree
    matches -- the DAC still feeds one speaker, and nothing is mixed down.

    Needs no audioif: nothing here pulls a sample graph. That is what lets a
    Spotify Connect speaker or a USB sound card run on firmware built
    without a DSP package.

    The ring is a physical ceiling, not the latency governor. I2SPCMOutput
    reports queued_size() over a byte-clock against the DMA's exactly-realtime
    drain, so the pump's lookahead governs note-to-sound latency and a
    full-size ring only guarantees writes never block. Shrinking it for
    latency="low" made every service call block against the DMA (measured
    88-160ms per call on this board -- the interaction stutter).

    The result is paced. I2S is armed into asyncio mode on open, so a full
    DMA returns zero from write() rather than holding the GIL; without
    PaceOutput keeping the remainder, PCMOutput.write() raises "audio stream
    made no write progress". It also covers Device.attach(), which slams
    write() from a Connect pump; blocking there starves the C6 SDIO Wi-Fi
    path and is audible as skips.
    """
    global _mclk_rate

    # check_latency is explicit rather than a side effect of handing `latency`
    # to queue_bytes: passing None to stop it shrinking the ring also stopped
    # it checking, so every unknown value -- "fast", "nonsense" -- was silently
    # accepted while only "low" did anything, contradicting this function's own
    # docstring. A latency keyword that promises tuning it does not do is worse
    # than one that raises.
    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    _mclk_rate = wire.rate
    ibuf = queue_bytes(wire, None, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    device = I2SPCMOutput(
        lambda: _output_stream(ibuf, wire),
        wire,
        session=_SESSION,
        set_hardware_volume=lambda value: _codec_call("set_dac_volume", value),
        set_hardware_mute=lambda value: _codec_call("dac_mute", value),
        power=lambda enable: _output_power(enable, wire.rate),
        # For a consumer that drives the peripheral in C: the pin map, and a
        # way to bring the codec up without opening a stream. On a firmware
        # carrying `audiopump`, audiodev's sample player uses both and never
        # opens machine.I2S on this port -- the pump's own I2S channel is the
        # only owner. On a firmware without it these two are inert.
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    device.set_volume(_DEFAULT_VOLUME)
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device, queue_ms=80)


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """ES7210 capture: a raw ``PCMInput`` with hardware ADC gain.

    Shares I2S(0) and its clocks with playback under a non-duplex session,
    so this board cannot record itself.
    """
    global _mclk_rate

    check_latency(latency)
    wire, source = negotiate(AUDIO_IN, format)
    if source is not wire:
        # Capture has no adapter. negotiate() will happily say "open the wire
        # at 1 channel and convert to the 2 you asked for", but that machinery
        # exists only on the push side -- so handing back the wire format here
        # would give a caller who asked for stereo a mono stream and no error.
        # Silently-different is the exact failure this contract prevents.
        raise ValueError(
            "this board captures %d channel(s); asked for %d, and capture "
            "cannot be remixed" % (wire.channels, source.channels)
        )
    _mclk_rate = wire.rate
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    return I2SPCMInput(
        lambda: _input_stream(ibuf, wire),
        wire,
        session=_INPUT_SESSION,
        set_hardware_gain=lambda value: _INPUT_SESSION.get_codec().set_gain(value),
        power=lambda enable: _input_power(enable, wire.rate),
    )


def _audio_out(format=None, *, latency=None, queue_ms=None, **kwargs):
    """ES8311 sample player: ``play(sample, loop=)``/``stop()``/``pause()``/
    ``resume()``/``playing`` over any audiosample (``synthio.Synthesizer``,
    ``audiomixer.Mixer``, ``audiocore.RawSample``/``WaveFile``, effects),
    with hardware volume and mute.

    Requires audioif in firmware. Use ``pcm_out`` when you already have PCM.

    GUI apps: ``import board_config`` then ``board_config.audio_out(...)``.
    Non-GUI apps: ``import board_peripherals`` and call the same factory --
    this module never imports ``board_config``, which on this board would
    start MIPI DSI and stall the VM.
    """
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    if latency == "low":
        # 10ms chunks, 4-chunk lookahead: a ~50ms schedule. The measured worst
        # pump gap under heavy interaction is 28ms (the ~33ms frame render
        # showing through), so 50ms keeps real margin while staying tight
        # enough for live pad response.
        pump.setdefault("chunk_ms", 10)
        pump.setdefault("lookahead_chunks", 4)
    device = _pcm_out(format, latency=latency, queue_ms=queue_ms, **kwargs)
    return AudioOut(device, **pump)


def _audio_power(enable=True, *, volume=None):
    """Bring the analog path up or down WITHOUT opening an I2S stream.

    For a consumer that drives the peripheral itself -- usbif's C FreeRTOS
    pump reads ``AUDIO_OUT.wire`` and opens I2S in C. Two owners of one I2S
    channel is a silent failure rather than an error, so Python must not
    open one; but the codec still has to be powered and unmuted or every
    byte moves and nothing is audible.

    The codec needs a clock before I2S exists, so PWM bootstraps MCLK here
    and the C pump's own ``mclk`` takes the pin over when it starts.
    """
    if enable:
        _ensure_mclk(_MCLK_FS)
        _codec_call("enable_output", True)
        _codec_call("dac_mute", False)
        if volume is not None:
            _codec_call("set_dac_volume", int(volume))
        from machine import Pin

        global _pa
        if _pa is None:
            _pa = Pin(_PA_CTRL, Pin.OUT, value=0)
        _pa.value(1)
    else:
        if _pa is not None:
            _pa.value(0)
        _codec_call("enable_output", False)
        _stop_mclk()
    return enable


def _input_power(enable, rate):
    if enable:
        _INPUT_SESSION.get_codec().enable_input(True)
    else:
        _INPUT_SESSION.get_codec().enable_input(False)


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


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
