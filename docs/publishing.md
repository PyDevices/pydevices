# Publishing pydevices

**The release procedure itself is org-wide and lives in one place:
[.github/docs/publishing-automation.md](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md).** It covers the standard
steps, the shared reusable workflows, the required secrets, monitoring the MIP
queue, retrying an interrupted publication, and correcting a bad release — for
every publishing repository, not just this one.

This page covers only what is specific to `pydevices`: what a release of this
repository actually produces.

One published GitHub Release named `vX.Y.Z` publishes every artifact generated
from this repository with version `X.Y.Z`. `VERSION` must already contain that
same version.

## Generated products

Exactly two TestPyPI distributions build from this repository, both assembled
by
[`dotgithub/scripts/build_pydevices_python_distributions.py`](https://github.com/PyDevices/.github/blob/main/scripts/build_pydevices_python_distributions.py):

- `pydevices` copies in every non-debris top-level module or package
  discovered under `lib/` (today `audiodev`, `displaydev`, `events`,
  `appdev`, `keys`, and `multimer`) as one distribution. There is no include
  list — adding a component under `lib/` adds it to `pydevices` on the next
  release automatically.
- `pydevices-desktop` depends on `pydevices==X.Y.Z` and additionally copies in
  every module discovered under `utils/` plus the desktop board config
  directory (`board_configs/desktop`). Utilities do not get their own
  distributions.

This replaced an earlier model that built one TestPyPI distribution per `lib/`
leaf (`pydevices-multimer`, `pydevices-displaydev`, `pydevices-events`,
`pydevices-keys`) alongside `pydevices` and `pydevices-desktop`. Republishing
eight lockstep-pinned distributions on every release didn't earn its keep —
nobody installs a single leaf on a desktop, where flash is not scarce the way
it is on a microcontroller — so the per-leaf split was retired in favor of the
two distributions above. Those leaf distributions are still visible on
TestPyPI, frozen at their last published version, `0.1.3`; they will not
receive new releases. The modules themselves were never removed — they live on
inside `pydevices`, just no longer as their own distributions.

MIP, which targets flash-constrained microcontrollers rather than desktop
`pip`, was not part of this retirement and still publishes `pydevices` as a
single package rather than per-component (see
[pydevices-examples' package names table](https://github.com/PyDevices/pydevices-examples#package-names)).

All internal TestPyPI requirements use exact `==X.Y.Z` pins. MIP meta-package
requirements intentionally resolve `latest`, while each generated manifest
records `X.Y.Z` as its own version.

## Board installers

Board `package.json` files are not published in the MIP index. Install them
directly from their raw GitHub directory. Hardware installers depend on
`pydevices` at `latest` and carry their board-specific Python drivers in their
own `urls`. Optional Python bus fallbacks are not pulled: firmware-provided
`i80bus`, `i2cbus`, `spibus`, and similar native modules take precedence.

The one desktop board installer depends on `pydevices-desktop` at `latest`.
Run `python scripts/validate_board_mip_installers.py` to validate every board
installer discovered under `board_configs/`.

## PyScript filesystem

[`pydevices-desktop.toml`](../pydevices-desktop.toml) is a generated, committed filesystem mapping that
tracks `main`. It contains the complete Python payload of the desktop package
with explicit `/lib/...` destinations. CI fails if any discovered `lib/` or
`utils/` source, or one of the fixed desktop board files, is missing or stale.

## Before you release

Confirm the generated package set is what you expect — adding or removing a
publishable entry under `lib/` or `utils/` changes the next release
automatically — then follow the standard procedure in the
[org-wide runbook](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md).

Published TestPyPI files and MIP releases are immutable in practice; publish a
new version to correct a release.
