# sayso

Small Spotify Web API client experiments for CPython, MicroPython, and CircuitPython.

The current focus is a lightweight object layer:

- Dict-backed Spotify objects
- Lazy hydration: any missing field on a fetchable type triggers `fetch_method` hydration
- Page-backed properties (`playlist.items`, `artist.albums`) call client page methods when needed
- Spec-driven class creation (`Page`, `CursorPaging`, and typed nested objects)
- Generic page navigation (`for item in page`, `page[0]`, `next_page(page)`)
- Manual bearer token, Client Credentials auth, and Authorization Code auth helpers
- Local config files for app credentials and optional write-example settings
- `SpotifyClient()` loads config and runs browser OAuth on first use when needed
- Transport functions isolated in `sayso.transport`

OAuth Authorization Code helpers include URL generation, callback parsing,
token exchange, refresh handling, PKCE helpers, and CPython interactive login
through `sayso.auth`.

## Setup

Copy the example config and add your Spotify app credentials:

```powershell
copy sayso.local.json.example sayso.local.json
```

Edit `sayso.local.json`:

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "redirect_uri": "http://127.0.0.1:8080"
}
```

Register the same `redirect_uri` in your Spotify app dashboard.

Or run the interactive setup script:

```powershell
python scripts\configure.py
```

Local files are ignored by Git:

- `sayso.local.json` — app credentials
- `tokens.json` — saved OAuth access/refresh tokens after browser login
- `examples/write_examples.json` — settings for write examples (optional)

## Quick Start

```python
from sayso import SpotifyClient

client = SpotifyClient()
user = client.me()

print(user.display_name)
print(user)
```

`print()` on a Spotify object shows its raw data as formatted JSON. The REPL
still uses the compact `repr`, for example `<PrivateUser id='...'>`.

With `sayso.local.json` in place, `SpotifyClient()` loads your app
credentials, reuses `tokens.json` when available, and runs PKCE browser login on
first use when needed.

On WSL, copy the printed authorize URL into a browser on Windows if it does
not open automatically.

You can also pass credentials or auth explicitly:

```python
from sayso import AuthorizationCodeAuth, SpotifyClient

client = SpotifyClient(
    client_id="your-client-id",
    client_secret="your-client-secret",
)

client = SpotifyClient(auth=AuthorizationCodeAuth(...))
client = SpotifyClient(access_token="...")
```

## Object Layer

Spotify objects are dict-backed wrappers generated from `SPOTIFY_OBJECT_SPECS`.
Property access reads embedded JSON first; when a field is absent on a type with
`fetch_method` (`Track`, `Album`, `Artist`, `Playlist`, and so on), the object
hydrates once via the matching `SpotifyClient` getter.

Page-backed fields use `object_by_key` and a `page_method`:

- `playlist.items` → lazy `LazyPageRef`; `total`/`href` from the stub, load on `[0]` or iteration via `playlist_items()`
- `artist.albums` → `artist_albums()` (`GET /artists/{id}/albums`)

`User` and other non-fetchable types only expose fields present in the embedding
response. Under February 2026 Dev Mode, `GET /users/{id}` is not available; use
`client.me()` for the authenticated user. See `PORTABILITY.md`.

When hydration or lazy page load fails, the object layer raises `HydrationError`
with object type, endpoint, and Dev Mode hints. The original `TransportError` is
on `.cause`.

Example navigation (no manual client calls in the chain):

```python
playlist = client.current_user_playlists()[0]
track = playlist.items[0].item
artist = track.artists[0]
album = artist.albums[0]

print(playlist.name, track.name, artist.name, album.name)
```

## Discovery Scripts

Run from the project root after `sayso.local.json` is configured. Each script
adds `os.getcwd()` to `sys.path` and calls `SpotifyClient()` with no arguments.

```powershell
python scripts\sayso_simpletest.py
python scripts\sayso_playlist_discovery.py
python scripts\sayso_album_discovery.py
python scripts\sayso_saved_discovery.py
```

| Script | Object graph exercised |
|--------|------------------------|
| `sayso_simpletest.py` | `PrivateUser` via `me()` |
| `sayso_playlist_discovery.py` | Owned playlist → `items` → track → artist → `artist.albums[0]` |
| `sayso_album_discovery.py` | Saved track → album → `tracks` paging and lazy album fields |
| `sayso_saved_discovery.py` | `SavedTrack` / `SavedAlbum` wrappers and `next_page()` |

`sayso_playlist_discovery.py` skips followed playlists (Spotify returns 403 on
`playlist_items` when the user is not the owner or a collaborator).

## Smoke Tests

After creating `sayso.local.json`:

```powershell
python scripts\smoke_client_credentials.py
python scripts\smoke_oauth.py
```

`smoke_client_credentials.py` fetches a public track with Client Credentials.
`smoke_oauth.py` refreshes or acquires a user token, then calls `/me`.

## Examples

Run examples from the project root. Most call `SpotifyClient()` and
authenticate automatically when needed.

### Read Examples

```powershell
python examples\client_credentials_track.py
python examples\page_navigation.py
python examples\custom_transport.py
python examples\refresh_token_user_profile.py
python examples\refresh_token_currently_playing.py
python examples\refresh_token_devices.py
python examples\refresh_token_queue.py
python examples\refresh_token_recently_played.py
python examples\refresh_token_top_artists.py
python examples\refresh_token_top_tracks.py
python examples\refresh_token_playlists.py
python examples\refresh_token_saved_albums.py
python examples\refresh_token_saved_tracks.py
```

`custom_transport.py` fetches available markets with Client Credentials. HTTP is
chosen automatically in `sayso.transport` from `requests` or a CircuitPython
`adafruit_requests` session.

### Playback Controls

`scripts/sayso_playback.py` is an interactive terminal demo. It prints
a key map, then loops on single keystrokes to call playback methods such as
`play()`, `pause()`, `next_track()`, `seek()`, `volume()`, and `queue()`, plus
parameterless read methods such as `me()`, `saved_tracks()`, and
`recently_played()`. Press `l` to reprint the key list. Press `Q` to exit.
Requires Premium and an active Spotify device for playback controls. Uses raw
terminal input (`termios`) and is intended for Linux/WSL/macOS terminals.

```powershell
python scripts\sayso_playback.py
```

Many API paths use descriptive method names rather than URL paths. For example,
`GET /me/tracks` is `saved_tracks()`, not `me_tracks()`. See
[Endpoint Coverage](#endpoint-coverage) to look up path-to-method mappings.

### Write Examples

Copy `examples/write_examples.json.example` to `examples/write_examples.json`.
Write examples are disabled by default. Enable them there:

```json
{
  "allow_write_examples": true,
  "playlist_id": "your-playlist-id",
  "user_id": "your-spotify-user-id",
  "playlist_cover_jpeg": "C:\\path\\to\\cover.jpg"
}
```

Then run:

```powershell
python examples\write_refresh_token_add_to_queue.py
python examples\write_refresh_token_create_playlist.py
python examples\write_refresh_token_add_playlist_track.py
python examples\write_refresh_token_set_playlist_cover.py
python examples\write_refresh_token_save_track.py
```

Optional fields in `examples/write_examples.json` include `playlist_name`,
`playlist_description`, and `track_uri`.

### Manual OAuth Examples

These examples demonstrate lower-level OAuth steps using values from
`sayso.local.json`:

```powershell
python examples\authorization_code_url.py
python examples\authorization_code_exchange.py
python examples\authorization_code_pkce_url.py
python examples\authorization_code_pkce_exchange.py
python examples\authorization_code_local_server.py
python examples\authorization_code_pkce_local_server.py
```

For the manual exchange examples, add temporary fields to
`sayso.local.json`:

```json
{
  "callback_url": "http://127.0.0.1:8080/?code=...&state=...",
  "code_verifier": "...",
  "auth_state": "sayso-pkce-example"
}
```

For most use, prefer `SpotifyClient()` instead of the manual OAuth flow.

Library code can also use `TokenCache("tokens.json")` with
`AuthorizationCodeAuth` to load and save access/refresh token data directly.

## Applications

[`apps/spotify_remote/`](apps/spotify_remote/) is an LVGL touch UI for playback
control, library browse, queue, search, and cover art. It runs on CPython and
MicroPython, Linux and Windows, on the
[PyDevices](https://github.com/PyDevices/pydevices) stack. See
[`apps/spotify_remote/README.md`](apps/spotify_remote/README.md) for setup;
`sayso.local.json` and `tokens.json` live in the app directory, not the repo
root.

## Tests

```powershell
python -m unittest discover -s tests -v
```

- `tests/test_objects.py` — offline unit tests for lazy hydration, `HydrationError`,
  page-backed properties, and `Page` behavior (no credentials or network).
- `tests/test_client.py` — offline tests for 401 retry after token refresh.
- `tests/test_transport.py` — offline transport response/error and bodyless POST tests.
- `tests/test_live.py` — live integration tests against the Spotify Web API
  (`me`, playlists, saved paging, `artist.albums`, recently played). Skipped
  when `sayso.local.json` is missing.

## Packaging

Build local source and wheel distributions with:

```powershell
python -m build
```

The wheel contains only the `sayso` runtime package. The source distribution
also includes examples, scripts, tests, and project notes. Generated draft specs
and local config/token files are excluded.

## Schema Draft Generation

`object_specs.py` is curated by hand, but a draft can be generated from Spotify's
OpenAPI schema for comparison:

```powershell
python scripts\generate_object_specs.py
```

The default output is `generated_object_specs.py`, which is ignored by Git and
kept outside the import package. YAML schemas require optional `PyYAML`; JSON
OpenAPI schemas work with the standard library.

The generator emits `CursorPaging` for cursor pages, merges hand-curated
`object_by_key` overrides (`Artist.albums`, `Playlist.items`), documents February
2026 removed paths in the output header, and does not emit per-field `fetch`
flags (hydration is driven by `fetch_method` on fetchable types).

## Endpoint Coverage

Compare `SpotifyClient` to Spotify's OpenAPI paths by parsing `sayso/client.py`:

```powershell
python scripts\endpoint_coverage.py
python scripts\endpoint_coverage.py --map
```

The report lists endpoints missing from the client, client-only paths, and (with
`--map`) each OpenAPI path with the matching `SpotifyClient` method names. For
example, `GET /me/tracks` maps to `saved_tracks()`, not a method named after
the URL path.

## Implemented Client Areas

The client currently includes object-returning methods for:

- Single and bulk tracks, albums, artists, episodes, shows, audiobooks, and chapters
- Album tracks, artist albums, related artists, playlist items/tracks, show episodes, and audiobook chapters
- Artist top tracks (unavailable in February 2026 Dev Mode; see `PORTABILITY.md`)
- Audio features, audio analysis, recommendations, search, categories, category playlists, featured playlists, and new releases
- Current playback, currently playing, queue, devices, recently played, current user, public users, and user playlists
- Saved albums, tracks, episodes, shows, audiobooks, followed artists, top artists/tracks, markets, and recommendation genres
- Saved-library membership checks, generic library URI methods, and following checks
- Save/remove saved-library items and follow/unfollow artists/users
- Create/update/follow/unfollow playlists, add/remove/replace/reorder playlist items/tracks, check playlist followers, and upload custom cover images
- `snapshot_id(result)` helper for playlist mutation responses
- Playback controls including transfer, play/pause, skip, seek, repeat, shuffle, volume, and queue add
- Write helpers accept strings or Spotify objects with matching `id`/`uri` fields where appropriate
- Generic `next_page(page)` and `previous_page(page)` navigation for Spotify paging URLs
- First-class methods for all OpenAPI paths currently reported by Spotify's schema
- Low-level HTTP helpers on `SpotifyClient` are private; the public surface is endpoint methods such as `track()`, `pause()`, and `saved_tracks()`

Some playback and user methods require a user access token from Authorization Code flow.
Some playback controls require Spotify Premium and an active device.

## Current Limitations

- Interactive browser OAuth uses CPython `http.server` and `webbrowser` when
  available; MicroPython falls back to a raw-socket callback listener (see
  `PORTABILITY.md`).
- User-specific endpoints need a user access token; Client Credentials is not enough.
- HTTP requires `requests` on CPython and MicroPython, or a CircuitPython
  `adafruit_requests` session.
- **February 2026 Dev Mode** — several endpoints are removed or return 403
  (for example `GET /users/{id}`, legacy `playlist_tracks`). Use `client.me()`
  for the current user and `playlist.items` for playlist entries. See
  `PORTABILITY.md` for details.

See `ROADMAP.md` for implemented areas, next steps, and open design questions.
See `PORTABILITY.md` for CPython, MicroPython, and CircuitPython boundary notes.
