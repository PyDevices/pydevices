# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A display that keeps its pixels in memory, with or without scroll registers."""


class FakeDisplay:
    color_depth = 16

    def __init__(self, width=80, height=48):
        self.width = width
        self.height = height
        self.mem = bytearray(width * height * 2)
        self.blits = 0
        self.shows = 0
        self.vscroll = 0

    def fill(self, c):
        for i in range(0, len(self.mem), 2):
            self.mem[i] = c & 0xFF
            self.mem[i + 1] = c >> 8

    def blit_rect(self, buf, x, y, w, h):
        self.blits += 1
        for row in range(h):
            src = row * w * 2
            dst = ((y + row) * self.width + x) * 2
            self.mem[dst : dst + w * 2] = buf[src : src + w * 2]

    def show(self):
        self.shows += 1

    def set_vscroll(self, tfa, bfa):
        self.tfa, self.bfa = tfa, bfa

    def pixel(self, x, y):
        """What the viewer sees at (x, y), after the scroll offset."""
        y = (y + self.vscroll) % (self.height - getattr(self, "bfa", 0))
        i = (y * self.width + x) * 2
        return self.mem[i] | self.mem[i + 1] << 8
