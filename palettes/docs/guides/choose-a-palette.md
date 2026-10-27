# Choose a palette

`get_palette(name)` returns one of four families. Pick by what you are
coloring, then pass that family's arguments.

| You are coloring | Use | Call |
|---|---|---|
| A gradient, a hue sweep, a gauge | the wheel | `get_palette("wheel", length=256)` |
| Widgets, status colors, themes | Material Design | `get_palette("material_design")` |
| A small fixed set for dithering or a picker | the cube | `get_palette("cube", size=4)` |
| Named colors such as `RED` and `NAVY` | the Windows 16 | `get_palette("default")` |

An unknown name returns the Windows 16, so check the spelling when a palette
has sixteen colors and you expected more.

## Index it

Every palette is an indexable sequence. An index wraps, so `wheel[-1]` and
`wheel[len(wheel)]` are legal and a moving offset needs no modulo of your own.

```python
from palettes import get_palette

wheel = get_palette("wheel", color_depth=16, length=256)
print(len(wheel), hex(wheel[0]), hex(wheel[256]), hex(wheel[-256]))
```

It prints `256 0xf800 0xf800 0xf800`.

## Use names

The Windows 16 and the Material palette add each color as an attribute, and
`color_name(index)` goes the other way:

```python
md = get_palette("material_design", color_depth=16)
header = md.BLUE_S500   # the same as md.BLUE
tint = md.BLUE_S50
accent = md.BLUE_A400

win16 = get_palette("default", color_depth=16)
print(win16.RED, win16.color_name(12))
```

The wheel carries the Windows 16 names as attributes too, and a cube carries
the names of its own colors (`BLACK`, `RED`, `WHITE` and so on for `size=2`).
`color_name` returns a `"#RRGGBB"` string for a color with no name in the
palette's table.

## Try one in the browser

Change `name` to `"cube"`, `"default"` or `"material_design"` and press
**Run**. It runs on MicroPython compiled to WebAssembly.

````{raw} html
<div class="pydevices-live-demo">
  <div class="demo-editor-pane">
    <textarea class="code-editor">
from palettes import get_palette
from displaydev.auto import AutoDisplay

display = AutoDisplay(width=320, height=240, canvas_id=CANVAS_ID)
display.fill(0x0000)

palette = get_palette("wheel", color_depth=16, length=320, saturation=1.0)

for x in range(display.width):
    display.fill_rect(x, 0, 1, display.height, palette[x])

display.show()
print(f"Rendered {len(palette)} colors from the wheel palette!")
    </textarea>
    <div class="demo-controls">
      <button class="run-btn" disabled>▶ Run</button>
      <button class="reset-btn">↺ Reset</button>
      <span class="demo-status">Initializing Python…</span>
    </div>
    <pre class="demo-output"></pre>
  </div>
  <div class="demo-canvas-pane">
    <canvas id="canvas_palette_gallery" width="320" height="240" tabindex="0"></canvas>
  </div>
</div>
````

[Palette families](../palettes.md) lists every argument and name.
