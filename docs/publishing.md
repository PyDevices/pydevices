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
- `pydevices-desktop` depends on `pydevices==X.Y.Z` and on each requirement in
  [`utils/requirements.txt`](../utils/requirements.txt) (zeroconf, for `mdns`),
  and additionally copies in every module discovered under `utils/` plus the
  desktop board config directory ([`board_configs/desktop`](../board_configs/desktop/)). Utilities do not get their own
  distributions.

## Interpreters on final releases

A final release (`vX.Y.Z`) also gets fresh desktop interpreters as release
assets, built by
[`release-interpreters.yml`](../.github/workflows/release-interpreters.yml):
`micropython`, `micropython.exe`, `micropython.mjs`, `micropython.wasm` and
`circuitpython`, each carrying every PyDevices module with this release's
`pydevices` frozen in, plus an `interpreters.json` listing each file's sha256,
size and version. A dev, a, b or rc release gets none.
[`bin/fetch_interpreters.sh`](../bin/fetch_interpreters.sh) downloads the
newest set and checks it against that manifest. To rebuild without releasing,
run the workflow by hand from the Actions tab: it keeps the files as a run
artifact and attaches nothing unless you tick "attach" with a final tag. The
recipe is [`scripts/release_interpreters.sh`](../scripts/release_interpreters.sh).

### The sources are pinned

What you download from a final must be what that release built, so the
interpreters are made from fixed commits, never from a branch tip.
[`scripts/release_interpreters/sources.lock`](../scripts/release_interpreters/sources.lock)
names the commit of `micropython-pydevices` (the build script, its patches, and
its own locks for MicroPython, the toolchains and every module) and of
`lvgl-circuitpython`. `interpreters.json` records every commit that went in:
this release's `pydevices`, the two pins, the MicroPython commit, the
CircuitPython version and each module's commit, with `"pinned": true` when the
build used exactly the pins. A run that attaches always does; to try another
`micropython-pydevices` or `lvgl-circuitpython`, name it in the two inputs of a
manual run, which then attaches nothing.

**Before you cut a final, move the pins:**

```bash
python3 scripts/release_interpreters/sources.py bump
git diff scripts/release_interpreters/sources.lock   # check what moved
```

Commit that change in a pull request; its checks build all four interpreters
from the new pins. The workflow prints a warning on every run whose pin is
behind its repository's default branch, but never fails on it, because
holding a pin back is sometimes right. `bump --dry-run` shows what would move.
The interpreter versions are whatever the pinned `micropython-pydevices` builds,
so a MicroPython or CircuitPython pre-release in its locks reaches the
interpreters as it is; the manifest's `version` fields say which. The
release's notes say so too: the workflow ends them with one line naming the
MicroPython and CircuitPython the interpreters are built on, marked "(a
preview)" when either is not a release
([`notes.py`](../scripts/release_interpreters/notes.py), which reads the line
from `interpreters.json`). Attaching again replaces that line.

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

Each board config and each driver is a package of the library index that
`tools/libbuild.py` builds: a board's `manifest.py` requires its driver
packages (listed in [`drivers/drivers.toml`](../drivers/drivers.toml)) and
`pydevices`, and mip installs them as `deps` from the same index. A board with
a `tested.json` publishes to the main index with the drivers it uses; every
other one is in the index's `untested/` folder, which holds everything.
[CONTRIBUTING.md](../CONTRIBUTING.md) has the commands.

Until that index is served, a board also installs straight from GitHub with
the `package.json` beside its manifest, which `python tools/libbuild.py
installers` writes. Optional Python bus fallbacks are not pulled:
firmware-provided `i80bus`, `i2cbus` and `spibus` take precedence. `python
tools/libbuild.py check` and `installers --check` validate every board and
driver package.

## The library index

Every release also asks the library index to rebuild. A `vX.Y.Z` release, a
pre-release included, and a `palettes-vX.Y.Z` or `pdwidgets-vX.Y.Z` release
each send [PyDevices/lib](https://github.com/PyDevices/lib) a request naming
the tag. It records the tag, builds every package with `tools/libbuild.py`
from the releases it has recorded, and serves the result from GitHub Pages at
`https://pydevices.github.io/lib` (the address moves to `lib.omnipython.org`).
Unlike the mip index at `PyDevices.github.io/mip`, which only takes finals,
the library index takes pre-releases, so its `latest` can be a release
candidate. A board installs from it with
`mip.install("pydevices", index="https://pydevices.github.io/lib")`.

Boards and drivers don't wait for a release. A merge to `main` that touches
`board_configs/` (a `tested.json` included) or `drivers/` runs
[`publish-lib-boards.yml`](../.github/workflows/publish-lib-boards.yml), which
sends the library index a `boards` request naming the merge commit. The index
takes those two folders from that commit and everything else from the last
`vX.Y.Z` release, so the new board file is live a few minutes after the merge
while `pydevices` itself keeps its released version. A board's version is still
the repository's, so the file hashes in its `package.json` tell two builds
apart. The next release clears the commit. A merge that touches neither folder
sends nothing. If the combination doesn't build, the index's run fails and the
index stays as it was; the fix is another merge.

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
