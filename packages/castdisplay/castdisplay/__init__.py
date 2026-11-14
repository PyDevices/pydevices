# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show what an app draws on a screen across the room: a TV, a PC or a video player.

Each display is an ``FBDisplay``, so a board config can make one its
``display_drv`` and any app runs on it unchanged:

- ``castdisplay.cast_display.CastDisplay``: Miracast to a Roku's Screen
  mirroring or a Windows PC's Wireless Display app, about a frame behind, with
  the PC's mouse and keyboard coming back as touches and keys.
- ``castdisplay.hls_display.HlsDisplay``: live HLS for VLC, any HLS player or a
  Roku running the PyDevices Companion channel, about ten seconds behind.
- ``castdisplay.roku_companion.RokuDisplay``: frames shown by the PyDevices
  Companion channel on a Roku.

On an ESP32-P4 the stream is the firmware's ``castif`` task; on CPython,
ffmpeg encodes. Each module is imported on its own, so this package imports
nothing until you name one.
"""
