# Build a settings screen

A settings screen is a card with a few controls and a button that reads them
back. This page builds one with a switch, a slider and a save button.

```python
import board_config
import appdev
import pdwidgets as pd

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x18C3)

card = pd.Card(screen, x=10, y=10, w=300, h=220, bg=0x2124, radius=8)
pd.Label(card, value="Settings", align=pd.ALIGN.TOP_LEFT, x=16, y=14, bg=0x2124, fg=0xFFFF)

pd.Label(card, value="WiFi enabled", align=pd.ALIGN.TOP_LEFT, x=16, y=50, bg=0x2124, fg=0xFFFF)
wifi = pd.Switch(card, value=True, x=220, y=45)

pd.Label(card, value="Brightness", align=pd.ALIGN.TOP_LEFT, x=16, y=90, bg=0x2124, fg=0xFFFF)
brightness = pd.Slider(card, value=0.8, x=16, y=115, w=268, align=pd.ALIGN.TOP_LEFT)   # 0 to 1

save = pd.Button(card, label="Save changes", x=16, y=160, w=268, h=36, radius=4)

def on_save(sender, event):
    print(f"Saved: wifi={wifi.value}, brightness={brightness.value}")

save.add_event_cb(pd.events.MOUSEBUTTONUP, on_save)
```

A few things the code relies on:

- Children are positioned inside their parent, so the card's contents use
  coordinates from the card's corner, not the screen's.
- A `Label` aligns to the center and a `Slider` to the bottom unless told
  otherwise, so these pass `align=pd.ALIGN.TOP_LEFT` to count `x` and `y` from
  the corner. See [Lay out widgets](lay-out-widgets.md).
- The labels pass white as `fg`, because their default ink is dark, and the
  card's color as `bg`, so text redraws cleanly.
- `Switch.value` is `True` or `False`. `Slider.value` runs from 0 to 1.
- To act as soon as a control changes instead of on a save button, use
  `set_change_cb`, as in [Respond to input](respond-to-input.md).

[Build a dashboard](build-a-dashboard.md) shows a read-only screen, and
[Build a calculator](build-a-calculator.md) a grid of buttons.
