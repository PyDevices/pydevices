# Color widgets with a palette

pdwidgets builds a Material Design palette for each display it draws on, at the
display's depth and byte order, and keeps it as `display.pal`. Use it, or build
your own with `get_palette`, to color widgets.

```python
import pdwidgets as pd
from palettes import get_palette

md = get_palette("material_design", color_depth=16)

screen = pd.Screen(display, bg=md.GREY_S100)
app_bar = pd.Widget(screen, w=screen.width, h=32, bg=md.TEAL_S700, align=pd.ALIGN.TOP)
submit = pd.Button(screen, label="Submit", bg=md.TEAL_S500, fg=0xFFFF,
                   x=20, y=50, radius=4)
cancel = pd.Button(screen, label="Cancel", bg=md.GREY_S300, fg=md.GREY_S900,
                   x=120, y=50, radius=4)
```

`display` is your pdwidgets `Display`. If your driver needs byte-swapped
colors, take the colors from `display.pal` instead of building a palette
yourself, so the byte order matches what pdwidgets draws.

pdwidgets' own color roles (primary, surface, error and the rest) live on its
`ColorTheme`, which uses a palette only to convert its colors to RGB565. The
[pdwidgets docs](https://pdwidgets.readthedocs.io) cover changing them.
