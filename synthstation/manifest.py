# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# Synth Station's MicroPython manifest. From a board's manifest.py:
#
#   include("/path/to/synthstation")
#
# It needs LVGL, audiodsp, controlpanel and audioinstruments in the
# firmware, and midiports for MIDI.

package("synthstation", base_path="lib")
