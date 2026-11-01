# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A stand-in adapter: an instrument with patches and macros, and no sound.

It keeps the same contract a real one does, so the panel can be built,
driven and tested anywhere. ``host_program`` and ``host_parameter`` play
the part of a host or a sequencer changing things from outside.
"""

MACRO_LABELS = (
    "Cutoff", "Resonance", "Env Amt", "Drive",
    "Attack", "Decay", "Sustain", "Release",
    "LFO Rate", "LFO Depth", "Detune", "Sub Osc",
    "Chorus", "Delay", "Reverb", "Volume",
)

_NAMES = (
    "Init", "Fat Bass", "Acid Line", "Rubber Sub", "Glass Keys", "Warm Pad",
    "Brass Stab", "Sync Lead", "Pluck Box", "Choir Air", "Wobble", "Bell Tree",
    "Dark Drone", "Hoover", "Soft Saw", "Zap Perc", "Tape Strings", "Organ 7",
    "Ice Arp", "Saw Swarm", "Noise Hit", "Mono Grit", "Detroit", "Sine Sub",
    "Vox Formant", "Clav Funk", "Juno Pad", "Laser", "Duck Bass", "Hollow",
    "Ring Mod", "Dust Keys", "Space Lead", "Pulse 25", "Rave Stab", "Mellow",
    "Metal Bell", "Big Room", "Lo-Fi Pad", "Last Light",
)


def _patch_values(index):
    """Sixteen repeatable values for patch *index*, spread over the range."""
    values = []
    seed = 2654435761 * (index + 7) & 0xFFFFFFFF
    for _ in range(16):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        values.append((seed >> 8) % 128)
    return values


class MockAdapter:
    """An adapter with *patch_count* patches and *macro_count* labelled macros.

    *echo* says whether a patch change reports each macro it moved, the way
    an engine does; with False it only reports the patch, the way a simpler
    adapter might, and the panel must still follow.
    """

    def __init__(self, name="Demo Synth", patch_count=40, macro_count=16, echo=True):
        self.script_name = name
        self.macro_labels = list(MACRO_LABELS[:macro_count])
        self.macro_count = macro_count
        self.patches = [_NAMES[i] if i < len(_NAMES) else "Patch %03d" % (i + 1) for i in range(patch_count)]
        self.patch_index = 0
        self.macro_values = _patch_values(0)
        self.bypass = False
        self.engine_ready = True
        self.engine_error = 0
        self.echo = echo
        self.edits = []
        self.reloads = 0
        self._listeners = []

    def on_external_change(self, callback):
        self._listeners.append(callback)

    def _notify(self, kind, index, value):
        for listener in self._listeners:
            listener(kind, index, value)

    def _load(self, index):
        for macro, value in enumerate(_patch_values(index)):
            if self.macro_values[macro] == value:
                continue
            self.macro_values[macro] = value
            if self.echo:
                self._notify("macro", macro, value)

    # ---- the panel's calls ----

    def set_macro(self, index, value):
        self.macro_values[index] = value
        self.edits.append(("macro", index, value))

    def set_patch(self, index):
        self.patch_index = index
        self.edits.append(("patch", index, index))
        self._load(index)

    def set_bypass(self, enabled):
        self.bypass = bool(enabled)
        self.edits.append(("bypass", 0, self.bypass))

    def request_reload(self):
        self.reloads += 1

    def tick(self):
        pass

    def close_all(self):
        pass

    # ---- the outside world ----

    def host_program(self, index):
        """A host or sequencer picks patch *index*: patch first, then macros."""
        if index == self.patch_index:
            return
        self.patch_index = index
        self._notify("patch", index, index)
        self._load(index)

    def host_parameter(self, index, value):
        """A host's automation moves macro *index* to *value*."""
        if self.macro_values[index] == value:
            return
        self.macro_values[index] = value
        self._notify("macro", index, value)
