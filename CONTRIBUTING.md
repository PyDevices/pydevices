# Contributing

## Where things are

| Path | What it holds |
|---|---|
| [board_configs/](board_configs/) | MicroPython board configurations; CircuitPython boards are under [board_configs/cp/](board_configs/cp/). |
| [drivers/](drivers/) | Bus, display, touch, input, codec, sensor, power and storage drivers. |
| [lib/](lib/) | The libraries that make up the `pydevices` package (`displaydev`, `audiodev`, `appdev`, `multimer`, `bledev` and the rest). |
| [utils/](utils/) | Desktop helpers that ship in `pydevices-desktop` (`mdns`, `micropython`, `usdl2`, `uwin32` and more). |
| `usb-core/`, `usb-host-*/`, `usb-device-*/`, `usb-hid/` | The USB packages ([docs/guides/usb.md](docs/guides/usb.md)). |
| [palettes/](palettes/), [pdwidgets/](pdwidgets/), [appkit/](appkit/), [sayso/](sayso/), [midiports/](midiports/) | Packages that publish on their own, each with its own README. |
| [docs/](docs/) | The documentation site's source. |
| [tests/](tests/) | Unit tests for the libraries. |

## Run the tests

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v
```

[tests/README.md](tests/README.md) says what each test covers.

## Build the docs

```bash
pip install -r docs/requirements.txt
sphinx-build -W --keep-going -b html docs _site
```

`-W` fails on any warning, as Read the Docs does. The API pages under
`docs/reference/` are generated on every build; don't edit or commit them.

## Add a board or a driver

You can add a board or a driver even if nobody else has the hardware. It
publishes as soon as it merges, to the **untested** index, and moves to the
main index when someone runs its smoke test on the real board.

### A board

A board config is a folder under `board_configs/` (MicroPython; CircuitPython
configs live under [`board_configs/cp/`](board_configs/cp/) and aren't packages). Its folder name
is its package name, so pick one that says what the board is
(`esp32-s3-touch-lcd-4_3`), and that micropython-lib doesn't already use.

The folder holds `board_config.py`, usually `board_peripherals.py` (the
[board peripherals contract](docs/boards/board-contract.md)), and a
`manifest.py` saying what the package installs:

```python
metadata(description="Waveshare ESP32-S3-Touch-LCD-4.3: 800x480 RGB, GT911 touch", version="0.1.0")

require("pydevices")
require("ch422g")
require("gt911")
require("sdcard")  # micropython-lib's

module("board_config.py")
module("board_peripherals.py")
```

`require()` every driver your files import, by its package name, plus
`pydevices`, or `pydevices-desktop` for a desktop host. A package from
micropython-lib (`sdcard`, `bmi270`, `aioble`) can be required too: firmware
builds freeze it, and on stock MicroPython you install it from
micropython-lib's index first (below). List every `.py` in the folder with
`module()`.

Then write its GitHub installer, the `package.json` beside it, with
`python tools/libbuild.py installers`. Don't edit that file by hand.

### A driver

Put the module under `drivers/<kind>/` (`touch/`, `display/`, `imu/`...) and
add a table for it to [`drivers/drivers.toml`](drivers/drivers.toml), named
by the module:

```toml
[gt911]
version = "0.1.0"
description = "GT911 capacitive touch controller"
modules = ["touch/gt911.py"]
# requires = ["digitalio"]   # other driver packages it imports
```

A driver copied from micropython-lib belongs there, not here: require
upstream's package instead. When you fix a driver, bump its `version`. Every
board that uses it gets the fix; nothing else has to change.

### What CI checks

Before you push, run the same check CI runs:

```bash
python tools/libbuild.py check
python tools/libbuild.py installers --check
```

It fails on a `require()` that names no package here or in micropython-lib,
on a package name micropython-lib already uses, on a driver a board imports
but doesn't require, on a `.py` in a board folder its manifest leaves out, on
a driver file that's in no package, and on a stale `package.json`. To build
the index itself (`pip install mpy-cross` first):

```bash
python tools/libbuild.py build --out build/lib --base-url http://YOUR-PC:8000
python -m http.server -d build/lib/index 8000
```

### Installing one that isn't tested yet

Untested packages are served from the `untested` folder of the index, which
also holds everything they depend on. On the board:

```python
import mip
mip.install("sdcard")   # only if the board package requires a micropython-lib package
mip.install("esp32-s3-touch-lcd-4_3", index="http://YOUR-PC:8000/untested")
```

### Marking a board tested

With the board package installed on the board, run its smoke test:

```bash
python tools/mark_tested.py esp32-s3-touch-lcd-4_3 -d ws://my-board.local \
    --hardware "Waveshare ESP32-S3-Touch-LCD-4.3"
```

It checks that `board_config` imports, the display draws, touch reads, and
each peripheral in `PERIPHERALS` answers. `usb_device` and `can` are skipped
by default, since on some boards they take the USB console away. A role that
would put the board to sleep or reset it, such as `sleep`, is never called;
the test only checks that it is there. Skip a peripheral you can't attach (an
empty SD slot) with `--skip sdcard`. Skipped roles are written down. When every check passes it writes `tested.json` in
the board's folder. Open a pull request with that file: once it merges, the
board and the drivers it uses publish to the main index.

`-d` is anything mpftp takes (`ws://HOST`, `COM5`, `/dev/ttyACM0`). For a
desktop config, `--local path/to/micropython --path <install folder>` runs it
on a desktop interpreter.

## Releases

The release procedure itself is the same for every PyDevices repository and
is in the [organization's runbook](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md):
the steps, the shared workflows, the secrets, retrying an interrupted
publication and correcting a bad release. This section covers what a release
of this repository produces.

One published GitHub Release named `vX.Y.Z` publishes every artifact generated
from this repository with version `X.Y.Z`. `VERSION` must already contain that
same version.

### Generated products

Exactly two TestPyPI distributions build from this repository, both assembled
by
[`dotgithub/scripts/build_pydevices_python_distributions.py`](https://github.com/PyDevices/.github/blob/main/scripts/build_pydevices_python_distributions.py):

- `pydevices` copies in every top-level module or package under `lib/`
  as one distribution. There is no include
  list — adding a component under `lib/` adds it to `pydevices` on the next
  release automatically.
- `pydevices-desktop` depends on `pydevices==X.Y.Z` and on each requirement in
  [`utils/requirements.txt`](utils/requirements.txt) (zeroconf, for `mdns`),
  and additionally copies in every module discovered under `utils/` plus the
  desktop board config directory ([`board_configs/desktop`](board_configs/desktop)). Utilities do not get their own
  distributions.

### Interpreters on final releases

A final release (`vX.Y.Z`) also gets fresh desktop interpreters as release
assets, built by
[`release-interpreters.yml`](.github/workflows/release-interpreters.yml):
`micropython`, `micropython.exe`, `micropython.mjs`, `micropython.wasm` and
`circuitpython`, each carrying every PyDevices module with this release's
`pydevices` frozen in, plus an `interpreters.json` listing each file's sha256,
size and version. A dev, a, b or rc release gets none.
[`bin/fetch_interpreters.sh`](bin/fetch_interpreters.sh) downloads the
newest set and checks it against that manifest. To rebuild without releasing,
run the workflow by hand from the Actions tab: it keeps the files as a run
artifact and attaches nothing unless you tick "attach" with a final tag. The
recipe is [`scripts/release_interpreters.sh`](scripts/release_interpreters.sh).

#### The sources are pinned

What you download from a final must be what that release built, so the
interpreters are made from fixed commits, never from a branch tip.
[`scripts/release_interpreters/sources.lock`](scripts/release_interpreters/sources.lock)
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
([`notes.py`](scripts/release_interpreters/notes.py), which reads the line
from `interpreters.json`). Attaching again replaces that line.

MIP publishes `pydevices` as a
single package rather than per-component (see
[pydevices-examples' package names table](https://github.com/PyDevices/pydevices-examples#package-names)).

All internal TestPyPI requirements use exact `==X.Y.Z` pins. MIP meta-package
requirements intentionally resolve `latest`, while each generated manifest
records `X.Y.Z` as its own version.

### Board installers

Each board config and each driver is a package of the library index that
[`tools/libbuild.py`](tools/libbuild.py) builds: a board's `manifest.py` requires its driver
packages (listed in [`drivers/drivers.toml`](drivers/drivers.toml)) and
`pydevices`, and mip installs them as `deps` from the same index. A board with
a `tested.json` publishes to the main index with the drivers it uses; every
other one is in the index's `untested/` folder, which holds everything.
[Add a board or a driver](#add-a-board-or-a-driver) has the commands.

Until that index is served, a board also installs straight from GitHub with
the `package.json` beside its manifest, which `python tools/libbuild.py
installers` writes. Optional Python bus fallbacks are not pulled:
firmware-provided `i80bus`, `i2cbus` and `spibus` take precedence. `python
tools/libbuild.py check` and `installers --check` validate every board and
driver package.

### The library index

Every release also asks the library index to rebuild. A `vX.Y.Z` release, a
pre-release included, and a `palettes-vX.Y.Z` or `pdwidgets-vX.Y.Z` release
each send [PyDevices/lib](https://github.com/PyDevices/lib) a request naming
the tag. It records the tag, builds every package with [`tools/libbuild.py`](tools/libbuild.py)
from the releases it has recorded, and serves the result from GitHub Pages at
`https://pydevices.github.io/lib` (the address moves to `lib.omnipython.org`).
Unlike the mip index at `PyDevices.github.io/mip`, which only takes finals,
the library index takes pre-releases, so its `latest` can be a release
candidate. A board installs from it with
`mip.install("pydevices", index="https://pydevices.github.io/lib")`.

Boards and drivers don't wait for a release. A merge to `main` that touches
`board_configs/` (a `tested.json` included) or `drivers/` runs
[`publish-lib-boards.yml`](.github/workflows/publish-lib-boards.yml), which
sends the library index a `boards` request naming the merge commit. The index
takes those two folders from that commit and everything else from the last
`vX.Y.Z` release, so the new board file is live a few minutes after the merge
while `pydevices` itself keeps its released version. A board's version is still
the repository's, so the file hashes in its `package.json` tell two builds
apart. The next release clears the commit. A merge that touches neither folder
sends nothing. If the combination doesn't build, the index's run fails and the
index stays as it was; the fix is another merge.

### PyScript filesystem

[`pydevices-desktop.toml`](pydevices-desktop.toml) is a generated, committed filesystem mapping that
tracks `main`. It contains the complete Python payload of the desktop package
with explicit `/lib/...` destinations. CI fails if any discovered `lib/` or
`utils/` source, or one of the fixed desktop board files, is missing or stale.

### Before you release

Confirm the generated package set is what you expect — adding or removing a
publishable entry under `lib/` or `utils/` changes the next release
automatically — then follow the standard procedure in the
[org-wide runbook](https://github.com/PyDevices/.github/blob/main/docs/publishing-automation.md).

Published TestPyPI files and MIP releases are immutable in practice; publish a
new version to correct a release.
