# spotify_remote

LVGL touch UI for Spotify playback control, built on [sayso](../../) and
[lvgl_micropython](https://github.com/lvgl-micropython/lvgl_micropython).

Target display: LCD-7, 800x480 capacitive touch. At that size the UI uses a
Spotify-style left navigation rail, a Now Playing screen, and a persistent
bottom mini-player. The mini-player keeps Queue and Connect to Device beside
mute and an inline volume slider; elapsed and total times flank its progress
bar. Larger displays retain the roomier tab layout. Hardware-specific display
and input drivers are intentionally deferred; it runs on desktop CPython and
MicroPython (Linux and Windows) under the PyDevices stack.

## Files

| File | Role |
|------|------|
| `main.py` | Entry point: auth, playback polling, event loop |
| `spotify_ctrl.py` | sayso wrapper (no LVGL) |
| `ui.py` | LVGL widgets; root screen via `scr = lv.screen_active()` |
| `config.py` | Tunable limits (cover-art cache size, library list size) |
| `artwork_cache.py` | Downloads and caches cover art from Spotify CDN URLs |
| `image_view.py` | Small LVGL cover-art view with a placeholder fallback |
| `genre_seeds.py` | Static genre preset list when the API seed endpoint is unavailable |
| `__main__.py` | `-m spotify_remote` entry point (runs the loop itself) |
| `local_speaker.py` | Optional earful Connect speaker in the same process |
| `keyboard_test.py` | PyDevices keyboard smoke test (LVGL textarea input) |

## Prerequisites

- `sayso` package on `sys.path` (for example `~/.micropython/lib/sayso` → repo `sayso/`)
- `sayso.local.json` and `tokens.json` in **this directory** (see [Config](#config))
- Spotify app scopes: user profile, playback read/write, playlist read/write,
  library read/write, and `user-follow-read` for followed artists
- An active Spotify playback device for now-playing and transport controls
- LVGL image decoder support for the image format returned by Spotify cover art
  URLs. Spotify album art is normally JPEG; the cache also preserves PNG/BMP if
  those formats are encountered.

On startup the app compares required scopes to `tokens.json`. If scopes are
missing, it opens the Spotify authorize URL automatically (same flow as
`sayso` examples) and saves the updated token. Access tokens are also
refreshed automatically via the refresh token when they expire.

## Config

`spotify_ctrl.py` loads credentials from this app directory (via `__file__`), not
from the process cwd. Copy or symlink secrets here:

```bash
cd apps/spotify_remote
cp ../../sayso.local.json.example sayso.local.json
# edit sayso.local.json, run desktop OAuth once, then copy or link tokens.json
ln -s ../../tokens.json tokens.json   # optional: reuse repo-root tokens
```

Both files are gitignored. When a file here cannot be opened (Windows reaching a WSL symlink over
`\\wsl.localhost`), the repo-root copy is used instead.

Cover art is cached under `art_cache/` beside the app. The cache is gitignored
and reused across app restarts. Limits are set in `config.py`:

- `ART_CACHE_MAX_ITEMS` — max cover-art files on disk (oldest removed first; `0` = unlimited)
- `THUMB_CACHE_MAX_ITEMS` — max list thumbnails under `thumb_cache/` (same rules)
- `LIBRARY_LIST_LIMIT` — entries loaded per library category tab
- `BROWSE_LIST_LIMIT` — entries loaded in album and playlist browse views
- `ARTIST_ALBUMS_PAGE_LIMIT` — artist discography page size (Dev Mode max is 10)
- `QUEUE_LIST_LIMIT` — queue rows shown
- `RECENT_LIST_LIMIT` — recently played tracks shown
- `SEARCH_RESULT_LIMIT` — search results (Dev Mode max 10)
- `MAX_ROW_ACTIONS` — action chips per row before overflow

Genre presets load from `GET /recommendations/available-genre-seeds` when the
API allows it; otherwise the app uses the static list in `genre_seeds.py`.

Restart the app after changing `config.py`.

## Desktop (Linux and Windows)

Runs on CPython and MicroPython with the released PyDevices stack installed
(`pydevices-desktop` and `pydevices-lvgl` from pip on CPython; the mip desktop
board in `~/.micropython/lib` on MicroPython). `main.py` puts the repo root
and `apps/` on `sys.path` itself, so run it from the sayso repo root:

```bash
cd /path/to/sayso
micropython -X heapsize=8M apps/spotify_remote/main.py
python apps/spotify_remote/main.py           # or micropython.exe / python.exe on Windows
```

Give MicroPython an 8 MB heap. The default 2 MB runs out on larger
library pages: saved albums fail with `memory allocation failed`.

Cover art needs a JPEG decoder in LVGL: displayif's `jpegio` on MicroPython
firmware, LVGL's TJPGD on CPython. Without one the view shows
"Cover unavailable" and list rows omit thumbnails.

## Frozen into firmware

[`manifest.py`](../../manifest.py) at the repo root freezes sayso and this
app. Name this repo by path in a micropython-pydevices build, with earful and
every PyDevices module, for a `micropython.exe` (or board image) that is both
the remote and the speaker:

```bash
/home/brad/gh/pydevices/micropython-pydevices/build_mp.py --port windows --variant pydevices \
    --modules all,/home/brad/gh/bdbarnett/earful,/home/brad/gh/bdbarnett/say-so
```

Run it from any directory holding `sayso.local.json` and `tokens.json`; the art caches are
written there too:

```bash
micropython.exe -m spotify_remote earful-win
```

Use `-m spotify_remote`, not `-m spotify_remote.main`: under `-m` appdev does
not keep the app alive after the script, so the package's `__main__.py` runs
the loop itself. The PyDevices Python stack (`displaydev`, `audiodev`, …) still
loads from `~/.micropython/lib` until pydevices publishes a freeze manifest
([pydevices#75](https://github.com/PyDevices/pydevices/issues/75)).

## Playing on itself (earful)

With an interpreter that has the [earful](https://github.com/bdbarnett/earful)
usermod, the remote can also be the speaker. Give it a Connect name as the
first argument, or set `LOCAL_SPEAKER` in `config.py`:

```bash
cd /path/to/sayso
micropython.exe apps/spotify_remote/main.py earful-win
```

The process logs in with earful's saved pairing, joins your Connect devices,
and shows up in **Devices** under that name. Pick it there to play through
this machine's audio output. Everything else in the UI then controls it.
Without earful, or with no name given, the remote runs as before.

While this speaker is the one playing, the screen follows earful's own state
events: a pause, a skip, a seek or a volume change from any Spotify app shows
at once, and the remote stops polling the Web API. When playback moves to
another device, polling every 5 s takes over again. An earful build without
state events (`Device.events()`) is polled as before.

On a board with no codec (an ESP32-S3 panel), set `LOCAL_SPEAKER_OUTPUT =
"usb"` and the speaker plays through a hosted USB sound card instead, such as
a P4 that is a USB speaker (usb-device-audio). It needs the `usb-core` and
`usb-host-audio` packages in the firmware or on `/lib`, and asks for a ring of
up to 2 s (PSRAM) so UI stalls don't starve the bus. There's no resampling: the
card must offer 44.1 kHz, and if it doesn't the remote says what it does
offer and runs without a speaker.

## Hardware (ESP32 and other MCUs)

1. Flash lvgl_micropython for your board with matching `DISPLAY` and `INDEV`.
2. Copy `sayso/` and this app to the device.
3. Place `sayso.local.json` and `tokens.json` in this app directory, or
   construct auth with an in-memory refresh token (no browser OAuth on-device).
4. In `main.py`, replace the driver comment block with your display/touch init
   (bus, frame buffers, `display.init()`, touch `indev`, backlight, rotation).
5. Run `main.py` on boot or from the REPL.

Display init must complete before `SpotifyUI` is created.

## UI overview

- **Now** — cover art, track/artist/album metadata, **+PL** / **Like**,
  artist **Albums** / **Follow**, album **Save**, progress slider (drag to seek),
  volume button (bottom-right, opens vertical slider popup), transport (prev, ±15s, play/pause, next),
  shuffle/repeat chips, and status messages
- **Library** (footer) — hub with **Songs**, **Artists**, **Albums**, **Playlists**,
  **Episodes**, **Shows**, and **Audiobooks**;
  row action chips and **Load more** when lists hit the configured limit
- **Queue** — now playing plus upcoming tracks; **Now** plays immediately (remove
  from queue is not supported by Spotify)
- **Recent** — recently played tracks with standard track actions
- **Find** (header) — text search field, type chips (**Tracks**, **Artists**,
  **Albums**, **Playlists**, **Episodes**, **Shows**, **Books**), and a genre
  preset dropdown. Genres load from Spotify's API when permitted; Dev Mode falls
  back to `genre_seeds.py`. Presets use `genre:` filters for tracks and artists.
  Up to 10 results per search in Dev Mode with **Load more**
- **Device picker** — **Refresh**, device type label, and transfer playback

### Row actions (tracks)

Most track lists expose **+Q** (add to queue), **Like**, and **+PL** (add to
owned playlist). Browse views for owned playlists also show **−PL** (remove from
playlist). Album and playlist headers offer **Play**, **Shuffle**, and **Save**
where applicable.

### Navigation

Footer tabs: **Now**, **Library**, **Queue**, **Recent**. Overlay panels (browse,
picker, search, devices) use **Back** to return to the previous screen. The playlist
picker includes **+ New** to create an owned playlist.

Playback state refreshes every 5 seconds and after transport actions. Success
status messages (for example “Queued …”) clear on the next poll.

## Notes

- HTTP calls block briefly; acceptable for v1 bring-up.
- HTTP 429 (rate limit) responses show “Too many requests — wait a moment”.
- Add to Playlist and **−PL** target owned playlists only.
- Spotify's Web API has no remove-from-queue endpoint; the Queue tab offers
  **Now** (play immediately) instead.
- Library save/like uses the unified `/me/library` API (Dev Mode safe).
- Artist **Top Tracks** is not offered (removed); `GET /artists/{id}/top-tracks`
  is unavailable in Spotify Development Mode. Use **Albums** or library browse instead.
- Find supports free-text search via keyboard/textarea and genre presets from the
  dropdown. Returns at most `SEARCH_RESULT_LIMIT` results per request (10 in Dev Mode).
- Lists draw at once; row thumbnails (Spotify's smallest image) fill in one
  download at a time afterwards, and show immediately once cached. They need a
  JPEG decoder that can scale (jpegio on MicroPython); on CPython, LVGL's TJPGD
  cannot ([lvgl-python#23](https://github.com/PyDevices/lvgl-python/issues/23)),
  so rows omit thumbnails there.
- Status messages show as a toast above the footer on every screen and clear
  themselves (errors after 8 s, everything else after 4 s).
