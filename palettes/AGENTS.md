# AGENTS.md — palettes

Color palette toolkit for PyDevices (`import palettes`).

## Environment

- A folder of the pydevices repository; run the commands below from here
  (`palettes/`)
- No runtime dependencies on other PyDevices packages
- Source layout: `lib/palettes/` (import name `palettes`)

## Tests and lint

```bash
PYTHONPATH=lib python3 -m unittest discover -s tests
ruff check lib tests scripts
```

## Publishing

palettes has its own version, in `VERSION` here, apart from the pydevices
release. A pull request that changes `VERSION` (and `CHANGELOG.md`) and merges
tags `palettes-vX.Y.Z` and publishes `pydevices-palettes` to TestPyPI from the
pydevices repository's release chain. The import and mip name stay
`palettes`.
