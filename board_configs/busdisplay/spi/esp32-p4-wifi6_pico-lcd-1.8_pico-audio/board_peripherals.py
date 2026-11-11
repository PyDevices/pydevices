# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""board_peripherals for the Waveshare ESP32-P4-WIFI6 with a Pico-Audio, on MicroPython.

PERIPHERALS = lazy roles only: nothing is constructed until it is asked for.
From Waveshare's ESP32-P4-WIFI6 schematic and the Pico-Audio's:

- Pico-Audio (the PCM5101A one) on the Pico header: DIN GP26 = GPIO23, BCK
  GP27 = GPIO22, LRCK GP28 = GPIO21. The DAC makes its own clock from BCK,
  so there is no MCLK, and an APA2068 amplifier drives the speaker header
  and the 3.5 mm jack. The Pico-Audio Rev2.1 (a CS4344) is wired
  differently: its DIN is GP22, and this file doesn't drive it.
- ES8311 mono codec on I2S0 (MCLK 13, SCLK 12, LRCK 10, DSDIN 9, ASDOUT 11),
  at 0x18 on the board I2C (SDA 7, SCL 8). Its DAC drives the board's own
  speaker connector through an NS4150B amplifier (enable GPIO53), and the
  onboard microphone is its analog input, so ``pcm_in`` records from it.
- MicroSD on SDMMC slot 0 (CLK 43, CMD 44, D0-D3 39-42), powered unless
  GPIO45 is driven high.
- 2-lane MIPI-CSI camera connector; its SCCB is the board I2C (7/8).
- ESP32-C6 Wi-Fi 6 / BLE over SDIO (CLK 18, CMD 19, D0-D3 14-17), reset on
  GPIO54.
- BOOT button on GPIO35 (low when pressed).
- The Type-C is a CH343 USB-UART only. The P4's full-speed USB pairs reach
  the Pico header: GPIO24/25 at pins 19 (D-) and 20 (D+), GPIO26/27 at
  pins 29 (D-) and 27 (D+). Which one is the USB device depends on the
  firmware (micropython-pydevices' boards table).

``audio_out`` and ``pcm_out`` play through the Pico-Audio, or through the
ES8311 when board_config sets ``AUDIO = "es8311"``.
"""

import sys

import boarddev
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

PERIPHERALS = frozenset(
    {
        "audio_out",
        "pcm_out",
        "pcm_in",
        "audio_power",
        "i2c",
        "sdcard",
        "camera",
        "radio",
        "wlan",
        "ble",
        "boot_button",
        "usb_device",
    }
)

# Audio roles are factories: the first board_config access does not construct.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power"})

# Pico-Audio
_PA_PORT = 1
_PA_BCK = 22
_PA_LRCK = 21
_PA_DIN = 23

# ES8311
_MCLK = 13
_SCLK = 12
_ASDOUT = 11
_LRCK = 10
_DSDIN = 9
_PA_CTRL = 53

_I2C_PORT = 1
_I2C_SCL = 8
_I2C_SDA = 7

_BOOT = 35

_i2c_own = None
_audio = "pico-audio"


def load_peripherals(ns):
    """Bind the roles into board_config, playing through the chip its
    ``AUDIO`` names: ``"pico-audio"`` (the default) or ``"es8311"``."""
    global pcm_out, audio_out, audio_power, _audio

    audio = ns.get("AUDIO", "pico-audio")
    _audio = audio
    if audio == "es8311":
        pcm_out = AudioFactory(_es8311_pcm_out, ES8311_OUT)
        audio_out = AudioFactory(_es8311_audio_out, ES8311_OUT)
        audio_power = _es8311_power
    elif audio == "pico-audio":
        pcm_out = AudioFactory(_pico_audio_pcm_out, PICO_AUDIO_OUT)
        audio_out = AudioFactory(_pico_audio_audio_out, PICO_AUDIO_OUT)
        audio_power = _pico_audio_power
    else:
        raise ValueError("AUDIO is 'pico-audio' or 'es8311', not %r" % (audio,))
    boarddev.bind_lazy(ns, sys.modules[__name__])


def i2c():
    """The board I2C (SDA 7, SCL 8): the ES8311 and the camera's SCCB.

    One bus for everything on these pins, so two controllers never share
    them.
    """
    global _i2c_own

    if _i2c_own is None:
        from machine import I2C, Pin

        _i2c_own = I2C(_I2C_PORT, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400_000)
    return _i2c_own


# --- The Pico-Audio ---------------------------------------------------------

# Two channels to two outputs; the DAC takes BCK at 32 or 64 times the rate,
# which 16- and 32-bit stereo give.
PICO_AUDIO_OUT = AudioCapability(
    AudioFormat(48000, 2, 16),
    rates=None,
    channels=(1, 2),
    native_channels=2,
    bits=(16, 32),
    wire=I2SWire(_PA_PORT, sck=_PA_BCK, ws=_PA_LRCK, sd=_PA_DIN),
)

_PA_IBUF = 20000
_PA_MIN_IBUF = 4096


def _pa_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _PA_PORT,
        sck=Pin(_PA_BCK),
        ws=Pin(_PA_LRCK),
        sd=Pin(_PA_DIN),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pico_audio_pcm_out(format=None, *, latency=None, queue_ms=None):
    """The Pico-Audio: a raw ``PCMOutput``, 48 kHz 16-bit stereo by default.

    The DAC has no volume or mute of its own: scale the samples.
    """
    check_latency(latency)
    wire, source = negotiate(PICO_AUDIO_OUT, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_PA_IBUF, minimum=_PA_MIN_IBUF)
    device = I2SPCMOutput(
        lambda: _pa_stream(ibuf, wire),
        wire,
        wire=PICO_AUDIO_OUT.wire,
        audio_power=_pico_audio_power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _pico_audio_audio_out(format=None, **kwargs):
    """``AudioOut`` sample player on the Pico-Audio: ``play(sample, loop=)``,
    ``stop()``, ``playing``. Requires audiodsp in firmware."""
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pico_audio_pcm_out(format, **kwargs), **pump)


def _pico_audio_power(enable=True, *, volume=None):
    """Nothing to switch: the PCM5101A and its amplifier are on whenever the
    board is, and an idle I2S channel is silent. ``volume=`` is ignored."""
    return enable


# --- The ES8311 -------------------------------------------------------------

# The codec needs a clock before I2S exists, so PWM bootstraps MCLK on
# GPIO13; once I2S opens it takes mck=Pin(13) from the same PLL as BCLK and
# LRCK and the PWM is released. IDF's I2S MCLK is 256fs; the codec matches.
_RATE = 24000
_FORMAT = AudioFormat(_RATE, 1, 16)
_DEFAULT_VOLUME = 100  # 0 dB: the loudest the ES8311 plays without clipping
_MCLK_FS = 256

# One DAC, one speaker: the ES8311 clocks two slots and plays one, so stereo
# content opens I2S.STEREO and nothing is mixed down.
ES8311_OUT = AudioCapability(
    _FORMAT,
    rates=None,
    channels=(1, 2),
    native_channels=1,
    bits=(16,),
    # sd_in is the ES8311's ADC output. Publishing it is what lets audio_out
    # and pcm_in run at once on firmware whose audio pump can read the RX
    # half of its own channel: the port opens as one TX/RX pair on one clock.
    wire=I2SWire(
        0, sck=_SCLK, ws=_LRCK, sd=_DSDIN, mck=_MCLK, mck_fs=_MCLK_FS, sd_in=_ASDOUT
    ),
)

# The microphone is the ES8311's ADC on the same I2S port and clocks. With the
# audio pump (audiodev.pump.duplex()), pcm_in reads the RX half of the pump's
# channel, so it records while audio_out plays. Without it, pcm_in is
# machine.I2S, and it and the speaker refuse each other.
AUDIO_IN = AudioCapability(
    _FORMAT,
    rates=None,
    channels=(1,),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(0, sck=_SCLK, ws=_LRCK, sd=_ASDOUT, mck=_MCLK, mck_fs=_MCLK_FS),
)

_IBUF = 20000
_MIN_IBUF = 4096
_SESSION = AudioSession(codec_factory=lambda: _codec(), duplex=False)
_INPUT_SESSION = AudioSession(codec_factory=lambda: _codec(), duplex=False)
_es8311 = None
_pa = None
_mclk = None
_mclk_rate = _RATE
_i2c_own = None


def _pump_clock_running():
    try:
        from audiodev import pump
    except ImportError:
        return False
    return pump.clock_running()


def _duplex_pump():
    """``audiodev.pump`` when this firmware records while it plays, else None."""
    try:
        from audiodev import pump
    except ImportError:
        return None
    return pump if pump.duplex() else None


def _ensure_mclk(multiplier=_MCLK_FS, rate=None):
    """PWM-bootstrap MCLK on GPIO13 until I2S takes the pin.

    Never while the audio pump's channel is running: it already drives GPIO13,
    and a PWM started now would take the pin from it mid-stream.
    """
    global _mclk, _mclk_rate
    from machine import PWM, Pin

    if rate is not None:
        _mclk_rate = int(rate)
    if _pump_clock_running():
        _stop_mclk()
        return None
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


class _ES8311Board:
    """The one ES8311, shared by playback and capture.

    Both directions talk to the same chip, so they share one initialised
    driver: a second ES8311() would reset the chip under the first.
    """

    def __init__(self, codec):
        self._codec = codec

    def __getattr__(self, name):
        return getattr(self._codec, name)

    def set_gain(self, value):
        self._codec.set_adc_volume(value)


def _codec():
    global _es8311
    if _es8311 is None:
        from es8311 import ES8311

        _ensure_mclk(_MCLK_FS)
        codec = ES8311(i2c(), mclk_multiplier=_MCLK_FS)
        codec.enable_output(True)
        codec.dac_mute(False)
        codec.set_dac_volume(_DEFAULT_VOLUME)
        _es8311 = _ES8311Board(codec)
    return _es8311


def _i2s(mode, sd_pin, ibuf, fmt):
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


def _refuse_if_held(session, wanted, holder):
    """Refuse to open I2S(0) while the other direction has it.

    Constructing machine.I2S(0) while it is in use doesn't raise on esp32:
    it deinitialises the live instance and hands the same object back in the
    new direction, so the speaker would just go quiet. pcm_out is always
    machine.I2S, so this holds with the audio pump too; audio_out plays
    through the pump and records alongside pcm_in.
    """
    if session._owners:
        raise OSError(
            "I2S(0) is in use by the %s: this board's speaker and microphone "
            "share one I2S port, and pcm_out and machine.I2S take the whole "
            "port, so close the %s before opening the %s. audio_out can play "
            "while pcm_in records, at the recording's rate"
            % (holder, holder, wanted)
        )


def _output_stream(ibuf, fmt):
    from machine import I2S

    _refuse_if_held(_INPUT_SESSION, "speaker", "microphone")
    return _i2s(I2S.TX, _DSDIN, ibuf, fmt)


def _input_stream(ibuf, fmt):
    from machine import I2S

    _refuse_if_held(_SESSION, "microphone", "speaker")
    return _i2s(I2S.RX, _ASDOUT, ibuf, fmt)


def _codec_call(name, value):
    return getattr(_SESSION.get_codec(), name)(value)


def _amp(on):
    global _pa
    from machine import Pin

    if _pa is None:
        _pa = Pin(_PA_CTRL, Pin.OUT, value=0)
    _pa.value(1 if on else 0)


def _output_power(enable, rate):
    if enable:
        _codec_call("enable_output", True)
        _amp(True)
    else:
        _amp(False)
        _codec_call("enable_output", False)


def _es8311_pcm_out(format=None, *, latency=None, queue_ms=None):
    """The ES8311 on the board's speaker connector: a raw ``PCMOutput``.

    ``format`` is the write() contract; ``None`` is the board default (24 kHz
    mono 16-bit).
    """
    global _mclk_rate

    check_latency(latency)
    wire, source = negotiate(ES8311_OUT, format)
    _mclk_rate = wire.rate
    ibuf = queue_bytes(wire, None, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    device = I2SPCMOutput(
        lambda: _output_stream(ibuf, wire),
        wire,
        session=_SESSION,
        set_hardware_volume=lambda value: _codec_call("set_dac_volume", value),
        set_hardware_mute=lambda value: _codec_call("dac_mute", value),
        power=lambda enable: _output_power(enable, wire.rate),
        wire=ES8311_OUT.wire,
        audio_power=_es8311_power,
    )
    device.set_volume(_DEFAULT_VOLUME)
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device, queue_ms=80)


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """The onboard microphone through the ES8311's ADC: a raw ``PCMInput``.

    With the Pico-Audio playing, the microphone has I2S(0) to itself. With
    the ES8311 playing, it shares I2S(0) and its clocks with playback: on
    firmware with the audio pump, this reads the RX half of the pump's
    channel, so it records while ``audio_out`` plays, in either order, at
    the rate the speaker is clocked at. Without the pump it is
    ``machine.I2S``: opening it while the speaker is open raises OSError,
    and so does the reverse. ``pcm_out`` is always ``machine.I2S``, so it
    refuses alongside a recording either way.
    """
    global _mclk_rate

    check_latency(latency)
    wire, source = negotiate(AUDIO_IN, format)
    if source is not wire:
        raise ValueError(
            "this board captures %d channel(s); asked for %d, and capture "
            "cannot be remixed" % (wire.channels, source.channels)
        )
    _mclk_rate = wire.rate
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    # The audio pump records from the RX half of the ES8311's channel, so
    # only while the ES8311 is the one playing.
    pump = _duplex_pump() if _audio == "es8311" else None
    if pump is not None:
        # The ES8311 has one ADC channel; this records the left slot.
        return pump.PumpPCMInput(
            wire,
            wire=ES8311_OUT.wire,
            ring_bytes=ibuf,
            take="left",
            before_open=lambda: _refuse_if_held(_SESSION, "microphone", "speaker"),
            session=_INPUT_SESSION,
            set_hardware_gain=lambda value: _INPUT_SESSION.get_codec().set_gain(value),
            power=lambda enable: _INPUT_SESSION.get_codec().enable_input(enable),
        )
    return I2SPCMInput(
        lambda: _input_stream(ibuf, wire),
        wire,
        session=_INPUT_SESSION,
        set_hardware_gain=lambda value: _INPUT_SESSION.get_codec().set_gain(value),
        power=lambda enable: _INPUT_SESSION.get_codec().enable_input(enable),
    )


def _es8311_audio_out(format=None, *, latency=None, queue_ms=None, **kwargs):
    """ES8311 sample player: ``play(sample, loop=)``/``stop()``/``playing``
    over any audiosample (``synthio.Synthesizer``, ``audiomixer.Mixer``,
    effects), with hardware volume and mute. Requires audiodsp in firmware.
    """
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    if latency == "low":
        pump.setdefault("chunk_ms", 10)
        pump.setdefault("lookahead_chunks", 4)
    device = _es8311_pcm_out(format, latency=latency, queue_ms=queue_ms, **kwargs)
    return AudioOut(device, **pump)


def _es8311_power(enable=True, *, volume=None):
    """Bring the codec and amplifier up or down without opening I2S, for a
    consumer that drives the I2S peripheral itself (the C audio pump)."""
    if enable:
        _ensure_mclk(_MCLK_FS)
        _codec_call("enable_output", True)
        _codec_call("dac_mute", False)
        if volume is not None:
            _codec_call("set_dac_volume", int(volume))
        _amp(True)
    else:
        if _pa is not None:
            _amp(False)
        _codec_call("enable_output", False)
        _stop_mclk()
    return enable


pcm_out = AudioFactory(_pico_audio_pcm_out, PICO_AUDIO_OUT)
audio_out = AudioFactory(_pico_audio_audio_out, PICO_AUDIO_OUT)
audio_power = _pico_audio_power
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)


def sdcard():
    """The microSD slot over 1-bit SDMMC (``machine.SDCard``); mount it yourself.

    In 4-bit mode a write hangs or resets the board with the cards tried here (reads
    work). 1-bit writes and reads a megabyte cleanly at 40 MHz: about 3.4 MB/s
    written and 2.6 MB/s read.
    """
    from machine import SDCard

    return SDCard(slot=0, width=1, freq=40_000_000, sck=43, cmd=44, data=(39,))


def camera(**kwargs):
    """The camera on the MIPI-CSI connector, through ``cameraif``.

    The firmware finds which sensor it is. Any ``cameraif.Camera`` keyword
    passes straight through. The SCCB bus is the board I2C, by port, so
    cameraif joins the bus already open rather than opening a second
    controller on the same pins.
    """
    import cameraif

    if not cameraif.available():
        raise NotImplementedError("cameraif is not in this firmware, or this is not an ESP32-P4")
    kwargs.setdefault("sda", _I2C_SDA)
    kwargs.setdefault("scl", _I2C_SCL)
    if "i2c" not in kwargs:
        i2c()
        kwargs["i2c"] = _I2C_PORT
    return cameraif.Camera(**kwargs)


def radio():
    """The ESP32-C6 over SDIO: the same NIC as ``wlan``."""
    return wlan()


def wlan():
    import network

    return network.WLAN(network.STA_IF)


def ble():
    # A bledev adapter (docs/guides/bluetooth-le.md). It also answers every
    # bluetooth.BLE method, so code written for the raw radio keeps working.
    try:
        import bledev.mpble
    except ImportError:
        import bluetooth

        return bluetooth.BLE()
    return bledev.mpble.get()


def boot_button():
    """The BOOT button (GPIO35, low when pressed): a strap at reset, a plain
    input once the board is running."""
    from machine import Pin

    return Pin(_BOOT, Pin.IN, Pin.PULL_UP)


def usb_device():
    from machine import USBDevice

    return USBDevice()
