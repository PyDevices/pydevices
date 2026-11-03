# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
Combination board configuration for desktop, pyscript and jupyter notebook platforms.
"""

import sys

from displaydev.sdldisplay import SDLDisplay as DTDisplay

width = 320
height = 480
rotation = 0
scale = 2.0

display_drv = DTDisplay(
    width=width,
    height=height,
    rotation=rotation,
    title=f"{sys.implementation.name} on {sys.platform}",
    scale=scale,
)

host_read = display_drv.get_events

display_drv.fill(0)
