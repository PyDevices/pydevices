# sayso Roadmap

This project currently has a lightweight Spotify Web API object layer, auth helpers,
transport helpers, read methods, selected write methods, examples, and live tests.

## Implemented

- Spec-driven Spotify object classes from `SPOTIFY_OBJECT_SPECS`
- Nested object wrapping for object, object list, typed object, and page fields
- Lazy hydration from simplified objects to full objects (`_get` / `_peek`)
- `Page.__getitem__`, `CursorPaging`, and page-backed `object_by_key` properties
- `Artist.albums` and `Playlist.items` wired to client page methods
- Discovery scripts (`sayso_*_discovery.py`) for object-graph walkthroughs
- Offline object-layer unit tests in `tests/test_objects.py`
- February 2026 Dev Mode API notes in `PORTABILITY.md`
- `SpotifyObject.__str__()` pretty-prints raw object data for `print()`
- Client Credentials auth
- Authorization Code auth helpers consolidated in `sayso.auth`
- PKCE verifier/challenge helpers
- `TokenCache` for access/refresh token persistence
- `sayso.local.json` config file for app credentials
- `examples/write_examples.json` for optional write-example settings
- `SpotifyClient()` config-file bootstrap from `sayso.local.json`
- Automatic browser OAuth on first `SpotifyClient()` call when needed
- OAuth error translation into `SpotifyAuthError`
- CPython interactive OAuth flow in `sayso.auth`
- Manual callback URL parsing and lower-level OAuth examples
- Automatic HTTP backend selection (`requests` or CircuitPython `adafruit_requests`)
- JSON and raw-body write transports; non-JSON 2xx responses treated as success
- Read methods for major Spotify object families, paging, search, playback, library, and user endpoints
- Write methods for saved-library items, follows, playlists, and playback controls
- `SnapshotResult` for playlist mutation responses
- Draft schema-to-object-spec generator script
- Endpoint coverage report that parses `sayso/client.py` and compares it to OpenAPI (`--map` prints path-to-method names)
- First-class client methods for all OpenAPI paths currently reported by Spotify's schema
- Example scripts for client credentials, OAuth, user-library usage, playback controls, and guarded write calls
- Live integration tests against the Spotify Web API (playlists, saved paging, artist albums, recently played)
- 401 retry after token refresh in `SpotifyClient` request helpers
- Offline client retry tests in `tests/test_client.py`
- Lazy `Playlist.items` via `LazyPageRef` (metadata without fetch; load on access)
- `HydrationError` for contextual object-layer fetch failures
- MicroPython on Linux validated with discovery scripts and the `spotify_remote` app
- `spotify_remote` LVGL MicroPython app (`apps/spotify_remote/`)
- `spotify_remote` follows a local earful speaker through its state events (`Device.events()`): while the board is Spotify's active device the screen shows each pause, skip and seek as earful reports it, and the Web API is only asked when playback moves elsewhere
- `transport.get_bytes()` for binary downloads (for example cover art)
- Socket-based OAuth callback fallback for MicroPython
- Offline transport tests in `tests/test_transport.py`

## Good Next Steps

- Validate MicroPython and CircuitPython on embedded hardware; record results in `PORTABILITY.md`.
- Keep the schema generator aligned with hand-curated object_by_key overrides and February 2026 endpoint removals.
- Optionally deprecate removed Dev Mode client methods (`user()`, legacy `playlist_tracks()`) in docstrings and endpoint coverage output.

## Resolved Decisions

- **Global client** — keep `set_client()` / `SpotifyClient(auto_set=True)`; objects do not carry a per-instance client.
- **Token storage** — keep `TokenCache` and default `tokens.json` paths as they are.
- **Examples** — keep `examples/` as source-only in the repo for now (no packaging or docs migration yet).

## Open Design Questions

- Are there additional non-playlist mutation response shapes worth modeling?
- Should write methods validate Spotify limits such as max IDs per request, or leave that to API errors?
