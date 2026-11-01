# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Pads that play notes, for when there's no keyboard.

:class:`NotePads` stands between the panel and the instrument's adapter.
Bank A's sixteen pads become notes: a drum machine's voices, or two octaves
of a C major scale. The instrument's patches move up to bank B onwards, so
they're still a press away.
"""

PADS = 16
#: Two octaves of C major from C3, for anything that isn't a drum machine.
SCALE = (48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74)
NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note):
    return "%s%d" % (NAMES[note % 12], note // 12 - 1)


def notes_for(face):
    """``((note, label), ...)`` for bank A: a kit's voices, or the scale."""
    note_map = getattr(face, "NOTE_MAP", None)
    if note_map:
        return tuple((note, label) for note, label in tuple(note_map)[:PADS])
    return tuple((note, note_name(note)) for note in SCALE)


class NotePads:
    """The panel's adapter, with bank A playing *notes*.

    *adapter* is the instrument's own adapter. *play(note)* sounds a note
    for a pad press; everything else passes straight through, with patch
    numbers moved up a bank each way.
    """

    def __init__(self, adapter, notes, play):
        self.adapter = adapter
        self.notes = notes
        self._play = play
        self._listeners = []
        labels = [label for _, label in notes]
        self._labels = labels + ["-"] * (PADS - len(labels))
        adapter.on_external_change(self._relay)

    # ---- what the panel reads ------------------------------------------------

    @property
    def script_name(self):
        return self.adapter.script_name

    @property
    def macro_labels(self):
        return self.adapter.macro_labels

    @property
    def macro_count(self):
        return self.adapter.macro_count

    @property
    def macro_values(self):
        return self.adapter.macro_values

    @property
    def patches(self):
        return self._labels + list(self.adapter.patches)[: 128 - PADS]

    @property
    def patch_index(self):
        return self.adapter.patch_index + PADS

    @property
    def bypass(self):
        return self.adapter.bypass

    @bypass.setter
    def bypass(self, value):
        self.adapter.bypass = value

    @property
    def engine_ready(self):
        return self.adapter.engine_ready

    @property
    def engine_error(self):
        return self.adapter.engine_error

    # ---- what the panel calls ------------------------------------------------

    def set_macro(self, index, value):
        self.adapter.set_macro(index, value)

    def set_patch(self, index):
        if index < PADS:
            if index < len(self.notes):
                self._play(self.notes[index][0])
            return
        self.adapter.set_patch(index - PADS)

    def set_bypass(self, enabled):
        self.adapter.set_bypass(enabled)

    def request_reload(self):
        self.adapter.request_reload()

    def on_external_change(self, callback):
        self._listeners.append(callback)

    def _relay(self, kind, index, value):
        if kind == "patch":
            index += PADS
            value += PADS
        for listener in self._listeners:
            listener(kind, index, value)
