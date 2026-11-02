# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Drive Synth Station through every instrument, with no window and no speaker.

Runs on CPython and on unix MicroPython. The app gets a scope whose timers
the script fires itself, a stand-in audio out that only keeps the sample it
was given (the script pulls the audio from it), and a stand-in keyboard the
script plays. For each instrument it picks it, checks the panel shows the
instrument's name, macros and patches, plays a note and checks the output
isn't silent, turns a knob and sends a program change and checks the panel
follows, then presses EXIT. Then it opens a drum machine and a synth with no
keyboard at all and plays them from the pads.

    python station_check.py [NAME ...]

Prints a line per instrument and ``RESULT OK`` at the end, or ``FAIL``
lines and exit status 1.
"""

import sys

import _headless
import lvgl as lv

WIDTH, HEIGHT = 800, 480
_headless.display(WIDTH, HEIGHT)

failures = []


def check(ok, what):
    if not ok:
        failures.append(what)
        print("FAIL", what)


# ---- stand-ins ------------------------------------------------------------


class Out:
    def __init__(self):
        self.sample = None

    def attach(self, scope):
        pass

    def play(self, sample):
        self.sample = sample

    def stop(self):
        self.sample = None

    def detach(self):
        pass

    def close(self):
        pass


class Peripherals:
    """``board_peripherals`` for a computer with an audio out and nothing else."""

    AUDIO_OUT = None
    outs = []

    @staticmethod
    def audio_out(fmt):
        out = Out()
        Peripherals.outs.append(out)
        return out


sys.modules["board_peripherals"] = Peripherals


class Timer:
    def __init__(self, ms, callback, periodic):
        self.ms = ms
        self.callback = callback
        self.periodic = periodic
        self.running = True
        self.due = Scope.now + ms

    def deinit(self):
        self.running = False


class Scope:
    now = 0

    def __init__(self):
        self.root = lv.screen_active()
        self.size = (WIDTH, HEIGHT)
        self.timers = []
        self.closes = []
        self._store = {}

    def store(self, name=None):
        return self._store

    def every(self, ms, callback):
        t = Timer(ms, callback, True)
        self.timers.append(t)
        return t

    def after(self, ms, callback):
        t = Timer(ms, callback, False)
        self.timers.append(t)
        return t

    def on_close(self, fn):
        self.closes.append(fn)

    def run(self, rounds=1):
        """Move the clock on 10 ms *rounds* times, firing what falls due.

        A periodic timer fires at most once a round, however short its
        period: the script calls this often enough.
        """
        for _ in range(rounds):
            Scope.now += 10
            for t in list(self.timers):
                if not t.running or Scope.now < t.due:
                    continue
                if t.periodic:
                    t.due = Scope.now + t.ms
                else:
                    t.running = False
                t.callback(t)
            self.timers = [t for t in self.timers if t.running]
            _headless.advance(10)


class Keyboard:
    """A MIDI input port the script plays."""

    def __init__(self):
        self.queue = bytearray()

    def send(self, *data):
        self.queue.extend(bytes(data))

    def any(self):
        return len(self.queue)

    def readinto(self, buf, nbytes=None):
        n = min(len(buf), len(self.queue))
        if not n:
            return None
        for i in range(n):
            buf[i] = self.queue[i]
        self.queue = self.queue[n:]
        return n

    def close(self):
        pass


import audiocore  # noqa: E402

from synthstation import midi, station  # noqa: E402

keyboard = Keyboard()
with_keyboard = [True]


def _open(self):
    inputs = midi.Inputs()
    if with_keyboard[0]:
        inputs.kind = "desktop"
        inputs.ports = [keyboard]
        inputs._desktop_names = ["Test Keys"]
    else:
        inputs.why = "no MIDI input on this computer"
    return inputs


midi.Inputs.open = _open


def peak_of(sample, blocks):
    peak = 0
    for _ in range(blocks):
        result, data = audiocore.get_buffer(sample)
        mv = memoryview(data)
        n = len(mv) // 2
        for i in range(0, n, 7):
            v = mv[2 * i] | (mv[2 * i + 1] << 8)
            if v >= 32768:
                v -= 65536
            if v < 0:
                v = -v
            if v > peak:
                peak = v
    return peak


def play(app, scope, note, velocity=110, pad=None):
    """Sound *note* (or press *pad*), give the instrument its turns, and pull audio."""
    if pad is None:
        keyboard.send(0x90, note, velocity)
    else:
        app.panel.choose_patch(pad)
    sample = Peripherals.outs[-1].sample
    peak = 0
    for _ in range(12):
        scope.run(2)
        peak = max(peak, peak_of(sample, 2))
    if pad is None:
        keyboard.send(0x80, note, 0)
    scope.run()
    return peak


def open_instrument(app, scope, name):
    app.pick(name)
    scope.run(5)
    return app.panel


def exercise(app, scope, name):
    import audioinstruments as ai

    face = ai.load(name)
    panel = open_instrument(app, scope, name)
    check(panel is not None, "%s: the panel opens" % name)
    if panel is None:
        print("     ", app.notice.get_text())
        return
    adapter = app.adapter
    inst = adapter.instrument
    # A name too long for the plate ends in dots: LVGL writes them into the text.
    plate = panel.title.get_text()
    if plate.endswith("..."):
        plate = plate[:-3]
    check(len(plate) >= 4 and face.DISPLAY_NAME.upper().startswith(plate), "%s: the name plate says %s (%r)" % (name, face.DISPLAY_NAME, panel.title.get_text()))
    labels = list(inst.macro_labels)[:16]
    check(list(adapter.macro_labels) == labels, "%s: the macro labels are the instrument's" % name)
    enabled = [e.enabled for e in panel.encoders]
    check(enabled == [i < len(labels) for i in range(16)], "%s: %d encoders are live" % (name, len(labels)))
    declared = inst.patches or {}
    names = [declared[i][0] if i in declared else "Patch %03d" % (i + 1) for i in range(max(declared) + 1 if declared else 0)]
    check(list(adapter.patches) == names, "%s: the pads are the instrument's patches" % name)
    note = face.NOTE_MAP[0][0] if getattr(face, "NOTE_MAP", None) else 60
    peak = play(app, scope, note)
    check(peak > 0, "%s: a note sounds (peak %d)" % (name, peak))
    knob = ""
    if labels:
        target = 17 if panel.encoders[0].value != 17 else 99
        keyboard.send(0xB0, station.KNOB_CCS[0], target)
        scope.run(3)
        knob = "knob %d" % panel.encoders[0].value
        check(panel.encoders[0].value == target, "%s: knob CC moves encoder 1 to %d (it's at %d)" % (name, target, panel.encoders[0].value))
        check(int(inst.get_macro(0)) == target, "%s: knob CC moves macro 0" % name)
    program = ""
    keys = sorted(inst.patches or {})
    if len(keys) > 1:
        want = keys[1] if adapter.patch_index != keys[1] else keys[0]
        keyboard.send(0xC0, want)
        scope.run(3)
        program = "patch %d" % panel.patch
        check(panel.patch == want, "%s: program change %d lights its pad (lit: %s)" % (name, want, panel.patch))
        check(inst.patch_index == want, "%s: program change reaches the instrument" % name)
    if shots and not SHOT[0]:
        SHOT[0] = True
        keyboard.send(0x90, 60, 100)
        scope.run(60)
        shot(shots + "/panel.raw")
        keyboard.send(0x80, 60, 0)
    print("ok  %-20s %-22s peak %5d  %d macros  %d patches  %s %s" % (
        name, face.DISPLAY_NAME, peak, len(labels), len(names), knob, program))
    app.back()
    scope.run()
    check(app.panel is None and not app.picker.has_flag(lv.obj.FLAG.HIDDEN), "%s: EXIT goes back to the picker" % name)


def shot(path):
    if path:
        _headless.refresh()
        _headless.save_raw(path, WIDTH, HEIGHT)


def main(names, shots=None):
    import audioinstruments as ai

    scope = Scope()
    app = station.Station(scope)
    scope.run(8)
    shot(shots and shots + "/picker.raw")
    check(app.inputs is not None and app.inputs.kind == "desktop", "the keyboard is open")
    for name in names or ai.ALL:
        exercise(app, scope, name)

    # With no keyboard, bank A plays notes and the patches move up a bank.
    with_keyboard[0] = False
    for fn in scope.closes:
        fn()
    scope = Scope()
    app = station.Station(scope)
    scope.run(8)
    check(not app.has_midi(), "no keyboard: the app knows")
    check("No MIDI" in app.midi_label.get_text(), "no keyboard: the picker says so")
    for name in ("rhythm808", "poly106"):
        panel = open_instrument(app, scope, name)
        check(panel is not None, "%s with no keyboard: the panel opens" % name)
        if panel is None:
            continue
        check(panel.adapter.patches[0] != app.adapter.patches[0], "%s: bank A is notes" % name)
        check(panel.subtitle.get_text().startswith("NO MIDI"), "%s: the panel says there's no keyboard" % name)
        scope.run(60)
        check((panel.display._text[1] or "").startswith("LOAD"), "%s: the display shows the load" % name)
        peak = play(app, scope, None, pad=2)
        check(peak > 0, "%s: pad 3 plays a note (peak %d)" % (name, peak))
        if len(app.adapter.patches) > 1:
            panel.choose_patch(16 + 1)
            check(app.adapter.patch_index == 1, "%s: bank B's second pad picks patch 2" % name)
        # RELOAD builds the instrument again and the output plays the new one.
        old = app.adapter.instrument
        panel.adapter.request_reload()
        scope.run(4)
        check(app.adapter.instrument is not old, "%s: RELOAD builds a new instrument" % name)
        check(Peripherals.outs[-1].sample is app.adapter.instrument.output, "%s: the output plays the new one" % name)
        peak = play(app, scope, None, pad=4)
        check(peak > 0, "%s: it sounds after RELOAD (peak %d)" % (name, peak))
        print("ok  %-20s pads play, peak %d, subtitle %r" % (name, peak, panel.subtitle.get_text()))
        app.back()
        scope.run()
    check(station.current is app, "station.current is the running app")
    for fn in scope.closes:
        fn()
    check(app.panel is None, "close takes the panel down")
    check(station.current is None, "close clears station.current")


SHOT = [False]
args = sys.argv[1:]
shots = None
if "--shots" in args:
    i = args.index("--shots")
    shots = args[i + 1]
    del args[i:i + 2]
main(args, shots)
if failures:
    print("RESULT FAIL", len(failures))
    sys.exit(1)
print("RESULT OK")
