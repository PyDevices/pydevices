# AGENTS.md — sayso

Lightweight Spotify Web API client for CPython, MicroPython and CircuitPython
(`import sayso`). Pure Python, standard library only.

## Environment

- A folder of the pydevices repository; run the commands below from here
  (`sayso/`)
- Source layout: `lib/sayso/` (import name `sayso`), `apps/spotify_remote/`
  (an LVGL touch app), `tests/`, `examples/`, `scripts/`
- No runtime dependency on other PyDevices packages, except `apps/spotify_remote/`,
  which needs LVGL and the PyDevices stack (or board drivers)

## Tests

```bash
PYTHONPATH=lib python3 -m unittest discover -s tests
```

`tests/test_objects.py`, `test_client.py` and `test_transport.py` run offline
with no credentials. `tests/test_live.py` talks to Spotify and is skipped
without `sayso.local.json` in this folder. Don't commit `sayso.local.json`,
`tokens.json` or `examples/write_examples.json`; `.gitignore` covers them.

To exercise the client without network, replace `sayso.transport.requests`
with a mock object exposing `get`/`post` (and `put`/`delete` for write paths)
before constructing `SpotifyClient`.

Build: `python3 -m build`.

## Notes

- `examples/*.py` and `scripts/smoke_client_credentials.py` need real Spotify
  credentials and a network. `scripts/sayso_*_discovery.py` need an OAuth user
  token; `sayso_playlist_discovery.py` needs an owned playlist.
- `scripts/endpoint_coverage.py` and `scripts/generate_object_specs.py` fetch
  Spotify's OpenAPI schema by default (pass a local schema path to run
  offline); the generator needs `PyYAML` (the `schema` extra) for YAML schemas.
- February 2026 Dev Mode removed `GET /users/{id}` and legacy playlist track
  endpoints; see `PORTABILITY.md`. Do not add `fetch_method` on `User`.
- Object hydration uses the global client (`set_client()`); per-object clients
  are not planned.
- MicroPython on Linux is validated; embedded MicroPython and CircuitPython on
  hardware are still outstanding (`PORTABILITY.md`, "Runtime Validation").
