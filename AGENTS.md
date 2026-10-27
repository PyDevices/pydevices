# AGENTS.md — pydevices

Canonical PyDevices product/source repository. Owns **board configs**,
**hardware drivers**, portable libraries (`displaydev`, `audiodev`,
`appdev`, `multimer`, `events`, `keys`, `bledev`), and pip/MIP publishing.
Docs are MyST Markdown under `docs/`, built by Sphinx for Read the Docs
([docs/index.md](docs/index.md), `.readthedocs.yaml`). Build locally with
`pip install -r docs/requirements.txt` and
`sphinx-build -W --keep-going -b html docs _site`.

## Do

- Add/edit MicroPython boards under `board_configs/` and CircuitPython under
  [`board_configs/cp/`](board_configs/cp/) (same directory names as MicroPython; do not add an `mp/`
  mirror). Chip helpers under `drivers/` (see [`drivers/README.md`](drivers/README.md)).
- MicroPython board dirs are packages: a `manifest.py` that requires
  `pydevices` and each driver package the board imports, and lists its own
  files with `module()`. Drivers are packages in `drivers/drivers.toml`. Run
  `python tools/libbuild.py installers` to write the `package.json` (the
  GitHub installer) from the manifest, and `python tools/libbuild.py check`
  before pushing. Nothing of this under `board_configs/cp/`. See
  [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Don't vendor a micropython-lib driver: require upstream's package
  (`sdcard`, `bmi270`). Use `machine.SDCard` for SDMMC/SDIO and upstream's
  `sdcard` for SPI CS paths (`sdcard_nrf` on the nRF52).
- **MicroPython** board peripherals contract: `board_config.py` (eager UI hardware) +
  `board_peripherals.py` (`PERIPHERALS`, lazy factories) + `load_peripherals(globals())`
  using the product-owned `boarddev`. Pin wiring for lazy extras lives in
  `board_peripherals` factories.
- **CircuitPython** (`board_configs/cp/`): `board_peripherals.py` is
  optional, only for roles that need setup `board` doesn't do (a codec, a
  power chip); **no** `from board_config import …` inside it.
  CircuitPython already has the native `board` module for pins/buses
  ([the contract](docs/boards/board-contract.md)). CP
  `board_config.py` provides `display_drv`, eager input hardware, and neutral
  read aliases (`touch_read`, `keypad_read`, `encoder_read`, and so on). Board
  configs never instantiate `appdev` or an `appdev.App`. Non-UI
  peripherals stay on CP `board` / libraries.
- Run `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests` after changing `displaydev`, `multimer`, `events`, `keys`, `audiodev`, `boarddev`, or `utils/`. See [`tests/README.md`](tests/README.md).
- Never edit a board's `package.json` by hand; it is generated from
  `manifest.py`. Don't `module()` anything under `lib/`: `require("pydevices")`
  already installs all of it.
  MIP names and Python imports remain unprefixed (`displaydev`, `audiodev`,
  `appdev`, `events`, `keys`, `multimer`). TestPyPI distribution names are
  always `pydevices-*`. `displaydev` → `events` + `keys`; `appdev` →
  `events` + `keys` + `multimer`. Every non-debris top-level component in
  `lib/` ships inside the `pydevices` MIP package; only a directory marked
  `own-package` in [`mip-split.toml`](mip-split.toml) also publishes as a MIP package of its own.
  Every library component in `utils/` is bundled automatically into
  `pydevices-desktop` without becoming a separate package. The desktop package
  depends on `pydevices`.
  `bledev` is the one `lib/` package declared to publish to MIP on its own
  (`mip-split.toml`, `own-package`); aioble comes from micropython-lib,
  installed first; `bledev.auto` is
  never imported by `bledev/__init__.py` or a backend.
  `AutoDisplay` is `displaydev.auto` only — never re-exported from
  `displaydev/__init__.py`. Backends must not import `.auto`.
  Likewise, `multimer`'s wake sources are private modules
  (`multimer._src_signal`, `_src_pending`, `_src_asyncio`, `_src_machine`,
  `_src_wasm`, `_src_native`, `_src_none`) that the dispatcher picks once, on
  the first armed timer; nothing else imports them, and `import multimer`
  touches no host mechanism. There is one public `Timer`.

## Do not

- Put product libraries or their release pipeline back in the examples repo.
- Instantiate `appdev.App` (or any traffic controller) in a board config.
- Import `displaydev.auto` from `displaydev/__init__.py` or any backend.
- Import a `multimer._src_*` module from anywhere but the dispatcher.
- Commit large generated assets unrelated to boards/drivers.
- Rename the GitHub repo casually — MIP URLs and docs pin this name.
- Add `board_peripherals.py` under `board_configs/cp/`.

## Local layout

Typical clone: `~/gh/pydevices/pydevices` next to
`~/gh/pydevices/pydevices-examples`.
