# Fill a framebuffer with a palette

A palette hands pygraphics the integers it draws with. Build the palette at the
framebuffer's depth (16 for RGB565) and index it for each fill.

```python
import pygraphics
from palettes import get_palette

w, h = 160, 128
fb = pygraphics.FrameBuffer(bytearray(w * h * 2), w, h, pygraphics.RGB565)
fb.fill(0x0000)

palette = get_palette("wheel", color_depth=16, length=h)
for y in range(h):
    fb.hline(0, y, w, palette[y])

area = pygraphics.text16(fb, "pygraphics", 20, 56, 0xFFFF)
print(area)
```

It prints `Area(20, 56, 80, 16)` and leaves a hue gradient with white text in
`fb`. Install pygraphics first:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pydevices-pygraphics
```

The palette does not know about the framebuffer, so a mismatch in depth gives
wrong colors and no error. A `pygraphics.RGB565` buffer wants
`color_depth=16`.
