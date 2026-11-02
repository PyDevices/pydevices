# Animate by cycling colors

An index wraps, so adding an offset to every index and moving the offset each
frame slides the colors along. The palette is built once and nothing is
allocated per frame.

```python
import time
from palettes import get_palette

wheel = get_palette("wheel", color_depth=16, length=256)

offset = 0
while True:
    for i in range(16):
        color = wheel[offset + i * 16]
        display_drv.fill_rect(i * 20, 0, 20, 240, color)
    display_drv.show()
    offset = (offset + 1) % 256
    time.sleep(0.016)
```

`display_drv` is your display driver, as in
[Use a palette on a display](use-a-palette-on-a-display.md). The wheel caches
each color it computes, so the second lap through the same indices only looks
them up.

To step faster or slower, change what you add to `offset`. To cycle a
different set of colors, build another family: `get_palette("cube", size=4)`
has 64 entries to walk through.
