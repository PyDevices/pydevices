# AGENTS.md — palettes

Color palette toolkit for PyDevices (`import palettes`).

## Environment

- Python venv at `.venv` — `python3`, `ruff`
- No runtime dependencies on other PyDevices packages
- Source layout: `lib/palettes/` (import name `palettes`)

## Tests and lint

```bash
PYTHONPATH=lib python3 -m unittest discover -s tests
ruff check lib tests scripts
```

## Publishing

Commit `VERSION=X.Y.Z` and publish GitHub Release `vX.Y.Z`. The import and MIP
name stay `palettes`; the distribution is `pydevices-palettes` on both
indexes -- TestPyPI is the live channel, and the production PyPI name is a
parked mirror that trails it (0.0.12 against TestPyPI's 0.0.13 today).
Procedure: [.github/docs/publishing-automation.md](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md).

## Cursor Cloud specific instructions

The Cloud Agent update script creates the repo-root `.venv` (with `ruff`).
