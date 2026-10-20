# pdwidgets

**Pure-Python, portable widget toolkit for [PyDevices](https://github.com/PyDevices/pydevices)**

`pdwidgets` provides a complete, 100% pure-Python GUI toolkit for building touchscreen and desktop interfaces without requiring native C bindings or complex build toolchains. It runs on **MicroPython**, **CPython desktop** and **PyScript (Web)** — see [Support and platforms](#support-and-platforms) for what each claim is worth, and where CircuitPython stands.

New here? Read the [newcomer's guide](docs/newcomers.md) for the widget tree,
event/rendering flow, and contributor boundary.

### Where pdwidgets fits

PyDevices offers several GUI approaches; `pdwidgets` is the pure-Python one. See
[pydevices — choosing a GUI layer](https://github.com/PyDevices/pydevices/blob/main/docs/architecture.md#choosing-a-gui-layer).

---

## Quick Start: Interactive Button & Screen

> **Note:** `import board_config` isn't satisfied by the install commands
> below. On desktop, `board_config` ships with `pydevices-desktop`
> (`pip install -i https://test.pypi.org/simple/ pydevices-desktop`). On a
> board, it comes from a `PyDevices/pydevices` board config, installed with
> `mip.install("github:PyDevices/pydevices/board_configs/<path-to-board>",
> index="https://PyDevices.github.io/mip")`.

```python
import board_config
import appdev
import pdwidgets as pd

# 1. Initialize display and the event app
app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

# 2. Add a label and an interactive button with a click handler
label = pd.Label(screen, value="Taps: 0", x=40, y=30)
btn = pd.Button(screen, label="Tap me", x=40, y=60, w=160, h=50)

_taps = 0

def on_button_click(sender, event):
    global _taps
    _taps += 1
    label.value = f"Taps: {_taps}"

btn.add_event_cb(pd.events.MOUSEBUTTONUP, on_button_click)

# 3. That's it -- the app keeps itself alive and handles input from here.
# No app.run() is needed; call it only to block at this point or to get an
# exit code.
```

---

## Key Features

- **100% Pure Python & Portable**: Zero native C extensions or compilation steps required.
- **Zero-File Icon System (`pdwidgets.icons`)**: Material Design icons packaged directly as importable Python bytecode modules (`bytearray` bitmaps)—no SD card assets, binary file I/O, or asset path management needed.
- **MCU Memory-Friendly (Lean Imports)**: Import individual widgets to minimize RAM footprint on microcontrollers:
  ```python
  from pdwidgets.widgets.button import Button
  from pdwidgets.screen import Screen
  ```
- **Integrated Theming**: Customizable color schemes, border radii, and visual states using [`palettes`](https://github.com/PyDevices/palettes).

---

## Installation

```python
import mip
# pdwidgets does not pull its dependencies on MIP -- install them too.
mip.install("pydevices", index="https://PyDevices.github.io/mip")
mip.install("pygraphics", index="https://PyDevices.github.io/mip")
mip.install("palettes", index="https://PyDevices.github.io/mip")
mip.install("pdwidgets", index="https://PyDevices.github.io/mip")
```

```bash
pip install -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ pydevices-pdwidgets
```

On desktop you also need SDL2 itself. `board_config` loads it by `ctypes` at
import, so without it the quickstart's very first line fails:

```bash
sudo apt install libsdl2-2.0-0      # Debian/Ubuntu
brew install sdl2                   # macOS
```

Windows wheels carry `SDL2.dll`, so nothing extra is needed there.

`board_config` itself comes from `pydevices-desktop` or a board config — see
the note under [Quick Start](#quick-start-interactive-button--screen) above.

## Support and platforms

Every claim below carries its tier, in the vocabulary of the org's
[platform support tiers](https://github.com/PyDevices/.github/blob/main/docs/platform-support-tiers.md).

| Runtime | Tier | What backs it |
|---|---|---|
| MicroPython on wasm (browser) | bench-proven | The [live demo gallery](https://pydevices.github.io/pydevices-examples/pyscript/) — a stranger can watch it run right now |
| MicroPython on MCU (ESP32 family, RP2) | bench-proven | The widget examples in [pydevices-examples](https://github.com/PyDevices/pydevices-examples) target the touch boards and are run on them; installs via MIP. Nothing automated covers this — there is no hardware job in CI |
| CPython desktop (Linux x86-64, Windows amd64) | CI-proven | `ruff` and the unit tests run on ubuntu CPython 3.13 on every push; the quickstart above runs on any desktop with SDL2 |
| CircuitPython | **not proven — no route** | See below |

**CircuitPython has no install route and nothing has run.** `manifest.py` is
runtime-agnostic, so a CircuitPython build whose freeze manifest includes it
*can* carry `pdwidgets` in the image — but nobody has built one, there is no CI job, and
there is no `circup` or bundle path for a user. The cause is plain: nobody has
needed it yet. Treat CircuitPython as unsupported until that changes.

**No macOS or ARM-Linux wheels.** The desktop and PyScript paths need
`pydevices-pygraphics`, which publishes cp310–cp314 wheels for manylinux
x86-64, Windows amd64, Android and Emscripten — and no sdist. The cause is
runners: there is no Mac on the bench and no ARM-Linux runner in the release
matrix, so there is nothing to build or prove those wheels on.

**Which index to install from.** Current releases go to TestPyPI; install
from there with the command above. Production PyPI holds one older release,
parked there to reserve the name. It installs and works, it is just behind:

| Index | Command | Serves today |
|---|---|---|
| TestPyPI (current) | `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pydevices-pdwidgets` | 0.0.23 |
| PyPI (parked, reserves the name) | `pip install pydevices-pdwidgets` | 0.0.22 |

So a plain `pip install pydevices-pdwidgets` works, and gives you the older
release. The TestPyPI command also lists PyPI as `--extra-index-url`, and pip
takes whichever index has the higher version, which today is TestPyPI.

What's planned next is in [ROADMAP.md](ROADMAP.md).

## Links & Demos

- [Documentation](https://pdwidgets.readthedocs.io)
- [Source Code](https://github.com/PyDevices/pdwidgets)
- [PyScript Live Demos](https://pydevices.github.io/pydevices-examples/pyscript/)
- Related: [pydevices](https://github.com/PyDevices/pydevices), [palettes](https://github.com/PyDevices/palettes), [pydevices-examples](https://github.com/PyDevices/pydevices-examples)

## License

MIT — see [LICENSE](LICENSE).


---

## Development (maintainers)

`pdwidgets` is pure Python and imports its three siblings from source. Clone
them beside this repo — [pydevices](https://github.com/PyDevices/pydevices),
[pygraphics](https://github.com/PyDevices/pygraphics) and
[palettes](https://github.com/PyDevices/palettes) — then:

```bash
python3 -m venv .venv
.venv/bin/pip install ruff
# tests and lint: the same two commands CI runs, so they cannot drift silently
PYTHONPATH="lib:tests/stubs:../pydevices/lib:../pygraphics/lib:../palettes/lib" \
  .venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check lib tests scripts
```

The `.venv` the icon recipe below invokes is this one.

---

## Icon assets (maintainers)

Runtime icons are **importable Python modules** under [`lib/pdwidgets/icons/`](lib/pdwidgets/icons/)
(no binary mip). Authoring:

```bash
# 1) Optional: regenerate mono .pbm / color .bmp from Material Design
.venv/bin/python scripts/assets_generate_pdwidgets_icons.py
.venv/bin/python scripts/assets_make_color_icons.py
# 2) Convert binaries → .py modules (BITMAP = bytearray).
#    Needs a sibling ../pygraphics checkout: FrameBuffer.export is pure-Python
#    only and is not in the published pygraphics wheel.
.venv/bin/python scripts/assets_icons_to_py.py --delete-binaries
# Optional bulk dump into assets/icons/
.venv/bin/python scripts/assets_convert_md_png_to_pbm.py
# PNG smoke probe (PyDevices display stack + material-design-icons png/)
SDL_VIDEODRIVER=dummy ../pydevices-examples/.venv/bin/python tools/png_test.py
```
