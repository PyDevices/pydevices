# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A character LCD in the style of a 16x2 dot-matrix module.

Each line is a canvas. Setting a line repaints only the characters that
changed, so a value that turns from 100 to 101 costs one character cell:
36 small rectangles, not a whole display.
"""

import lvgl as lv

from . import font5x7


class DotMatrix:
    def __init__(self, parent, columns, lines, pitch, theme):
        self.columns = columns
        self.pitch = pitch
        self.cell_w = 6 * pitch
        self.cell_h = 8 * pitch
        self.width = columns * self.cell_w - pitch
        self.height = lines * self.cell_h + (lines - 1) * pitch
        self._on = lv.color_hex(theme["dot_on"])
        self._off = lv.color_hex(theme["dot_off"])
        self._bg = lv.color_hex(theme["display_bg"])
        self._dot = max(1, pitch - 1)
        self._rect = lv.draw_rect_dsc_t()
        self._area = lv.area_t()

        self.obj = lv.obj(parent)
        self.obj.remove_style_all()
        self.obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.obj.remove_flag(lv.obj.FLAG.CLICKABLE)
        self.obj.set_size(self.width, self.height)
        self._canvases = []
        self._bufs = []
        self._text = []
        for line in range(lines):
            buf = lv.draw_buf_create(self.width, self.cell_h, lv.COLOR_FORMAT.RGB565, 0)
            canvas = lv.canvas(self.obj)
            canvas.set_draw_buf(buf)
            canvas.set_pos(0, line * (self.cell_h + pitch))
            canvas.fill_bg(self._bg, lv.OPA.COVER)
            self._canvases.append(canvas)
            self._bufs.append(buf)
            self._text.append(None)
            self.set_line(line, "")
        self.obj.add_event_cb(self._on_delete, lv.EVENT.DELETE, None)

    def _on_delete(self, _event):
        # The canvases go with the object; their buffers are ours to free.
        for buf in self._bufs:
            try:
                buf.destroy()
            except Exception:
                pass
        self._bufs = []

    def text(self, line):
        """What line *line* shows now, padded to the display's width."""
        return self._text[line]

    def set_line(self, line, text):
        """Show *text* on line *line*, cut or padded to the display's width."""
        text = (str(text) + " " * self.columns)[: self.columns]
        old = self._text[line]
        if text == old:
            return
        canvas = self._canvases[line]
        layer = lv.layer_t()
        canvas.init_layer(layer)
        for column in range(self.columns):
            char = text[column]
            if old is None or old[column] != char:
                self._paint(layer, column, char)
        canvas.finish_layer(layer)
        self._text[line] = text

    def _paint(self, layer, column, char):
        d = self._rect
        area = self._area
        pitch = self.pitch
        dot = self._dot
        x0 = column * self.cell_w
        rows = font5x7.rows(char)
        for row in range(7):
            bits = rows[row]
            y = row * pitch
            for col in range(5):
                d.init()
                d.bg_color = self._on if bits & (16 >> col) else self._off
                d.bg_opa = 255
                if dot > 2:
                    d.radius = 1
                area.x1 = x0 + col * pitch
                area.y1 = y
                area.x2 = area.x1 + dot - 1
                area.y2 = y + dot - 1
                lv.draw_rect(layer, d, area)
