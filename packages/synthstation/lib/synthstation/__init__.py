# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Synth Station: pick an instrument, then play it from a MIDI keyboard.

An appkit app. The picker lists audioinstruments' instruments; the one you
pick plays through the board's audio out, from every MIDI keyboard the
program can reach, with controlpanel's panel as its front panel and a live
readout of what rendering it costs. Importing this does nothing; appkit
calls ``main(scope)``.
"""

__all__ = ["main"]


def main(scope):
    """Run Synth Station on *scope*; returns the running app."""
    from .station import Station

    return Station(scope)
