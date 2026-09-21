"""MCU I2S adapter: wrap ``machine.I2S`` as :class:`audiodev.PCMOutput` / :class:`PCMInput`."""

try:
    import asyncio
except ImportError:  # pragma: no cover
    try:
        import uasyncio as asyncio
    except ImportError:
        asyncio = None

import sys

from audiodev import PCMInput, PCMOutput


def _arm_i2s_asyncio(i2s):
    """Switch ``machine.I2S`` to delay=0 writes (partial, no GIL stall).

    The C driver has no Python setter for that mode. A POLL ioctl is the
    documented trigger, and ``select.poll().register`` plus a 0-timeout
    ``poll()`` is how a script issues one. Register with POLLOUT only: the
    default POLLIN|POLLOUT mask EPERMs on a TX stream and would leave the
    device blocking.
    """
    try:
        import select
    except ImportError:
        return None
    poller = getattr(select, "poll", None)
    if poller is None:
        return None
    flags = getattr(select, "POLLOUT", 4)
    try:
        poll = poller()
        poll.register(i2s, flags)
        poll.poll(0)
        return poll
    except (OSError, TypeError, ValueError, AttributeError):
        return None


def _resolve(value):
    return value() if callable(value) else value


def _close_i2s(i2s):
    if i2s is None:
        return
    if hasattr(i2s, "deinit"):
        i2s.deinit()
    elif hasattr(i2s, "close"):
        i2s.close()


try:
    from time import ticks_diff, ticks_ms
except ImportError:  # pragma: no cover - CPython test hosts
    from multimer import ticks_diff, ticks_ms


class I2SPCMOutput(PCMOutput):
    """Playback through ``machine.I2S`` (or any object with ``write``).

    ``machine.I2S`` cannot report how much of its ring is filled, and the
    inherited ``queued_size() == 0`` told the pump's backpressure that the
    queue was always empty - so every service call rendered its full
    catch-up allowance and paid for it inside blocking ``write()`` calls at
    realtime speed (measured 88-160ms per service on the ESP32-P4, which
    starved LVGL and made every interaction stutter). DMA consumption is
    exactly realtime, so a software byte-clock - bytes written minus
    rate x elapsed - reports the queue accurately enough for backpressure.

    On open, a POLL ioctl flips the driver to asyncio mode so ``write()``
    returns a partial/zero count instead of holding the GIL until DMA has
    room. ``PaceOutput`` keeps the remainder.
    """

    def __init__(self, i2s, format, *, wire=None, audio_power=None, **kwargs):
        super().__init__(format, **kwargs)
        self._i2s_factory = i2s
        self._i2s = None
        self._async_stream = None
        self._poll = None
        self._clock_start_ms = None
        self._written_bytes = 0
        # Published, not used here. A consumer that means to drive the
        # peripheral itself -- the audio pump does, in C, on its own task --
        # needs the port and pin numbers and a way to power the codec WITHOUT
        # a stream being opened, because two owners of one I2S channel is the
        # failure that sounds like silence. `audiodev.pump` reads both off
        # this object rather than importing board_peripherals, which it must
        # not: audiodev sits under the board, not beside it. A board that
        # passes neither simply keeps the old path.
        self.wire = wire
        self.audio_power = audio_power

    @property
    def i2s(self):
        return self._i2s

    def _open(self):
        self._i2s = _resolve(self._i2s_factory)
        if hasattr(self._i2s, "open"):
            self._i2s.open()
        self._poll = _arm_i2s_asyncio(self._i2s)
        self._clock_start_ms = None
        self._written_bytes = 0

    def _close(self):
        i2s = self._i2s
        poll = self._poll
        self._i2s = None
        self._async_stream = None
        self._poll = None
        self._clock_start_ms = None
        self._written_bytes = 0
        if poll is not None and i2s is not None:
            unregister = getattr(poll, "unregister", None)
            if unregister is not None:
                try:
                    unregister(i2s)
                except (OSError, KeyError, ValueError):
                    pass
        _close_i2s(i2s)

    def queued_size(self):
        if self._clock_start_ms is None:
            return 0
        elapsed = ticks_diff(ticks_ms(), self._clock_start_ms)
        consumed = elapsed * self.format.rate * self.format.frame_size // 1000
        queued = self._written_bytes - consumed
        if queued < 0:
            # The stream underran and played silence; realign the clock so
            # the report cannot go (and stay) negative.
            self._written_bytes = consumed
            return 0
        return queued

    def _poll_i2s(self):
        if self._poll is None:
            return
        try:
            self._poll.poll(0)
        except (OSError, TypeError, ValueError):
            pass

    def service(self):
        self._poll_i2s()
        return None

    def _write(self, buf):
        if self._clock_start_ms is None:
            self._clock_start_ms = ticks_ms()
        self._poll_i2s()
        written = self._i2s.write(buf)
        # machine.I2S returns None on EAGAIN (DMA full, 0 bytes). That is
        # not "wrote the whole buffer" — counting it as len(buf) would
        # freeze queued_size() at a fake full ring and starve the DAC.
        if written is None:
            count = 0
        else:
            count = int(written)
            if count < 0:
                count = 0
            elif count > len(buf):
                count = len(buf)
        self._written_bytes += count
        return count

    async def _awrite(self, buf):
        if sys.implementation.name == "micropython":
            if self._async_stream is None:
                self._async_stream = asyncio.StreamWriter(self._i2s)
            if self._clock_start_ms is None:
                self._clock_start_ms = ticks_ms()
            self._async_stream.write(buf)
            await self._async_stream.drain()
            self._written_bytes += len(buf)
            return len(buf)
        return await super()._awrite(buf)


class I2SPCMInput(PCMInput):
    """Capture through ``machine.I2S`` (or any object with ``readinto``)."""

    def __init__(self, i2s, format, **kwargs):
        super().__init__(format, **kwargs)
        self._i2s_factory = i2s
        self._i2s = None
        self._async_stream = None

    @property
    def i2s(self):
        return self._i2s

    def _open(self):
        self._i2s = _resolve(self._i2s_factory)
        if hasattr(self._i2s, "open"):
            self._i2s.open()

    def _close(self):
        i2s = self._i2s
        self._i2s = None
        self._async_stream = None
        _close_i2s(i2s)

    def _readinto(self, buf):
        return self._i2s.readinto(buf)

    async def _areadinto(self, buf):
        if sys.implementation.name == "micropython":
            if self._async_stream is None:
                self._async_stream = asyncio.StreamReader(self._i2s)
            return await self._async_stream.readinto(buf)
        return await super()._areadinto(buf)


def pcm_out(i2s, format, **kwargs):
    """Build an :class:`I2SPCMOutput` around *i2s* (instance or factory).

    ``wire=`` (the board's :class:`~audiodev.I2SWire`) and ``audio_power=``
    (its power role) are what let the audio pump take the peripheral over on
    esp32. Leave them out and the board plays the old way.
    """
    return I2SPCMOutput(i2s, format, **kwargs)


def pcm_in(i2s, format, **kwargs):
    """Build an :class:`I2SPCMInput` around *i2s* (instance or factory)."""
    return I2SPCMInput(i2s, format, **kwargs)
