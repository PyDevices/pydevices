# castdisplay

What each module in [castdisplay](../guides/cast-to-a-tv.md) holds, what its
displays take, and how each way of casting does on each runtime.

## Modules

| Module | What it holds | Runs on |
|---|---|---|
| `castdisplay.cast_display` | `CastDisplay`: Miracast to a Roku or a Windows laptop, registered as the `cast` display backend | ESP32-P4 with `castif`; CPython with ffmpeg |
| `castdisplay.hls_display` | `HlsDisplay`: live HLS, registered as `hls` | ESP32-P4 with `castif`; CPython with ffmpeg |
| `castdisplay.roku_companion` | `RokuCompanion`, `RokuDisplay` (registered as `roku`), `RokuDisplayWrapper`, `RokuAudioSink`: the PyDevices Companion channel | anything with sockets; `RokuDisplay` needs `pngio` |
| `castdisplay.roku_cast` | `RokuScreen`: a Roku's power, keys and inputs, and a Miracast cast to it that blocks or runs in the background | ESP32-P4 with `castif` to cast; TV control with gallery's `roku_engine` |
| `castdisplay.micecast` | `Session`: the Wi-Fi Display session over MS-MICE and RTSP | MicroPython, CPython |
| `castdisplay.castfast` | the `castif` task's Python side: `make_caster`, `CastifStreamer`, `PumpFeed`, `TapFeed`, `pump_out` | ESP32-P4 with `castif` |
| `castdisplay.pycast` | `castif` on CPython: `FfmpegCaster`, `FfmpegStreamer`, `TsMux`, `CastAudio`, `CastAudioOut` | CPython with ffmpeg |
| `castdisplay.uibcinput` | `UibcInput`: a laptop's mouse, keys, touchscreen and remote as touches and keys | MicroPython, CPython |

## CastDisplay

`CastDisplay(sink, width=720, height=720, kind="windows", canvas=None, fps=30,
bitrate=3_000_000, name="PyDevices P4", log=None, audio=None,
audio_format=(24000, 2), audio_loop=False)`

| Argument | Meaning |
|---|---|
| `sink` | the TV's or laptop's address |
| `width`, `height` | the picture, multiples of 16 |
| `kind` | `"windows"` (Wireless Display app) or `"roku"` (Screen mirroring) |
| `canvas` | `(w, h)` of the stream, at least the picture, which is centred on black |
| `fps`, `bitrate` | the stream's |
| `name` | what the sink lists the cast as |
| `log` | where session messages go (default: nowhere) |
| `audio` | `None` for silence; `True` for the app's sound; on a desktop, a file, URL or list of ffmpeg input arguments |
| `audio_format` | `(rate, channels)` the P4's audio pump drives, for `audio=True` |
| `audio_loop` | play a desktop's audio file over and over |

`stats()` returns frames encoded and sent, `fps`, `sessions` and
`idr_requests` (the keyframes the sink asked for after a loss). `pcm_out()` is
a speaker on the cast, `touch_read()` and `keypad_read()` are the laptop's
input, and `close()` ends the cast and gives the encoder back. The session
rejoins by itself when the sink goes away.

## HlsDisplay

`HlsDisplay(tv=None, width=1280, height=720, fps=20, bitrate=2_000_000,
port=8090, segments=4, log=print)`

`tv` is a Roku's address, woken and told to play the stream through the
Companion channel, or `None` to serve only. `url` is the playlist's address.
The playlist lists `segments` one-second segments; a player starts at the
oldest, so each adds about a second of delay. `stats()` and `close()` work as
in `CastDisplay`.

## Each method on each runtime

Frames a second reaching the screen, for testris and for the LVGL
`lv_test_timer`.

| Runtime | Companion channel | Miracast to a Roku | Miracast to Windows | HLS |
|---|---|---|---|---|
| `python` (Linux) | 11.0, 9.1 | 30, 30 | 30 | plays |
| `python.exe` (Windows) | closes, 13.6 | 30, 30 | 30 | plays |
| `micropython` (unix) | 13.4, 11.3 | no H.264 | no H.264 | no H.264 |
| `micropython.exe` (Windows) | 7.7, 7.8 | no H.264 | no H.264 | no H.264 |
| ESP32-P4 4" panel | 2.2, 2.1 | -, 29 | 30 | plays |
| ESP32-S3 LCD-7 | 1.8, 1.7 | no H.264 | no H.264 | no H.264 |

A dash is a figure not measured. On Windows CPython, testris over the
Companion channel closes the cast a moment after it starts.

No H.264 is by design: desktop MicroPython and the S3 have no H.264 encoder,
so `CastDisplay` and `HlsDisplay` stop there with an error that says so.

Sound, recorded from a TV's speakers by a microphone:

| Runtime | Miracast to a Roku, app sound | Companion channel (`RokuAudioSink`) |
|---|---|---|
| `python` (Linux) | plays, no drift, no gaps | plays, 4.2 s behind |
| `python.exe` (Windows) | plays, no drift, no gaps | plays, 5.4 s behind |
| `micropython` (unix) | no H.264 | plays, 3.5 s behind |
| `micropython.exe` (Windows) | no H.264 | plays, 4.8 to 5.2 s behind |
| ESP32-P4 (the panel) | plays, no drift, no gaps | plays, 4.3 s behind |

The ESP32-P4 Wi-Fi 6 dev kit can't cast sound: its Wi-Fi barely sends while
its speaker runs, and the TV gives up on the session.
