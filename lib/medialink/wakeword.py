"""A wake word, such as "Hey Jarvis", to open the hands-free floor.

:class:`WakeWord` stands where a :class:`~medialink.VoiceActivity` would in
an :class:`~medialink.Intercom`, so the intercom sends only after someone
says the word: "Hey Jarvis, the baby's awake" sends, and talk in the room
around it doesn't. After the word the floor stays open for ``listen_ms``,
time to start speaking, and then for as long as the voice activity hears
speech. When it stops, the next turn needs the word again.

:class:`MicroWakeWord` is the detector: one of ESPHome's microWakeWord
models, run by the firmware's ``tflite`` module on features from
audiodsp's ``audiofeatures``. A board whose firmware has both runs it;
CircuitPython and CPython don't, for now. It follows ESPHome's
micro_wake_word: the mean of the last few probabilities must pass the
model's cutoff, nothing fires while it warms up, and after a detection the
probabilities must fall back below the cutoff before the next.
"""

import json

from medialink.voice import VoiceActivity


class MicroWakeWord:
    """A microWakeWord model, loaded from its JSON manifest.

    ``manifest`` is the path of the model's ``.json``; its ``.tflite`` sits
    beside it. ``warm_up`` is the number of 10 ms slices below the cutoff it
    needs at the start and after each detection. ``model`` and ``frontend``
    stand in for the tflite model and the audiofeatures frontend.
    """

    def __init__(self, manifest, *, warm_up=100, model=None, frontend=None):
        with open(manifest) as f:
            info = json.load(f)
        micro = info["micro"]
        #: The wake word, as the manifest names it.
        self.name = info["wake_word"]
        if model is None:
            import tflite

            folder = manifest[: manifest.rfind("/") + 1]
            model = tflite.Model(folder + info["model"])
        if frontend is None:
            import audiofeatures

            frontend = audiofeatures.Frontend()
            self._size = audiofeatures.FEATURE_SIZE
        else:
            self._size = frontend.FEATURE_SIZE
        self.model = model
        self.frontend = frontend
        self.cutoff = int(micro["probability_cutoff"] * 255)
        self.window = micro["sliding_window_size"]
        self.stride = model.input_shape[0][1]
        self.warm_up = warm_up
        self._group = bytearray(self.stride * self._size)
        self._features = bytearray(self._size * 10)
        self.reset()

    def reset(self):
        """Start again, warming up as at the start."""
        self.frontend.reset()
        self._probabilities = [0] * self.window
        self._ignore = -self.warm_up
        self._filled = 0
        self._newest = 0

    def _fill(self, buffer, shape, dtype):
        buffer[:] = self._group

    def feed(self, pcm, rate, channels):
        """Take signed 16-bit PCM. True if the wake word ended in it."""
        size = self._size
        group = self._group
        features = self._features
        fired = False
        self.frontend.feed(pcm, rate, channels)
        while True:
            count = self.frontend.readinto(features)
            if not count:
                break
            for i in range(count):
                # Gather stride slices, then run the model on them.
                at = self._filled * size
                group[at : at + size] = features[i * size : (i + 1) * size]
                self._filled += 1
                fresh = self._filled == self.stride
                if fresh:
                    self._filled = 0
                    self._newest = self.model.predict([self._fill])[0][0][0]
                    self._probabilities = self._probabilities[1:] + [self._newest]
                # After a detection, count only the slices below the cutoff.
                if self._newest < self.cutoff:
                    self._ignore = min(self._ignore + 1, 0)
                # Fire when the window's mean passes the cutoff.
                if fresh and self._ignore >= 0 and sum(self._probabilities) > self.cutoff * self.window:
                    fired = True
                    self._probabilities = [0] * self.window
                    self._ignore = -self.warm_up
        return fired


class WakeWord:
    """Opens the floor on a wake word; a stand-in for ``VoiceActivity``.

    ``manifest`` is a microWakeWord model's JSON, as for
    :class:`MicroWakeWord`, or pass ``spotter``, anything with
    ``feed(pcm, rate, channels)`` that is True when the word ends.
    ``voice`` says when the speech after it stops; by default a
    :class:`~medialink.VoiceActivity` at ``rate``. ``listen_ms`` is how
    long the floor stays open after the word for speech to begin.
    """

    def __init__(self, manifest=None, rate=16000, channels=1, *, voice=None, listen_ms=2000, spotter=None):
        if spotter is None:
            spotter = MicroWakeWord(manifest)
        self.spotter = spotter
        self.voice = voice if voice is not None else VoiceActivity(rate, channels)
        self.rate = rate
        self.channels = channels
        self.listen_ms = listen_ms
        #: How the floor is opened, for a status line.
        self.detector = "wake word %s" % spotter.name
        #: How many times the word has been heard.
        self.heard = 0
        self._open = False
        self._samples = 0
        self._until = 0

    @property
    def level(self):
        """The last frame's level, for a meter."""
        return self.voice.level

    @property
    def speaking(self):
        """True while the floor is open: after the word, until speech stops."""
        return self._open

    def feed(self, pcm):
        """Take a frame of signed 16-bit PCM. True while it is worth sending."""
        # Time here is samples heard, so a slow loop doesn't shorten it.
        self._samples += len(pcm) // (2 * self.channels)
        speech = self.voice.feed(pcm)
        if self.spotter.feed(pcm, self.rate, self.channels):
            self.heard += 1
            self._open = True
            self._until = self._samples + self.listen_ms * self.rate // 1000
        if self._open and self._samples >= self._until and not speech:
            self._open = False
        return self._open

    def reset(self):
        """Close the floor and forget the room."""
        self.spotter.reset()
        self.voice.reset()
        self._open = False
