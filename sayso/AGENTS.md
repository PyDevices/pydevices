# AGENTS.md

## Cursor Cloud specific instructions

`sayso` is a single, pure-Python (stdlib-only) Spotify Web API **client library**
targeting CPython/MicroPython/CircuitPython. There are no servers, databases, or
background services to run — it is a library plus `tests/`, `examples/`, `scripts/`,
and `apps/` (for example `apps/spotify_remote/`).

The startup update script installs the package editable into the system Python with
`pip install --break-system-packages -e ".[schema]"` plus `build`. (`--break-system-packages`
is used because the VM's Ubuntu system Python is PEP-668 "externally managed"; a venv
would otherwise require the `python3.12-venv` system package, which is not part of the
codebase.) Use `python3` (there is no `python` alias on the VM).

Common commands (run from repo root):
- Tests (offline object tests always run): `python3 -m unittest discover -s tests` — see `README.md` "Tests".
- Build (packaging = the library "build"): `python3 -m build` — see `README.md` "Packaging".
- Lint: none configured (no ruff/mypy/flake8 config exists despite cache entries in `.gitignore`).

Non-obvious notes:
- `tests/test_objects.py` and `tests/test_transport.py` run offline with no credentials or network.
  `tests/test_live.py` is skipped without `sayso.local.json`.
- `scripts/sayso_*_discovery.py` exercise the object graph live (OAuth user
  token). `sayso_playlist_discovery.py` requires an owned playlist.
- `examples/*.py` and `scripts/smoke_client_credentials.py` need real Spotify
  credentials (`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`, and a refresh token /
  callback URL for user-scoped flows) and live network. They are NOT needed to
  verify the environment.
- February 2026 Dev Mode removed `GET /users/{id}` and legacy playlist track
  endpoints; see `PORTABILITY.md`. Do not add `fetch_method` on `User`.
- `scripts/endpoint_coverage.py` and `scripts/generate_object_specs.py` fetch
  Spotify's OpenAPI schema from the network by default (pass a local schema path to
  run offline); `generate_object_specs.py` only needs `PyYAML` (the `schema` extra)
  for YAML schemas.
- To exercise the client without network, replace `sayso.transport.requests`
  with a mock object exposing `get`/`post` (and `put`/`delete` for write paths)
  before constructing `SpotifyClient`.
- MicroPython on Linux is validated; embedded MicroPython and CircuitPython on
  hardware are still outstanding. See `PORTABILITY.md` "Runtime Validation".
- `apps/spotify_remote/` requires LVGL and the PyDevices stack (or board
  drivers); it is not needed to verify the library on the VM.
- Object hydration uses the global client (`set_client()`); per-object clients
  are not planned.
