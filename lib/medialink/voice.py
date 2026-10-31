"""Is anyone speaking? Voice activity for a hands-free floor.

:class:`VoiceActivity` takes the microphone's frames as they come and says
whether there is sound worth sending. :class:`~medialink.Intercom` uses one
to take the floor when someone starts to speak and give it back when they
stop, so nobody holds a button.

Where audiodsp's ``audiofeatures`` is built in (MicroPython firmware that
carries audiodsp, the unix port, and CPython with pydevices-audiodsp), it
decides: the speech detector beside its wake word features, which ignores
a fan or road noise that stays on. Elsewhere, CircuitPython among them, a
level gate stands in: a noise floor that follows the quiet, and sound
10 dB over it counts. The gate can't tell a voice from a door slamming;
the detector can, mostly.

Either way a frame counts for ``hold_ms`` after the last one that held
speech, so the pauses between words don't end a turn.

Both learn the room's quiet from the first frames they hear, so a frame in
which every sample is the same is passed over: that is a microphone not yet
running, not a room. An ES7210 on a P4 board sends 100 to 280 ms of it the
first time it opens after power-up, and a detector that learned the quiet
from that took the room's own hiss for 3.4 s of speech.
"""

import struct

from medialink._compat import ticks_diff, ticks_ms


class VoiceActivity:
    """Feed it 16-bit PCM, a frame at a time; ``feed()`` says whether to send.

    ``rate`` and ``channels`` are the microphone's. ``hold_ms`` is how long
    a turn lasts after the last speech. ``detector`` picks
    ``"audiofeatures"`` or ``"level"``; by default the first there is.
    """

    def __init__(self, rate=16000, channels=1, *, hold_ms=600, detector=None):
        self.rate = rate
        self.channels = channels
        self.hold_ms = hold_ms
        self._frontend = None
        if detector in (None, "audiofeatures"):
            try:
                import audiofeatures

                frontend = audiofeatures.Frontend(slices=20)
                frontend.speaking  # an audiodsp from before voice activity has none
                self._frontend = frontend
                self._features = bytearray(audiofeatures.FEATURE_SIZE * 20)
                self._flags = bytearray(20)
            except (ImportError, AttributeError):
                if detector is not None:
                    raise
        self.detector = "audiofeatures" if self._frontend is not None else "level"
        self._floor = None
        self._warm = 0
        self._heard = None
        #: The last frame's level, mean absolute sample, for a meter.
        self.level = 0

    @property
    def speaking(self):
        """True while speech was heard within ``hold_ms``."""
        return self._heard is not None and ticks_diff(ticks_ms(), self._heard) < self.hold_ms

    def feed(self, pcm):
        """Take a frame of signed 16-bit PCM. True while it is worth sending."""
        self.level = _level(pcm, self.channels)
        step = 2 * self.channels
        if bytes(pcm[step:]) == bytes(pcm[:-step]):
            # Digital silence, from a microphone still starting: not the room.
            return self.speaking
        if self._frontend is not None:
            voiced = self._voiced_frontend(pcm)
        else:
            voiced = self._voiced_level()
        if voiced:
            self._heard = ticks_ms()
        return self.speaking

    def _voiced_frontend(self, pcm):
        frontend = self._frontend
        frontend.feed(pcm, self.rate, self.channels)
        flags = self._flags
        count = frontend.readinto(self._features, flags)
        for i in range(count):
            if flags[i]:
                return True
        return False

    def _voiced_level(self):
        level = self.level
        floor = self._floor
        if floor is None:
            self._floor = level
            return False
        # The floor drops to the quiet at once and climbs back slowly, so a
        # steady noise becomes the floor in a few seconds and a voice
        # doesn't.
        if level < floor:
            floor = level
        else:
            floor += (level - floor) / 200
        self._floor = floor
        self._warm += 1
        # The first few frames only learn the floor, as audiofeatures does.
        if self._warm < 8:
            return False
        # 10 dB over the floor, and over a level near the quietest a
        # microphone gives, so hiss in a silent room isn't speech.
        return level > floor * 3.16 and level > 60

    def reset(self):
        """Forget the room: for a new microphone, or a new place."""
        if self._frontend is not None:
            self._frontend.reset()
        self._floor = None
        self._warm = 0
        self._heard = None


def _level(pcm, channels):
    """The mean absolute value of a frame, from every eighth sample."""
    count = len(pcm) // 2
    if not count:
        return 0
    step = 8 if count >= 64 else 1
    total = 0
    taken = 0
    for i in range(0, count, step):
        sample = struct.unpack_from("<h", pcm, i * 2)[0]
        total += sample if sample >= 0 else -sample
        taken += 1
    return total // taken
