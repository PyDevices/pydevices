# castdisplay

castdisplay is the part of OmniPython that puts what an app draws on a
screen across the room: a Roku TV or a Windows laptop over Miracast, VLC or
any HLS player, or a Roku running the PyDevices Companion channel. Each one
is a display, so an app runs on it unchanged. It casts from an ESP32-P4 with
MicroPython-compatible firmware, and from CPython with ffmpeg.

On a board, with `mip`:

```python
import mip
mip.install("castdisplay")
```

This serves a picture as live video and prints the address to open in VLC:

```python
import time

from castdisplay.hls_display import HlsDisplay

display = HlsDisplay(tv=None, width=640, height=360)
display.fill(0x001F)
display.fill_rect(40, 40, 160, 120, 0xF800)
display.show()
time.sleep(60)
```

```text
HLS at http://192.0.2.20:8090/r1234567/stream.m3u8 (and http://192.0.2.20:8090/stream.m3u8)
```

VLC shows a red box on blue, about ten seconds later.

[Docs](../../docs/guides/cast-to-a-tv.md) · [Examples](examples/castdisplay_simpletest.py) · [Roadmap](../../ROADMAP.md)

OmniPython is made by [PyDevices](https://pydevices.com).
