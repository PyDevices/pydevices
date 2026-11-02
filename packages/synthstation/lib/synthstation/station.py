# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The app: a picker, then the instrument's control panel.

The picker lists every instrument in audioinstruments on three tabs. Pick
one and it's created at the output's rate, starts playing through the
board's audio out, and gets controlpanel's panel; EXIT on the panel goes
back to the picker. While the panel is up, MIDI from every keyboard the
program can reach plays it, and the line under the name shows what
rendering it costs.
"""

import lvgl as lv

from . import midi as _midi
from .catalog import DEFAULT, RENAMED, TAB_ORDER, catalog, find

#: How often the keyboards are read, and the instrument told to take in
#: what was played, in milliseconds.
MIDI_MS = 4
FILL_MS = 10
#: Every so many fills the app checks what the pump's render costs.
GOVERN_EVERY = 5
#: The share of a block's time the voices may take before the app caps them.
BUDGET = 0.85
#: Reads to skip after changing the cap, while the stolen voices ring out.
SETTLE = 4
#: How often the load readout and the MIDI device names are refreshed.
STATUS_MS = 500
#: How often the load is printed to the console while an instrument
#: plays, for a log of a bench session; 0 prints nothing.
LOG_MS = 5000
#: How long a pad's note sounds when there's no keyboard.
PAD_NOTE_MS = 300
#: The controllers that move the first eight macros: Sound Controllers 1
#: to 8 in the MIDI spec, which many keyboards' knobs send. Any other
#: controller goes to the instrument itself.
KNOB_CCS = (70, 71, 72, 73, 74, 75, 76, 77)

BG = 0x141518
PANEL = 0x24262B
TEXT = 0xE8E6E1
DIM = 0x8A8D93
ACCENT = 0xD8402F

#: The running app, for a console or a bench script: ``current.adapter``
#: is the instrument's adapter, ``current.parser.feed()`` plays MIDI bytes.
#: None while the app isn't open.
current = None


def _style(obj, bg=None, radius=0):
    obj.set_style_border_width(0, 0)
    obj.set_style_radius(radius, 0)
    obj.set_style_pad_all(0, 0)
    if bg is not None:
        obj.set_style_bg_color(lv.color_hex(bg), 0)
        obj.set_style_bg_opa(lv.OPA.COVER, 0)


def _label(parent, text, color=TEXT, font=None):
    label = lv.label(parent)
    label.set_text(text)
    label.set_style_text_color(lv.color_hex(color), 0)
    if font is not None:
        label.set_style_text_font(font, 0)
    return label


class Station:
    """The whole app on *scope*. ``main(scope)`` makes one."""

    def __init__(self, scope):
        self.scope = scope
        self.root = scope.root
        self.width, self.height = scope.size
        self.prefs = scope.store()
        self.inputs = None
        self.output = None
        self.adapter = None
        self.panel = None
        self.name = None
        self.loading = False
        self._filling = False
        self._fills = 0
        self._played = 0
        self._idle_us = None
        self._settle = 0
        self._timers = []
        self._knobs = {}
        self._program = None
        self._shown = None
        self._since_log = 0
        self._names = None
        try:
            import audioinstruments as ai

            from .audio import Output

            self.ai = ai
            self.output = Output(scope)
        except ImportError as e:
            self._missing("Synth Station needs the audio libraries: %s." % (e,))
            return
        self.catalog = catalog(ai)
        name = RENAMED.get(self.prefs.get("name"), self.prefs.get("name"))
        if find(self.catalog, name)[0] is None:
            name = DEFAULT
        self.prefs["name"] = name
        tab = self.prefs.get("tab")
        if tab not in TAB_ORDER:
            tab = find(self.catalog, name)[0] or self.catalog[0][0]
        self.parser = _midi.Parser(self)
        scope.on_close(self.close)
        global current
        current = self
        self._build_picker()
        self._show_tab(tab)
        self._status_timer = scope.every(STATUS_MS, self._status_tick)
        # Opening the keyboards can take a moment (a USB host starting), so
        # it happens once the picker is on the screen.
        scope.after(50, self._open_midi)

    # ---- the picker ------------------------------------------------------------

    def _missing(self, text):
        _style(self.root, BG)
        label = _label(self.root, text)
        label.set_width(self.width - 40)
        label.set_long_mode(lv.label.LONG_MODE.WRAP)
        label.center()

    def _build_picker(self):
        w, h = self.width, self.height
        _style(self.root, BG)
        picker = lv.obj(self.root)
        _style(picker, BG)
        picker.set_size(w, h)
        picker.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.picker = picker
        title = _label(picker, "SYNTH STATION", TEXT, lv.font_montserrat_24)
        title.set_pos(16, 12)
        self.midi_label = _label(picker, "MIDI: looking...", DIM, lv.font_montserrat_16)
        self.midi_label.set_long_mode(lv.label.LONG_MODE.DOTS)
        self.midi_label.set_width(w - 32)
        self.midi_label.set_pos(16, 46)
        self.notice = _label(picker, "", ACCENT, lv.font_montserrat_16)
        self.notice.set_pos(16, h - 26)
        self.notice.set_width(w - 32)
        self.notice.set_long_mode(lv.label.LONG_MODE.DOTS)

        top = 76
        tab_h = 44
        gap = 8
        self.tabs = []
        tab_w = (w - 32 - gap * (len(self.catalog) - 1)) // len(self.catalog)
        for i, (tab, items) in enumerate(self.catalog):
            button = lv.button(picker)
            _style(button, PANEL, 6)
            button.set_size(tab_w, tab_h)
            button.set_pos(16 + i * (tab_w + gap), top)
            label = _label(button, "%s  %d" % (tab, len(items)), TEXT, lv.font_montserrat_16)
            label.center()
            button.add_event_cb((lambda t: lambda e: self._show_tab(t))(tab), lv.EVENT.CLICKED, None)
            self.tabs.append((tab, button))

        grid = lv.obj(picker)
        _style(grid, BG)
        grid_y = top + tab_h + 10
        grid.set_size(w - 24, h - grid_y - 34)
        grid.set_pos(12, grid_y)
        grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        grid.set_style_pad_all(4, 0)
        grid.set_style_pad_row(8, 0)
        grid.set_style_pad_column(8, 0)
        self.grid = grid
        columns = 4 if w >= 760 else (3 if w >= 520 else 2)
        self._cell_w = (w - 24 - 8 - (columns - 1) * 8) // columns

    def _show_tab(self, tab):
        self.prefs["tab"] = tab
        for name, button in self.tabs:
            button.set_style_bg_color(lv.color_hex(ACCENT if name == tab else PANEL), 0)
        grid = self.grid
        grid.clean()
        for name, items in self.catalog:
            if name != tab:
                continue
            for module, display in items:
                button = lv.button(grid)
                _style(button, PANEL, 6)
                button.set_size(self._cell_w, 52)
                if module == self.prefs.get("name"):
                    button.set_style_border_width(2, 0)
                    button.set_style_border_color(lv.color_hex(ACCENT), 0)
                label = _label(button, display, TEXT, lv.font_montserrat_16)
                label.set_width(self._cell_w - 12)
                label.set_long_mode(lv.label.LONG_MODE.DOTS)
                label.center()
                button.add_event_cb((lambda m: lambda e: self.pick(m))(module), lv.EVENT.CLICKED, None)

    # ---- MIDI ------------------------------------------------------------------

    def _open_midi(self, _timer=None):
        self.inputs = _midi.Inputs().open()
        self._show_midi()

    def _midi_text(self):
        inputs = self.inputs
        if inputs is None:
            return "MIDI: looking..."
        if inputs.kind is None:
            if inputs.why == _midi.NO_INPUT:
                return "No MIDI keyboard: the pads play notes."
            return "No MIDI (%s): the pads play notes." % (inputs.why,)
        names = inputs.names()
        if not names:
            if inputs.kind == "usb":
                return "No MIDI keyboard: plug one into the USB host port, or play the pads."
            return "No MIDI keyboard: the pads play notes."
        return "MIDI: " + " + ".join(names)

    def has_midi(self):
        inputs = self.inputs
        return inputs is not None and inputs.kind is not None and bool(inputs.names())

    def _show_midi(self):
        text = self._midi_text()
        if text != self._names:
            self._names = text
            self.midi_label.set_text(text)
            self.midi_label.set_style_text_color(lv.color_hex(TEXT if self.has_midi() else ACCENT), 0)

    # The parser's sink: a keyboard's messages land here.

    def note_on(self, note, velocity):
        adapter = self.adapter
        if adapter is not None and not self.loading:
            adapter.note_on(note, velocity)
            self._played = 2

    def note_off(self, note):
        adapter = self.adapter
        if adapter is not None and not self.loading:
            adapter.note_off(note)

    def control(self, controller, value):
        adapter = self.adapter
        if adapter is None or self.loading:
            return
        try:
            knob = KNOB_CCS.index(controller)
        except ValueError:
            knob = -1
        if 0 <= knob < adapter.macro_count:
            # Only each knob's last value, applied once everything waiting
            # has been read: a macro change can take milliseconds, and a
            # fast sweep sends a hundred values a second.
            self._knobs[knob] = value
        else:
            adapter.instrument.control_change(controller, value)

    def bend(self, value):
        adapter = self.adapter
        if adapter is not None and not self.loading:
            adapter.instrument.pitch_bend(value)

    def program(self, number):
        self._program = number

    def _midi_tick(self, _timer=None):
        inputs = self.inputs
        if inputs is None or self.adapter is None or self.loading:
            return
        inputs.poll(self.parser)
        adapter = self.adapter
        if self._knobs:
            knobs = self._knobs
            self._knobs = {}
            for knob, value in knobs.items():
                adapter.note_cc(knob, value)
        if self._program is not None:
            number = self._program
            self._program = None
            # Only a program the instrument has: the others would be silence.
            if number in (adapter.instrument.patches or {}):
                adapter.note_program(number)

    # ---- the instrument ------------------------------------------------------

    def pick(self, name):
        """Open instrument *name* on the panel."""
        if self.loading or self.panel is not None:
            return
        self.loading = True
        self.notice.set_text("Loading %s..." % find(self.catalog, name)[1])
        # Give the screen a frame to show that before the work starts.
        self.scope.after(30, lambda t: self._load(name))

    def _create(self, name):
        import audioinstruments.panel

        adapter = audioinstruments.panel.create(name, self.output.rate, channel_count=self.output.channels)
        inst = adapter.instrument
        # Build the voices' tables now, not on the first key.
        note_map = getattr(self.ai.load(name), "NOTE_MAP", None)
        for note in ([n for n, _ in note_map] if note_map else (60,)):
            inst.note_on(note, 1)
        inst.fill()
        inst.all_notes_off()
        inst.fill()
        return adapter

    def _load(self, name):
        display = find(self.catalog, name)[1]
        try:
            adapter = self._create(name)
        except Exception as e:
            self.notice.set_text("%s didn't load: %s" % (display, e))
            self.loading = False
            return
        inst = adapter.instrument
        patch = self.prefs.get("patches", {}).get(name)
        if patch and patch in (inst.patches or {}):
            adapter.set_patch(patch)
        self.prefs["name"] = name
        self.name = name
        self._idle_us = None
        self._settle = 0
        self.adapter = adapter
        # RELOAD builds the instrument again. Nothing is played or filled
        # while it does; then the output takes the new one and lets go of
        # the old, which is deinitialised once nothing pulls it.
        reload = adapter.request_reload

        def request_reload():
            self.loading = True
            try:
                return reload()
            finally:
                self.loading = False

        adapter.request_reload = request_reload
        adapter.on_reload(self._reloaded)
        try:
            self.output.start(inst)
        except Exception as e:
            self.adapter = None
            inst.deinit()
            self.notice.set_text("No sound out: %s" % (e,))
            self.loading = False
            return
        self.notice.set_text("")
        self.picker.add_flag(lv.obj.FLAG.HIDDEN)
        shown = adapter
        if not self.has_midi():
            from .pads import NotePads, notes_for

            shown = NotePads(adapter, notes_for(self.ai.load(name)), self._pad_note)
        self.panel = self._build_panel(shown, display)
        self._shown = None
        self._since_log = 0
        self._timers = [
            self.scope.every(MIDI_MS, self._midi_tick),
            self.scope.every(FILL_MS, self._fill),
        ]
        self.loading = False
        self._status_tick()

    def _reloaded(self, new, old):
        self.output.start(new)
        old.deinit()

    def _build_panel(self, adapter, title):
        import sys

        import controlpanel

        two_wheels = False
        if getattr(sys, "platform", "") in ("linux", "darwin", "win32"):
            # Only the display_driver that opened this window: importing it
            # here would open another.
            driver = sys.modules.get("display_driver")
            if driver is not None and hasattr(driver, "set_wheel_mapping"):
                driver.set_wheel_mapping(adjust_axis="h", adjust_sign=1, navigate=True, navigate_sign=-1)
                two_wheels = True
                self._wheels = driver
        return controlpanel.build(
            adapter, screen=self.root, title=title, subtitle=None if self.has_midi() else "No MIDI",
            on_close=self.back, two_wheels=two_wheels)

    def _pad_note(self, note):
        adapter = self.adapter
        if adapter is None:
            return
        adapter.note_on(note, 100)
        self.scope.after(PAD_NOTE_MS, lambda t: self.adapter is adapter and adapter.note_off(note))

    def _fill(self, _timer=None):
        """Let the instrument take in what was played. A tick can land
        between the bytecodes of whatever the app is doing, so one that
        arrives inside another fill, or while the instrument is being
        swapped, is dropped."""
        adapter = self.adapter
        if adapter is None or self._filling or self.loading:
            return
        self._filling = True
        try:
            adapter.instrument.fill()
        finally:
            self._filling = False
        self._fills += 1
        # A new note is read again once its strike has rendered, rather than
        # waiting for the next scheduled look.
        if self._played:
            self._played -= 1
        if self._played == 1 or self._fills % GOVERN_EVERY == 0:
            self._govern(adapter.instrument)

    def _govern(self, inst):
        """Cap the voices at what the pump can render in time.

        The pump renders on a core of its own, so a chord the core can't
        keep up with doesn't slow the app, it starves the speaker: the audio
        runs behind for as long as the keys are held. Each sounding voice
        costs about the same, so from the cost of the blocks just rendered
        this works out how many fit in :data:`BUDGET` of a block's time and
        sets the instrument's ``voices`` to that. The extra notes steal the
        oldest instead of everything going quiet. The cap is set from the
        first sounding voice, before a chord needs it, and stays for as long
        as the instrument is loaded.
        """
        output = self.output
        cost = output.pull_us()
        if cost is None or inst.voices < 2:
            return
        if self._settle:
            # The blocks right after a cap still carry the voices it stole.
            self._settle -= 1
            return
        sounding = inst.voice_pool.sounding()
        if sounding == 0:
            self._idle_us = cost if self._idle_us is None else min(self._idle_us, cost)
            return
        idle = self._idle_us or 0
        room = BUDGET * output.block_us() - idle
        per_voice = (cost - idle) / sounding
        if per_voice > 0:
            fit = max(1, int(room / per_voice + 0.5))
            if fit < inst.voices:
                inst.voices = fit
                self._settle = SETTLE

    def back(self):
        """EXIT: stop the instrument and go back to the picker."""
        if self.loading:
            return
        self._stop_instrument()
        self.picker.remove_flag(lv.obj.FLAG.HIDDEN)
        self._show_tab(self.prefs.get("tab"))

    def _stop_instrument(self):
        for timer in self._timers:
            timer.deinit()
        self._timers = []
        adapter = self.adapter
        self.adapter = None
        if adapter is not None:
            self.prefs.setdefault("patches", {})[self.name] = adapter.patch_index
            self.output.stop()
            # After the output, so nothing pulls a deinitialised instrument.
            adapter.instrument.deinit()
        panel = self.panel
        self.panel = None
        if panel is not None:
            panel.delete()
        driver = getattr(self, "_wheels", None)
        if driver is not None:
            self._wheels = None
            driver.set_wheel_mapping(adjust_axis="v", adjust_sign=1, navigate=False, navigate_sign=1)

    # ---- the readout -----------------------------------------------------------

    def _status_text(self):
        """The display's second line: render load and underruns."""
        load, worst, underruns = self.output.load()
        if load is None:
            return "LOAD --"
        return "LOAD %d%% U%d" % (load, underruns)

    def _status_tick(self, _timer=None):
        if self.inputs is not None and self.panel is None:
            self._show_midi()
        panel = self.panel
        if panel is None or self.loading:
            return
        text = self._status_text()
        if text != self._shown:
            self._shown = text
            panel.set_status(text)
        if LOG_MS:
            self._since_log += STATUS_MS
            if self._since_log >= LOG_MS:
                self._since_log = 0
                output = self.output
                print("synthstation: %s load %s%% peak %s%% underruns %d starved %d ms" % (
                    self.name, output.load_pct, output.worst_pct, output.underruns, output.starved_ms()))

    def close(self):
        global current
        if current is self:
            current = None
        self._stop_instrument()
        if self.output is not None:
            self.output.close()
        if self.inputs is not None:
            self.inputs.close()
            self.inputs = None
