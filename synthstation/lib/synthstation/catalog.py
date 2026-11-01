# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Which instruments the picker shows, on which tab.

Every instrument in ``audioinstruments.ALL`` has a small module of
constants (its face) that names it and its category, so the whole list is
built without creating any of them.
"""

#: Which tab a face's first CATEGORIES entry lands on; anything else is a synth.
TABS = {"Drum": "Drums", "Piano": "Keys", "Synth": "Synths"}
TAB_ORDER = ("Drums", "Keys", "Synths")
#: The instrument picked when nothing has been saved.
DEFAULT = "electric_piano"
#: What a choice saved under an instrument's old name means now.
RENAMED = {
    "andromeda": "polya6", "arp2600": "patch2600", "b3": "tonewheel3", "clavinet": "clavichord",
    "cp70": "electric_grand70", "cs80": "poly80", "farfisa": "compact_organ", "juno106": "poly106",
    "jupiter8": "poly8", "minimoog": "mono_synth", "ms20": "duo20", "music_easel": "west_coast_synth",
    "obxa": "polyxa", "odyssey": "duosynth", "pianet": "reed_piano", "polysix": "poly6",
    "prophet5": "poly5", "rhodes": "electric_piano", "sh101": "mono101", "solina": "string_ensemble",
    "taurus": "bass_pedals", "tb303": "acid303", "vox_continental": "combo_organ", "vp330": "vocoder330",
    "wasp": "hybrid_mono", "wurlitzer": "reed_piano200a", "cr78": "rhythm78",
    "simmons_sdsv": "electronic_drums5", "tr606": "rhythm606", "tr808": "rhythm808", "tr909": "rhythm909",
}


def catalog(ai):
    """``((tab, ((module, display name), ...)), ...)`` for package *ai*.

    The tabs come in ``TAB_ORDER`` and the instruments on each sorted by
    name; an empty tab is left out.
    """
    tabs = {tab: [] for tab in TAB_ORDER}
    for name in ai.ALL:
        face = ai.load(name)
        categories = getattr(face, "CATEGORIES", ())
        tab = TABS.get(categories[0] if categories else "", "Synths")
        tabs[tab].append((name, face.DISPLAY_NAME))
    return tuple((tab, tuple(sorted(tabs[tab], key=lambda item: item[1].lower()))) for tab in TAB_ORDER if tabs[tab])


def find(entries, name):
    """``(tab, display name)`` of instrument *name* in a catalog, or ``(None, name)``."""
    for tab, items in entries:
        for module, display in items:
            if module == name:
                return tab, display
    return None, name
