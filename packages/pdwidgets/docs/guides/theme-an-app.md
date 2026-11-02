# Theme an app

Colors, corner radii and icons are properties of each widget, and the display
carries a Material Design palette to take colors from. This page shows how to
color a screen, round corners, use the built-in icons and switch between a dark
and a light look.

## Color widgets from a palette

Each `Display` builds a Material Design palette at its own color depth and byte
order and keeps it as `display.pal`. Take colors from it so they come out right
on any panel:

```python
import pdwidgets as pd

md = display.pal

screen = pd.Screen(display, bg=md.GREY_S100)
app_bar = pd.Widget(screen, w=screen.width, h=36, bg=md.BLUE_S700, align=pd.ALIGN.TOP)
pd.Label(app_bar, value="Device panel", fg=0xFFFF, bg=md.BLUE_S700,
         align=pd.ALIGN.TOP_LEFT, x=12, y=8)

connect = pd.Button(screen, label="Connect", bg=md.BLUE_S500, fg=0xFFFF,
                    x=20, y=50, radius=4)
cancel = pd.Button(screen, label="Cancel", bg=md.GREY_S200, fg=md.GREY_S800,
                   x=120, y=50, radius=4)
```

Names are the color, `_S`, then the shade, as in `BLUE_S700`. The
[palettes docs](https://palettes.readthedocs.io) list every name and show how
to build other palettes with `get_palette`.

## Use the built-in color roles

pdwidgets also names the colors its own widgets paint with, such as
`primary_variant`, `surface`, `on_surface` and `error`, on `display.color_theme`.
A widget reads its role when it's created, so change a role first and the
widgets you create afterward use it. A `Button` with no `bg` takes
`primary_variant`:

```python
display.color_theme.primary_variant = display.pal.TEAL_S600
ok = pd.Button(screen, label="OK", x=20, y=200)
```

## Round the corners

Every widget has a `radius`, in pixels, and the faces that draw a rounded
shape (`Button`, `Card`, `Chip` and the like) read it:

- `radius=0` gives square corners.
- `radius=4` to `8` is the usual rounded button or card.
- `radius=h // 2` makes a pill.

```python
pill = pd.Button(screen, label="Active", w=80, h=30, radius=15, x=20, y=100)
```

## Use an icon

Icons ship as Python modules under `pdwidgets.icons`, so there are no files to
copy to a board. Pass the module's dotted path as an `Icon`'s `value`:

```python
from pdwidgets.widgets.icon import Icon

bluetooth = Icon(screen, value="pdwidgets.icons.bluetooth_color_24dp", x=10, y=150)
menu = Icon(screen, value="pdwidgets.icons.menu_24dp", x=40, y=150, fg=0xFFFF)
```

The size is the number before `dp` in the name: 18, 24, 36 or 48.
`pd.icon_theme` resolves the names the widgets use themselves, such as
`pd.icon_theme.home(pd.ICON_SIZE.LARGE)`.

## Switch between a dark and a light look

Colors are plain values, so re-theming a live screen means assigning new ones
and letting the next tick redraw:

```python
DARK = {"bg": 0x1082, "card": 0x2124}
LIGHT = {"bg": 0xF7BE, "card": 0xFFFF}

card = pd.Card(screen, w=200, h=100, align=pd.ALIGN.CENTER)

def apply_theme(theme):
    screen.bg = theme["bg"]
    card.bg = theme["card"]
    pd.tick()

apply_theme(DARK)
```
