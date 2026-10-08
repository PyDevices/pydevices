"""board_peripherals for a QT Py ESP32 Pico carrying an Adafruit Audio BFF, on CircuitPython.

Headless, like the MicroPython config beside it in board_configs/nodisplay:
there is no display, so there is no board_config.py; an app imports
board_peripherals directly.

``audio_out()`` is CircuitPython's own ``audiobusio.I2SOut`` on the BFF's pins
(BCLK A3, LRCLK A2, DATA A1). The BFF's MAX98357A amplifier takes its clock
from BCLK, so any sample rate plays; it averages left and right in hardware.
Heard working: pydevices-examples' audio_arpeggio.py, with an audiodsp
Biquad in the graph.
"""

import audiobusio
import board

PERIPHERALS = frozenset({"audio_out"})


def audio_out(*args, **kwargs):
    """The BFF's I2S output. Arguments are accepted and ignored: I2SOut plays
    whatever format each sample carries."""
    return audiobusio.I2SOut(board.A3, board.A2, board.A1)
