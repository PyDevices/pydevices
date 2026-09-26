# AGENTS.md — pydevices

Canonical PyDevices product/source repository. Owns **board configs**,
**hardware drivers**, portable libraries (`displaydev`, `audiodev`,
`appdev`, `multimer`, `events`, `keys`, `bledev`), and pip/MIP publishing.
Docs are markdown under `docs/`, published only via GitHub Pages
([docs/](docs/README.md); the Pages site is the landing page only)
— not Read the Docs. Build locally with `./scripts/build_pages.sh` (needs
`pandoc`).

## Do

- Add/edit MicroPython boards under `board_configs/` and CircuitPython under
  `board_configs/cp/` (same directory names as MicroPython; do not add an `mp/`
  mirror). Chip helpers under `drivers/` (see `drivers/README.md`).
- MicroPython board dirs get a direct-GitHub `package.json`; do **not** add one
  under `board_configs/cp/`. Board installers depend on `pydevices` at
  `latest`, include required board-specific Python drivers in `urls`, and do
  not pull optional Python bus fallbacks.
- Prefer vendored single-file drivers (micropython-lib / reputable GitHub) for
  shared chips. Use `machine.SDCard` for SDMMC/SDIO and `sdcard.py` for SPI CS
  paths.
- **MicroPython** board peripherals contract: `board_config.py` (eager UI hardware) +
  `board_peripherals.py` (`PERIPHERALS`, lazy factories) + `load_peripherals(globals())`
  using the product-owned `boarddev`. Pin wiring for lazy extras lives in
  `board_peripherals` factories.
- **CircuitPython** (`board_configs/cp/`): **no** `board_peripherals.py`, **no**
  `PERIPHERALS` / `load_peripherals`, and **no** `from board_config import …`.
  CircuitPython already has the native `board` module for pins/buses. CP
  `board_config.py` provides `display_drv`, eager input hardware, and neutral
  read aliases (`touch_read`, `keypad_read`, `encoder_read`, and so on). Board
  configs never instantiate `appdev` or an `appdev.App`. Non-UI
  peripherals stay on CP `board` / libraries.
- Run `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests` after changing `displaydev`, `multimer`, `events`, `keys`, `audiodev`, `boarddev`, or `utils/`. See `tests/README.md`.
- Keep MIP `package.json` URLs on
  `github:PyDevices/pydevices/...` for files in this repo
  (MicroPython boards only; all sources are product-owned). Do **not** add a
  URL for anything under `lib/`: a board config that declares
  `"deps": [["pydevices", "latest"]]` already installs all of it, and a second
  fetch pinned to `main` only creates a way for the two to disagree.
  MIP names and Python imports remain unprefixed (`displaydev`, `audiodev`,
  `appdev`, `events`, `keys`, `multimer`). TestPyPI distribution names are
  always `pydevices-*`. `displaydev` → `events` + `keys`; `appdev` →
  `events` + `keys` + `multimer`. Every non-debris top-level component in
  `lib/` publishes automatically as a leaf; `pydevices` depends on all leaves.
  Every library component in `utils/` is bundled automatically into
  `pydevices-desktop` without becoming a separate package. The desktop package
  depends on `pydevices`.
  `bledev` is the one `lib/` package declared to publish to MIP on its own
  (`mip-split.toml`, `own-package`), requiring aioble; `bledev.auto` is
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
