<img src="docs/images/pdwidgets.png" width="240" alt="A label reading Taps: 3 above a button labelled Tap me, on black">

# pdwidgets

pdwidgets is the part of OmniPython that draws user interfaces: labels, buttons,
sliders, lists, dialogs and layouts in pure Python, with the same code on
MicroPython-compatible boards, CPython and in the browser.

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pydevices-pdwidgets pydevices-desktop
```

```python
import mip
for package in ("pydevices", "pygraphics", "palettes", "pdwidgets"):
    mip.install(package, index="https://PyDevices.github.io/mip")
```

The first is for a desktop, and `pydevices-desktop` brings the display it draws
on. The second installs onto a board, which also needs its board config:
[Install](docs/get-started/install.md) has every board and channel.

```python
import board_config
import appdev
import pdwidgets as pd

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

label = pd.Label(screen, value="Taps: 0", align=pd.ALIGN.TOP, y=40, bg=screen.bg)
button = pd.Button(screen, label="Tap me", align=pd.ALIGN.CENTER, w=160, h=50)
taps = 0

def on_tap(sender, event):
    global taps
    taps += 1
    label.value = f"Taps: {taps}"
    print(label.value)

button.add_event_cb(pd.events.MOUSEBUTTONUP, on_tap)
app.run()
```

```text
Taps: 1
Taps: 2
Taps: 3
```

That opens a window with a button in it, and each click prints a line. The
picture at the top of this page is the window after three clicks.

[Docs](https://pdwidgets.readthedocs.io) · [Examples](https://pydevices.github.io/pydevices-examples/pyscript/) · [Roadmap](ROADMAP.md)

OmniPython is made by [PyDevices](https://pydevices.com).
