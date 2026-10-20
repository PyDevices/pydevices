## v0.0.14 (2026-09-24)

- **Behaviour change:** name tables (`WIN16` and the cube tables) are now
  ordered tuples of `(0xRRGGBB, name)` pairs, not dicts. Code that treated them
  as dicts (`WIN16[0xFF0000]`, `.keys()`, `.items()`) must change; a subclass
  that sets `_names` must set a sequence of pairs. Palette index order is now
  the same on CPython, MicroPython and CircuitPython (it was not, because the
  embedded ports do not keep dict insertion order) (#15)
- docs: palettes' manifest is included by freeze manifests, not discovered by an aggregator (#19)
- Docs: add newcomer codebase guide
- docs: the index promised HSL math the library does not have; it is HSV only
- Cold-eyes #16: a Quick Start that runs, a depth table that is true, and depth 4 picking a side
- manifest: describe the aggregator generically in the docstring
- docs theme: the header bar takes a deeper cyan
- docs theme: the Instrument palette
- docs theme: extra.css is now synced from dotgithub
- docs theme: drop the dead .color-swatch rule
- docs(theme): consolidate every color into the token blocks

## v0.0.13 (2026-08-29)

- Adopt publishing-v6 (MIP second-publication race fix)

## v0.0.13.dev2 (2026-08-29)


## v0.0.13.dev1 (2026-08-29)

- Adopt publishing-v5 and release-PR automation (Phase 1 pilot)
- ci: bump the actions group across 1 directory with 2 updates (#11)
- Use direct WebAssembly host for documentation demos

