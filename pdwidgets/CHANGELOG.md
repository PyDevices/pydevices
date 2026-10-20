## v0.0.24 (2026-09-24)

- Smoke test: skip scripts that need a sibling pydevices-examples checkout
- Docs: current releases are on TestPyPI; PyPI holds an older release parked to reserve the name (#28)
- docs: add pdwidgets newcomer guide (#27)
- README: a CircuitPython freeze can carry pdwidgets; no aggregator named
- requires-python is >=3.11: the org dropped 3.10 and this repo was missed
- Cold-eyes #25: tier every platform claim, stop denying PyPI, and make the docs checkable
- Sort pathlib within the stdlib block
- scripts: derive the package root from pyproject.toml, not src/
- manifest: describe the aggregator generically in the docstring
- docs theme: the header bar takes a deeper cyan
- docs theme: the Instrument palette
- docs theme: extra.css is now synced from dotgithub
- docs theme: drop the dead .color-swatch rule
- docs(theme): consolidate every color into the token blocks

## v0.0.23 (2026-08-29)

- Adopt publishing-v6 (MIP second-publication race fix)
- Fix documentation defects found by API audit

## v0.0.23.dev1 (2026-08-29)

- Grant publishing-v5's permission ceiling (assets + OIDC)
- Adopt publishing-v5 and release-PR automation (Phase 1 batch 1)
- ci: bump the actions group across 1 directory with 2 updates (#21)
- Use direct WebAssembly host for documentation demos

