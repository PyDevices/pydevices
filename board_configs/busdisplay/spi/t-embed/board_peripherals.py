"""Lazy constructors for contract_proof board peripherals. PERIPHERALS = lazy roles only."""
import boarddev
import sys

PERIPHERALS = frozenset(
    {
        "pixels",
        "audio_out",
        "pcm_out",
        "pcm_in",
        "audio_power",
        "sdcard",
        "battery",
        "i2c",
        "wlan",
        "ble",
    }
)

# Audio roles are factories: first attribute access must not construct, so a
# caller can pass a format. See boarddev.bind_lazy.
FACTORY_ROLES = frozenset({"audio_out", "pcm_out", "pcm_in", "audio_power"})

from audiodev import (
    AudioCapability,
    AudioFactory,
    AudioFormat,
    AudioSession,
    I2SWire,
    adapt_channels,
    negotiate,
)
from audiodev.i2s_audio import I2SPCMInput, I2SPCMOutput

_POWER_ON = 46           # LilyGO PIN_POWER_ON: the whole peripheral rail


def _rail_on():
    """Raise LilyGO's peripheral rail. Idempotent; returns False off-board.

    Keep peripherals powered (LilyGO PIN_POWER_ON). board_config asserts this
    too, but the non-graphics idiom imports only this module -- and the
    MAX98357A sits on that rail. Without it the I2S DMA drains at exactly
    realtime into an unpowered amplifier: every byte-clock reads as playing
    and nothing is heard. Found by playing a tone the DMA reported consumed.
    """
    try:
        from machine import Pin as _Pin
    except ImportError:
        # Host structural import (the contract proof binds this module on
        # CPython, where there is no ``machine``). There is no rail to power
        # there; every peripheral factory below imports ``machine`` lazily and
        # is guarded the same way, so the module stays importable off the
        # board.
        return False
    _Pin(_POWER_ON, _Pin.OUT, value=1)
    return True


_rail_on()

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

_OUT_PORT = 1
_IN_PORT = 0
_IBUF = 20000
_MIN_IBUF = 4096

# --- what this board can actually do --------------------------------------
#
# Every value below was measured on the board, not read off a datasheet, with
# a 440 Hz tone played on the MAX98357A and captured on the ES7210 mics --
# see tools/audio_rig/. A capability is a promise the contract makes on the
# board's behalf, so declaring one that has not been heard is a way of
# shipping a lie.
#
# MAX98357A is an amplifier, not a codec: no I2C, no register set, and it
# takes its clock from BCLK, so the rate is whatever the I2S PLL is asked
# for. Continuous rates (``rates=None``) is therefore a real claim here, not
# an optimistic one. Measured: 16000 (err 0 permille), 22050, 44100 (err -1).
#
# The amp is mono into one speaker, but the wire takes two slots -- so
# ``channels`` and ``native_channels`` differ, and stereo content needs no
# mixdown. Handing it mono opens one slot instead.
_OUT_DEFAULT = AudioFormat(16000, 2, 16)
AUDIO_OUT = AudioCapability(
    _OUT_DEFAULT,
    rates=None,
    channels=(1, 2),
    native_channels=1,
    bits=(16,),
    wire=I2SWire(_OUT_PORT, sck=_IIS_BCLK, ws=_IIS_WCLK, sd=_IIS_DOUT),
)

# ES7210 dual MEMS on its own I2S port and its own pins, which is why this
# board can play and capture at once where the ESP32-P4 panel cannot: there
# the DAC and ADC share I2S(0) and one set of clocks.
#
# Only 16 kHz is declared because only 16 kHz has been captured. The codec's
# MAIN_CLK register encodes an MCLK ratio and the driver's profiles set it to
# fixed values, so another rate needs a register change and a fresh capture
# before it can be promised.
_IN_DEFAULT = AudioFormat(16000, 2, 16)
AUDIO_IN = AudioCapability(
    _IN_DEFAULT,
    rates=(16000,),
    channels=(2,),
    native_channels=2,
    bits=(16,),
    wire=I2SWire(_IN_PORT, sck=_ES7210_BCLK, ws=_ES7210_LRCK, sd=_ES7210_DIN,
                 mck=_ES7210_MCLK, mck_fs=256),
)

_INPUT_SESSION = AudioSession(codec_factory=lambda: _input_codec(), duplex=False)
_in_mclk = None


def load_peripherals(ns):
    boarddev.bind_lazy(ns, sys.modules[__name__])


def pixels():
    """7× APA102 ring (DotStar)."""
    from machine import Pin, SoftSPI

    from dotstar import DotStar

    spi = SoftSPI(baudrate=1_000_000, sck=Pin(_APA102_CLK), mosi=Pin(_APA102_DI), miso=Pin(3))
    return DotStar(spi, 7, auto_write=True)


def _i2c_bus():
    """Panel/Qwiic I2C, shared with whatever already opened it.

    Never ``import board_config`` from here: a non-graphics app importing
    this module must not start a display.
    """
    bc = sys.modules.get("board_config")
    bus = getattr(bc, "i2c", None) if bc is not None else None
    if bus is not None:
        return bus
    from machine import I2C, Pin

    return I2C(0, sda=Pin(_IIC_SDA), scl=Pin(_IIC_SCL), freq=400_000)


def _ensure_in_mclk(rate):
    """PWM-bootstrap the ES7210's MCLK on GPIO48.

    This firmware's ``machine.I2S`` has no ``mck=`` keyword -- passing one
    raises ``TypeError: extra keyword arguments given``. (The previous
    version of this file passed ``mck=Pin(_ES7210_MCLK)``, which means that
    code had never run.) PWM at 256fs is what the ES7210 actually locks to
    here; measured with room noise at peak 159 against a silent floor.
    """
    global _in_mclk
    from machine import PWM, Pin

    freq = int(rate) * AUDIO_IN.wire.mck_fs
    if _in_mclk is None:
        _in_mclk = PWM(Pin(_ES7210_MCLK), freq=freq, duty_u16=32768)
    else:
        _in_mclk.freq(freq)
    return _in_mclk


def _input_codec():
    """ES7210 on the shared I2C bus.

    ``profile="waveshare_p4"`` is not a mistake and not a copy-paste: on this
    board the driver's ``"default"`` profile returns a dead stream (measured
    peak 1 of 32767, i.e. LSB dither), while the waveshare register sequence
    brings the same part up correctly (peak 159 on room noise, 4064 of 4096
    samples non-zero). The profile name describes the register sequence, not
    the board it was first written for. Renaming it is filed, not done here.
    """
    from es7210 import ES7210

    return ES7210(_i2c_bus(), profile="waveshare_p4")


def _out_stream(ibuf, fmt):
    from machine import I2S, Pin

    return I2S(
        _OUT_PORT,
        sck=Pin(_IIS_BCLK),
        ws=Pin(_IIS_WCLK),
        sd=Pin(_IIS_DOUT),
        mode=I2S.TX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _in_stream(ibuf, fmt):
    from machine import I2S, Pin

    _ensure_in_mclk(fmt.rate)
    return I2S(
        _IN_PORT,
        sck=Pin(_ES7210_BCLK),
        ws=Pin(_ES7210_LRCK),
        sd=Pin(_ES7210_DIN),
        mode=I2S.RX,
        bits=fmt.bits,
        format=I2S.STEREO if fmt.channels == 2 else I2S.MONO,
        rate=fmt.rate,
        ibuf=ibuf,
    )


def _pcm_out(format=None, *, latency=None, queue_ms=None):
    """MAX98357A I2S amplifier: a raw ``PCMOutput``. Push bytes with ``write()``.

    ``format`` is the write() contract; ``None`` is this board's default
    (16 kHz stereo 16-bit). Ask ``pcm_out.capability`` what it takes rather
    than guessing. Needs no audiodsp -- no sample graph is pulled.

    The returned device is paced, and that is not optional. ``I2SPCMOutput``
    arms ``machine.I2S`` into asyncio mode on open (a POLL ioctl), so a full
    DMA makes ``write()`` return zero instead of holding the GIL until there
    is room. Handing that straight to a caller breaks
    ``PCMOutput.write()``, which loops until every byte lands and raises
    ``OSError("audio stream made no write progress")`` on a zero return --
    measured here on the first write of a 44.1 kHz tone. ``PaceOutput``
    keeps the remainder instead.

    A caller writing faster than realtime must gate on ``space()``: overflow
    above the stash cap is dropped, deliberately, because the alternative is
    blocking the interpreter while the DAC plays out.
    """
    from audiodev import check_latency, pace_output, queue_bytes

    check_latency(latency)
    wire, source = negotiate(AUDIO_OUT, format)
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    device = I2SPCMOutput(
        lambda: _out_stream(ibuf, wire),
        wire,
        # For a consumer that drives the peripheral in C: the pin map, and a
        # way to bring the analog path up without opening a stream. On a
        # firmware carrying ``audiopump``, audiodev's sample player uses both
        # and never opens ``machine.I2S`` on this port -- the pump's own I2S
        # channel is the only owner. On a firmware without it these two are
        # inert. Without them this board plays every sample on machine.I2S
        # and the pump sits idle (PyDevices/pydevices#41).
        wire=AUDIO_OUT.wire,
        audio_power=_audio_power,
    )
    if source is not wire:
        from audiodev.accel import best_remix

        device = adapt_channels(device, source, remix=best_remix())
    return pace_output(device)


def _pcm_in(format=None, *, latency=None, queue_ms=None):
    """ES7210 dual-MEMS capture: a raw ``PCMInput``."""
    from audiodev import check_latency, queue_bytes

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
    ibuf = queue_bytes(wire, latency, queue_ms, default=_IBUF, minimum=_MIN_IBUF)
    codec = _INPUT_SESSION.get_codec()
    return I2SPCMInput(
        lambda: _in_stream(ibuf, wire),
        wire,
        session=_INPUT_SESSION,
        set_hardware_gain=codec.set_gain,
        power=codec.enable_input,
    )


def _audio_out(format=None, **kwargs):
    """``AudioOut`` sample player over the amplifier: ``play(sample, loop=)``/
    ``stop()``/``pause()``/``resume()``/``playing`` over any audiosample.

    Requires audiodsp in the firmware. Use ``pcm_out`` when you already have
    PCM bytes -- that path has no DSP dependency at all.
    """
    from audiodev.sample_out import AudioOut

    pump = {}
    for key in ("chunk_ms", "lookahead_chunks", "max_catchup_chunks"):
        if key in kwargs:
            pump[key] = kwargs.pop(key)
    return AudioOut(_pcm_out(format, **kwargs), **pump)


def _audio_power(enable=True, *, volume=None):
    """Bring the analog path up WITHOUT opening an I2S stream.

    The same role the P4 panel publishes, on a board that has no codec to
    talk to. A MAX98357A is an amplifier: no I2C, no register set, no mute
    and no volume. So all "power on" means here is LilyGO's rail, and
    ``volume=`` is accepted and ignored -- the loudness lives in the
    material, which is why every probe on this board scales its source.

    **``enable=False`` does not lower anything, on purpose.** GPIO46 is
    PIN_POWER_ON: the display, the backlight, the SD card and the amplifier
    are all on it, so taking it low to silence one of them blanks the screen
    and drops the card. There is no amplifier shutdown pin broken out, and an
    idle I2S channel is already silent, so there is nothing to switch and
    nothing to lose by saying so.

    The audio pump's ``BusioDriver`` calls this before it opens the channel
    and again when it closes it; both calls are safe here.
    """
    if enable:
        _rail_on()
    return enable


pcm_out = AudioFactory(_pcm_out, AUDIO_OUT)
pcm_in = AudioFactory(_pcm_in, AUDIO_IN)
audio_out = AudioFactory(_audio_out, AUDIO_OUT)
audio_power = _audio_power


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
