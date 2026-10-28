# AGENTS.md

- Run from `sayso/`: `PYTHONPATH=lib python3 -m unittest discover -s tests`. The offline tests need no credentials; `tests/test_live.py` talks to Spotify and skips without `sayso.local.json`.
- Never commit `sayso.local.json`, `tokens.json` or `examples/write_examples.json`.
- To test without a network, replace `sayso.transport.requests` with a mock that has `get`/`post` (and `put`/`delete` for writes) before you build `SpotifyClient`.
- Spotify's Dev Mode removed `GET /users/{id}` and the legacy playlist track endpoints ([`PORTABILITY.md`](PORTABILITY.md)). Don't add `fetch_method` on `User`.
- `examples/*.py` and most `scripts/` need real credentials and a network; `scripts/endpoint_coverage.py` and `scripts/generate_object_specs.py` fetch Spotify's OpenAPI schema unless you pass a local path.
