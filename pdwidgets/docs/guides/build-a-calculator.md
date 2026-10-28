# Build a calculator

A calculator is a readout and a grid of buttons that share one handler. This
page builds a four-function one.

```python
import board_config
import appdev
import pdwidgets as pd

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

readout = pd.Label(screen, value="0", x=10, y=10, w=300, h=40, bg=0x1082,
                   align=pd.ALIGN.TOP_LEFT)

keys = [
    ["7", "8", "9", "/"],
    ["4", "5", "6", "*"],
    ["1", "2", "3", "-"],
    ["C", "0", "=", "+"],
]

total, op, entry = 0.0, None, ""

def apply(a, op, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    return a / b if b else 0.0

def press(key):
    global total, op, entry
    if key.isdigit():
        entry += key
        readout.value = entry
    elif key == "C":
        total, op, entry = 0.0, None, ""
        readout.value = "0"
    else:
        if entry:
            total = apply(total, op, float(entry)) if op else float(entry)
            entry = ""
        op = None if key == "=" else key
        readout.value = "%g" % total

for r, row in enumerate(keys):
    for c, key in enumerate(row):
        button = pd.Button(screen, label=key, x=10 + c * 75, y=60 + r * 42,
                           w=70, h=38, radius=4, align=pd.ALIGN.TOP_LEFT)
        button.add_event_cb(pd.events.MOUSEBUTTONUP, lambda s, e, k=key: press(k))
```

The loop makes one button per key and gives each its own copy of `key` through
a default argument, `k=key`. Without it every button would press the last key,
because a lambda looks the name up when it runs, not when it's made.

The buttons sit at fixed pixel positions on a 320-pixel-wide panel. To fit
other sizes, place them with a [Grid](lay-out-widgets.md) or percentage widths.
For a calculator with raised, shaded keys, see the `calc_widgets` example in
[gallery](https://pydevices.github.io/gallery/pyscript/).
