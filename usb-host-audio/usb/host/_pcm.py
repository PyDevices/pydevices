# The hosted speaker and microphone as audiodev's PCMOutput and PCMInput.
# MIT license; Copyright (c) 2026 Brad Barnett
#
# Imported by usb.host.audio's pcm_out() and pcm_in(), not by hand. It is
# apart from audio.py so that Speaker and Microphone work on a board without
# audiodev.
import time

from audiodev import AudioFormat, PCMInput, PCMOutput

_FULL_WAIT_MS = 500     # how long a write waits for room before it gives up


class SpeakerOutput(PCMOutput):
    """A hosted USB speaker as an audiodev ``PCMOutput``: ``write()``,
    ``try_write()``, volume and mute (in software), and the rest of the
    interface every audiodev output has. Wrap it in ``audiodev.AudioOut``
    to ``play()`` a synthio or audiodsp graph through it.

    ``open()`` starts the stream and ``close()`` parks the device again.
    ``speaker`` is the ``usb.host.audio.Speaker`` underneath."""

    def __init__(self, speaker, **kwargs):
        PCMOutput.__init__(self, AudioFormat(speaker.rate, speaker.channels, speaker.bits), **kwargs)
        self.speaker = speaker
        self._packet = max(1, speaker.rate // 1000) * self.format.frame_size    # 1 ms

    def _open(self):
        self.speaker.start()

    def _close(self):
        self.speaker.stop()

    def _write(self, buf):
        # A short write is normal: the ring is finite and the bus drains it
        # in real time. Taking nothing is what PCMOutput.write() reads as a
        # dead stream, so a full ring waits here for the bus to make room,
        # and only one that stays full far longer than a packet reports 0.
        # It waits for a packet's worth of room, not just any, so a caller
        # ahead of the bus writes once a millisecond rather than spinning on
        # a few bytes at a time.
        spk = self.speaker
        want = min(len(buf), self._packet)
        deadline = time.ticks_add(time.ticks_ms(), _FULL_WAIT_MS)
        while spk.space() < want:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return 0
            time.sleep_ms(1)
        return max(0, spk.write(buf))

    def try_write(self, buf):
        """Take what fits now and return at once."""
        self.open()
        return max(0, self.speaker.write(self._prepare(buf)))

    def _drain(self):
        # The queue plays out at the stream's rate; wait that long, and a
        # little over, for it to empty.
        fmt = self.format
        per_s = fmt.rate * fmt.frame_size
        deadline = time.ticks_add(time.ticks_ms(), 200 + 1000 * self.queued_size() // per_s)
        while self.queued_size() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(2)

    def space(self):
        """Bytes a write can take now, in whole frames; 0 while closed."""
        if not self.is_open:
            return 0
        room = max(0, self.speaker.space())
        return room - room % self.format.frame_size

    def queued_size(self):
        return self.speaker.queued() if self.is_open else 0

    def is_active(self):
        return self.queued_size() > 0

    def capacity(self):
        """The ring's size in bytes; 0 while closed."""
        return self.speaker.capacity()

    def stats(self):
        """The stream's ``(packets, bytes, dropped, starved, errors, empty)``."""
        return self.speaker.stats()

    def c_sink(self):
        """The stream as a C sink for another native module (see
        ``Speaker.c_sink``). Opens the stream. Volume set here doesn't
        reach bytes written through it."""
        self.open()
        return self.speaker.c_sink()


class MicrophoneInput(PCMInput):
    """A hosted USB microphone as an audiodev ``PCMInput``. ``readinto()``
    returns what has arrived, in whole frames, and 0 when nothing has yet:
    it never waits for the bus. ``available()`` says how much is waiting.
    ``microphone`` is the ``usb.host.audio.Microphone`` underneath."""

    def __init__(self, microphone, **kwargs):
        PCMInput.__init__(self, AudioFormat(microphone.rate, microphone.channels, microphone.bits),
                          **kwargs)
        self.microphone = microphone

    def _open(self):
        self.microphone.start()

    def _close(self):
        self.microphone.stop()

    def _readinto(self, buf):
        return self.microphone.read(buf)

    def available(self):
        """Captured bytes waiting; 0 while closed."""
        return self.microphone.queued() if self.is_open else 0

    queued_size = available

    def stats(self):
        """The stream's ``(packets, bytes, dropped, starved, errors, empty)``."""
        return self.microphone.stats()
