# How casting works

This is what happens under the [castdisplay guide](../guides/cast-to-a-tv.md):
the Miracast session, the encoder on the board, how sound joins the picture,
and the limits that come from them.

## The Miracast session

Miracast here is Wi-Fi Display over infrastructure (Microsoft's MS-MICE): the
board and the screen are on the same Wi-Fi network, not on a direct link.
`castdisplay.micecast` runs the session in Python with one poll loop and no
threads: MICE on TCP 7250, then the Wi-Fi Display RTSP exchange on 7236, then
RTP over UDP from the server port it advertised (Windows opens its firewall
for that port only). A Roku needs MICE's Session Request first, and answers
an early capability query with an error, so the session waits for the sink's
own OPTIONS before asking.

Once the sink says PLAY, the stream is a C task on the P4's core 0, the
firmware's `castif`. It converts the framebuffer with the PPA, encodes H.264
in hardware with [`h264enc`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/h264enc),
muxes MPEG-TS with [`tsmux`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/tsmux)
and sends it over RTP, with the audio as 48 kHz LPCM on the same clock.
Python only answers keepalives, forwards the sink's keyframe requests and
draws. `castdisplay.castfast` is the Python side of that task.

On CPython, `castdisplay.pycast` stands in for `castif`: ffmpeg encodes the
H.264, and Python muxes the same MPEG-TS and sends the same RTP, 7 TS packets
to a datagram, byte for byte what the P4 sends. Windows' receiver checks the
stream strictly, so matching a stream it's known to accept matters. A test
compares pycast's muxer with `castif`'s output.

## Input from a laptop

Windows sends the laptop's mouse, keyboard, touchscreen and remote over
Miracast's back channel (UIBC) as HID reports. `castdisplay.uibcinput` reads
each device's report descriptor, integrates the mouse's relative moves into a
cursor, turns clicks and fingers into touches and keys into `keys` codes, and
merges them into the board's own `touch_read` and `keypad_read`.

## Sound with the picture

On the P4, sound reaches the cast in one of two ways. `castfast.PumpFeed`
makes 10 ms blocks for the speaker and the cast at once, paced on the clock.
Or `castif` reads the audio pump's output itself (`castfast.TapFeed`), so
whatever an app plays is what the sink gets, and nothing the interpreter does
can starve it. `CastDisplay(audio=True)` uses the tap. The pump drives the
I2S wire in stereo even when the app opened a mono stream, which is why
`audio_format` defaults to `(24000, 2)`.

A 10-minute drum machine cast measured about 1 ms of A/V drift, with the
audio clock within 13 ppm of the PC's and nothing dropped on the board.

## HLS

`HlsDisplay` on the P4 hands each finished frame to `castif.Hls`, a task on
core 0 that encodes, cuts one-second segments and serves the playlist and
segments over HTTP without the interpreter. It takes a frame only once it has
started on the last one, so a fast app costs one copy per encoded frame. On
CPython, ffmpeg encodes and segments and a thread serves. Each run serves
under its own path, because a TV caches by URL.

## Limits

- No flash writes while casting. A littlefs write erases a block about every
  two minutes, which parks core 0 and stalls the cast. Log to the console
  while a cast runs.
- A whole-panel refresh flashes the P4's glass white. Draw, then refresh just
  the rows you changed (`display_drv.flush_rect`).
- Weak Wi-Fi is audible. At -70 dBm about 0.4 % of packets were lost; at
  -80 dBm several percent. Put the board near the access point.
- The P4's H.264 encoder keeps its reference rows in one block of internal
  RAM, 1,152 bytes for each 16 pixels of width, so a long-running board can
  have the memory free but in pieces. Cast early, or restart first.

## Measuring a cast

[`tools/rtp_capture.py`](../../packages/castdisplay/tools/rtp_capture.py)
records a cast on a PC, and
[`tools/ts_timing.py`](../../packages/castdisplay/tools/ts_timing.py) reports
what a sink would hear: lost packets, audio gaps, the audio and picture clocks
against the PC's, and the A/V offset second by second. Run the capture with
Windows Python when the PC is WSL, because a WSL socket doesn't see the LAN's
UDP:

```
python.exe tools/rtp_capture.py capture.bin 5004 700
python tools/ts_timing.py capture.bin
```
