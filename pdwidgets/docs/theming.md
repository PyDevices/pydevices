# Theming & Icons

Customizing colors, corner radii, dark/light modes, and icon assets in `pdwidgets`.

---

## 1. Color Theming with `palettes`

`pdwidgets` pairs with the [`palettes`](https://palettes.readthedocs.io) package for standard Material Design themes:

```python
import pdwidgets as pd
from palettes import get_palette

# Load Material Design Blue and Grey color sets
blue = get_palette("material_design", color_depth=16, color_name="blue")
grey = get_palette("material_design", color_depth=16, color_name="grey")

# Apply tokens to screen and widgets
screen = pd.Screen(display, bg=grey["50"])

app_bar = pd.Widget(screen, w=screen.width, h=36, bg=blue["700"], align=pd.ALIGN.TOP)
pd.Label(app_bar, value="Device Panel", fg=0xFFFF, x=12, y=8)

btn_primary = pd.Button(screen, label="Connect", bg=blue["500"], fg=0xFFFF, x=20, y=50, radius=4)
btn_secondary = pd.Button(screen, label="Cancel", bg=grey["200"], fg=grey["800"], x=120, y=50, radius=4)
```

---

## 2. Corner Radii (`radius`)

Every `Widget` supports a `radius` parameter for modern rounded corners:

* **Square (`radius=0`)**: Retro / low-resolution display style.
* **Rounded (`radius=4` to `8`)**: Standard modern card and button appearance.
* **Pill (`radius=h // 2`)**: Fully rounded chip or badge style.

```python
# Pill button
pill_btn = pd.Button(screen, label="Active", w=80, h=30, radius=15)
```

---

## 3. Built-in Icon Modules

`pdwidgets` includes pre-compiled Material Design icon modules under `lib/pdwidgets/icons/` (e.g. `bluetooth_color_24dp.py`, `battery_full_color_24dp.py`, `menu_24dp.py`, `home_filled_24dp.py`):

```python
from pdwidgets.widgets.icon import Icon

# `value` is the dotted import path of the generated icon module.
bt_icon = Icon(screen, value="pdwidgets.icons.bluetooth_color_24dp", x=10, y=10)
menu_icon = Icon(screen, value="pdwidgets.icons.menu_24dp", x=35, y=10, fg=0xFFFF)
```

---

## 4. Dark Mode / Light Mode Switching

You can dynamically re-theme a live UI simply by modifying the root palette tokens:

```python
class Theme:
    DARK = {
        "bg": 0x1082,
        "card": 0x2124,
        "fg": 0xFFFF,
        "primary": 0x04FF,
    }
    LIGHT = {
        "bg": 0xF7BE,
        "card": 0xFFFF,
        "fg": 0x0000,
        "primary": 0x001F,
    }

def apply_theme(theme):
    screen.bg = theme["bg"]
    card.bg = theme["card"]
    pd.tick()
```
