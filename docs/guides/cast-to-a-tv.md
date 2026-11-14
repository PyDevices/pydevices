# castdisplay: cast an app to a TV

castdisplay puts what an app draws on a screen across the room: a Roku TV, a
Windows laptop's Wireless Display window, or VLC. Each way is a display like
any other, so an app runs on it unchanged, LVGL or not. Over Miracast the TV
gets the sound too, in time with the picture, and a laptop's mouse and
keyboard drive the app as if they were its own touch screen. No phone app,
no cloud service and no PC sits in between: an ESP32-P4 speaks Miracast,
encodes the H.264 in its own silicon and serves the video itself.

## Install

On a board, with `mip`:

```python
import mip
mip.install("castdisplay")
```

or `mip.install("github:PyDevices/pydevices/packages/castdisplay")` for the
newest code. From a checkout, put `packages/castdisplay` on `PYTHONPATH` (or
`MICROPYPATH`) beside `lib/`.

On a board, Miracast and HLS need an ESP32-P4 and firmware with `castif`,
`h264enc` and `tsmux`, which OmniPython MP's P4 builds carry. On CPython they
need [ffmpeg](https://ffmpeg.org) on the PATH, or named in the `FFMPEG`
environment variable. The Companion channel needs neither, only `pngio`.

## Which way to cast

| Method | The screen | What the screen needs | Sound | Input back | Boards | From a desktop |
|---|---|---|---|---|---|---|
| [Miracast to a Roku](#miracast-to-a-roku-tv) | Roku TV | Screen mirroring on, nothing installed | yes, 48 kHz, in sync | no: use the Companion channel for the remote | ESP32-P4 | CPython with ffmpeg |
| [Miracast to Windows](#miracast-to-a-windows-laptop) | Windows laptop | the Wireless Display app open | yes | the laptop's mouse and keyboard | ESP32-P4 | CPython with ffmpeg, from another PC |
| [The Companion channel](#the-pydevices-companion-channel) | Roku TV | the Companion channel, sideloaded once | sound or the picture, not both; seconds behind | the TV's remote | any board with Wi-Fi and `pngio` | CPython and MicroPython |
| [HLS video](#hls-video-to-a-roku-or-vlc) | Roku TV, or VLC anywhere | the Companion channel, or any HLS player | no (needs AAC) | none | ESP32-P4 | CPython with ffmpeg |

In short: Miracast for a live picture with sound, on a TV or a laptop, with
nothing installed on either. The Companion channel for a TV you play with the
remote, from any runtime and any board with Wi-Fi. HLS for one stream that a
TV and any number of VLC windows can all watch. How each one does on each
runtime, in frames a second, is in the [reference](../reference/castdisplay.md).

## Run any app on the TV

A cast display is a board config's `display_drv`. Make a folder with this
`board_config.py`, put it first on the path, and run the app:

```python
from castdisplay.cast_display import CastDisplay

display_drv = CastDisplay("192.0.2.10", 720, 720, kind="roku")
touch_read = display_drv.touch_read      # a laptop's mouse, for kind="windows"
keypad_read = display_drv.keypad_read    # and its keyboard
```

Swap the display for `HlsDisplay(tv=None)` or `RokuDisplay` to cast the other
ways. [`castdisplay_simpletest.py`](../../packages/castdisplay/examples/castdisplay_simpletest.py)
draws on an `HlsDisplay` and prints the address to open in VLC.

## Miracast to a Roku TV

Turn on **Screen mirroring** in the Roku's settings and the board mirrors to
it. No channel, no account and no pairing on the TV. `CastDisplay(...,
kind="roku")` wakes the TV first.

A 720x720 picture sits in the middle of the TV's 1280x720, at about 24 fps on
the P4; a P4 with no screen of its own casts the full 1280x720 at 18 fps.
`audio=True` puts what the board plays on the cast as 48 kHz audio on the
picture's clock, so a drum machine's hits land with its step light. From a
desktop, `audio=True` makes `display_drv.pcm_out()` the app's speaker, and
`audio="song.mp3"` casts a file, or any input ffmpeg can open given as a list
of ffmpeg arguments.

`castdisplay.roku_cast.RokuScreen` also controls the TV over its network API
(ECP, built into every Roku, with **Control by mobile apps** on): power, the
input, the volume and any key. It uses gallery's `roku_remote` example for
that when it's installed beside the package.

## Miracast to a Windows laptop

Open the laptop's **Wireless Display** app (Settings > System > Projecting to
this PC) and use `kind="windows"`. The sink can be the laptop's name, such as
`windows:my-laptop`, where the runtime's resolver knows it (Windows'
`python.exe` does; WSL doesn't, so give it the address).

This one talks back. Windows sends the laptop's mouse and keyboard to the
board (Miracast's UIBC), and `CastDisplay` turns them into touch and key
events. An app can't tell them from its own touch screen. The Wireless
Display window has to have focus: it then takes the mouse pointer and the
keys, and the Windows key gives them back.

Expect glitches on a busy 2.4 GHz network. Miracast sends its video over UDP,
so a packet Wi-Fi loses is gone, and Windows draws the damage until the next
keyframe a moment later. A quieter channel, or the board and laptop closer to
the router, means fewer. `CastDisplay.stats()` counts them as
`idr_requests`. Windows won't take a cast from itself, so from CPython the
receiver is a second PC.

## The PyDevices Companion channel

The Companion channel is a small Roku channel, sideloaded once with the TV in
developer mode. Then a program on the network can use the TV as a display,
read its remote, speak through it and play video on it, through
`castdisplay.roku_companion`:

- `RokuDisplay` is a framebuffer display whose frames show full-screen, sent
  as PNGs. At 480x270 a desktop gets 8 to 14 frames a second onto the TV, and
  a P4 about 2, the time each PNG takes to encode.
- The remote's eleven buttons arrive as key presses and releases.
- `RokuCompanion` has `say()`, `dashboard()`, `frames(url)` and `video(url)`.
- `RokuAudioSink` streams an app's sound to the TV, 3.5 to 5.5 seconds
  behind: fine for music, not for a game. The channel plays sound or shows
  frames, not both.

It's plain sockets plus `pngio`, so it needs no video encoder. OmniPython MP
firmware has `pngio` built in; on CPython it comes with `pydevices-desktop`
and needs Pillow. From WSL, give it the TV's address: SSDP discovery doesn't
cross WSL's NAT.

## HLS video to a Roku or VLC

`HlsDisplay` makes the app's screen a live video stream that anything can
watch, about ten seconds behind: right for a clock, a dashboard or a camera,
slow for a game. On the P4 a task on the second core encodes and cuts
one-second segments and serves them itself, so a busy app doesn't starve it.

```python
from castdisplay.hls_display import HlsDisplay

display_drv = HlsDisplay(tv=None)   # prints http://<board>:8090/r.../stream.m3u8
```

With a TV's address as `tv=`, the board wakes it, even from standby, and the
Companion channel plays the stream. Otherwise open the printed address in VLC
(Media > Open Network Stream). Every viewer gets the same stream. HLS is video
only: a Roku plays HLS audio only as AAC.

## Let AutoDisplay pick a cast display

Each display registers itself with the `backends` registry when its module is
imported, so a board config can ask for one by name and an app that calls
`AutoDisplay(...)` gets it:

```python
import backends
from displaydev.auto import AutoDisplay

backends.require("display", "hls", module="castdisplay.hls_display")
display_drv = AutoDisplay(1280, 720, tv=None)   # keywords go to the display
```

The names are `cast` (module `castdisplay.cast_display`, `sink=` and
`kind=`), `hls` (`castdisplay.hls_display`, `tv=`) and `roku`
(`castdisplay.roku_companion`, `tv=`). A cast display is never picked unless
something asks for it, so nothing streams to a TV by surprise.
`PYDEVICES_DISPLAY=hls` names one for a single run. The registry itself is in
the [displays guide](displays.md#write-your-own-backend).

## The Roku remote over Miracast

The Roku's remote doesn't reach the app over Miracast. The Roku offers no
input back channel, and while it mirrors, Screen Mirroring is the app in
front and gets every press. The remote works only while the app's display is
the Companion channel (`RokuDisplay`).

[How casting works](../how-it-works/casting.md) describes the Miracast session,
the encoder pipeline and the limits that come from them.
