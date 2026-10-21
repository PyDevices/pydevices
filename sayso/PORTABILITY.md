# Portability Notes

`sayso` is intended to keep runtime-specific behavior narrow and easy to
replace.

## Portable Core

These modules should stay free of CPython-only imports at import time and should
run under CPython, MicroPython, and CircuitPython when the runtime has enough
memory:

- `sayso.objects`
- `sayso.object_specs`
- `sayso.client`
- `sayso.auth`

The client delegates all HTTP behavior to `sayso.transport`.

On MicroPython, import submodules directly (`from sayso.auth import ...`,
`from sayso.client import SpotifyClient`) rather than re-exports from
`sayso/__init__.py`, which may not resolve on constrained runtimes.

## Object Layer

`sayso.objects` builds spec-driven classes at import time:

- **`SpotifyObject._get()`** — returns embedded data; hydrates fetchable types once
  when a field key is absent.
- **`SpotifyObject._peek()`** — reads `_data` without hydration (used by `__repr__`,
  `Page.items`, and internal fetch helpers).
- **`Page`** — offset paging with `items`, `__iter__`, `__len__`, and `__getitem__`.
- **`CursorPaging`** — extends `Page` with a `cursors` field for cursor-based pages.
- **`object_by_key`** — returns an embedded page when present, otherwise calls a
  `page_method` on `SpotifyClient` (`artist.albums`) or a `LazyPageRef`
  (`playlist.items`). `LazyPageRef` exposes ref metadata such as `total` without
  a network call; subscripting, `len()`, and iteration load the page.
- **`HydrationError`** — raised when lazy fetch or `_fetch()` fails, with object
  type, endpoint, and Dev Mode hints. The original `TransportError` is on
  `.cause`.

Types with `fetch_method` in `object_specs.py`: `Track`, `Album`, `Artist`,
`Playlist`, `Episode`, `Show`, `Audiobook`, `Chapter`. `User` intentionally has
no `fetch_method` because `GET /users/{id}` is unavailable in Dev Mode.

## Transport Boundary

`sayso.transport` owns HTTP and encoding differences:

- Automatic HTTP backend selection through `_find_requests()`
- `requests` on CPython and MicroPython
- A CircuitPython `adafruit_requests` session when `requests` is not available
- JSON request/response handling via `response_json()` (including empty success
  bodies and non-JSON error bodies)
- Binary downloads via `get_bytes()` and `response_bytes()`
- Form encoding and URL query encoding
- Raw body uploads
- Bodyless POST/PUT/PATCH/DELETE requests send `Content-Length: 0`
- Response cleanup through `close()` or `deinit()`

When `sayso.transport` is imported, it sets `requests = _find_requests()`.
Other modules can use `from sayso.transport import requests` if they need the
resolved HTTP client.

To mock HTTP in tests, replace `sayso.transport.requests` before making API
calls.

## Auth

`sayso.auth` contains OAuth mechanics and uses `sayso.transport` for network
requests. It imports only lightweight standard modules at import time. PKCE and
Basic auth helpers import optional modules inside helper functions:

- `base64` or `binascii` for Basic auth
- `hashlib` for PKCE S256 challenges
- `os.urandom` or `urandom` for PKCE verifier generation

If a runtime does not provide one of those modules, the relevant helper raises
`SpotifyAuthError`.

`sayso.auth` also contains:

- `sayso.local.json` load/save helpers
- `TokenCache` for saving OAuth tokens to `tokens.json`
- Interactive browser OAuth helpers such as `authorize_with_local_server()`

Those helpers import `json`, local file I/O, `http.server`, `socket`/`usocket`,
or `webbrowser` only when they run. `wait_for_oauth_callback()` uses
`http.server` when available and falls back to `wait_for_oauth_callback_socket()`
otherwise. On constrained devices, construct `AuthorizationCodeAuth` or
`SpotifyClient` directly with in-memory tokens instead.

## Config-Based Client

`SpotifyClient()` with no credentials reads `sayso.local.json`, reuses
`tokens.json` when available, and runs interactive browser OAuth on first use
when needed. That path is intended for CPython development workflows, examples,
scripts, and live tests.

Portable applications can call `SpotifyClient(...)` directly with explicit
credentials, auth, or access tokens instead.

## CPython-Only Workflows

The following areas are development or desktop workflows and are not required on
embedded runtimes:

- `scripts/`
- `tests/`
- examples that load `sayso.local.json` or call `SpotifyClient()` with no args
- `scripts/sayso_playback.py` (raw terminal keyboard input)
- examples that load `examples/write_examples.json`

Portable applications can still use the core client, auth, transport, and object
layers without the local config file or interactive OAuth helpers.

## Runtime Validation

| Runtime | Environment | Status |
|---------|-------------|--------|
| CPython | Linux / WSL / desktop | Primary development target |
| MicroPython | Linux (UNIX port) | Validated with discovery scripts and `apps/spotify_remote` (pydisplay) |
| MicroPython | Embedded hardware | Not yet validated |
| CircuitPython | Embedded hardware | Not yet validated |

On embedded targets, pass credentials and tokens explicitly to `SpotifyClient`
or `AuthorizationCodeAuth` rather than relying on `sayso.local.json`,
browser OAuth, or `tokens.json` in the project root.

Suggested hardware smoke commands (from the repo root on the device):

```text
micropython scripts/sayso_simpletest.py
micropython scripts/sayso_playlist_discovery.py
```

CircuitPython requires `wifi`, `socketpool`, `ssl`, and `adafruit_requests` for
HTTP. Copy the `sayso` package and supply a pre-obtained access or refresh token.

## Client and Token Conventions

Object hydration uses a **global client** via `set_client()` / `get_client()`.
`SpotifyClient(auto_set=True)` registers itself by default. Per-object client
references are not planned.

`TokenCache` and the default `tokens.json` path are sufficient for development.
A configurable token base directory is not planned.

## Spotify Web API (February 2026 Dev Mode)

Spotify restricted Development Mode apps starting February 2026. See Spotify's
[February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
for the authoritative list.

Practical impact on `sayso`:

- **`GET /me`** — use `client.me()` for the authenticated user's profile.
- **`GET /users/{id}`** — removed for Dev Mode; `client.user()` may return 403.
  Do not set `fetch_method` on `User`; nested `User` stubs (for example
  `playlist_item.added_by`) only expose fields present in the embedding response.
- **`GET /playlists/{id}/tracks`** — removed; use `playlist.items` (backed by
  `playlist_items` / `GET /playlists/{id}/items`).
- **Followed playlists** — `playlist_items` returns 403 when the user is not the
  owner or a collaborator. Filter to owned playlists or handle `TransportError`.
- **Lazy hydration** — missing fields on fetchable types (`Track`, `Album`,
  `Artist`, `Playlist`, and so on) trigger `fetch_method` hydration. Types
  without `fetch_method` (`User`, `Page`, wrappers) never call the network from
  property access.
- **`artist.albums`** — backed by `artist_albums()`; the first album in the
  artist discography is not necessarily the album on the track that led to the
  artist.

`client.user()` and other removed paths remain on `SpotifyClient` for callers
that run under Extended Quota or future API tiers, but hobby/Dev Mode apps should
treat them as unavailable.
