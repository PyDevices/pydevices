# palettes

palettes is the part of OmniPython that turns a palette index into a color a
display, LED or terminal can use: wheels, cubes, Material Design swatches and
the sixteen Windows names, with the same code on MicroPython-compatible boards,
CircuitPython-compatible boards and CPython. It has no dependencies.

Edit the code below and press **Run**. It runs in your browser, on
MicroPython compiled to WebAssembly.

````{raw} html
<div class="pydevices-live-demo">
  <div class="demo-editor-pane">
    <textarea class="code-editor">
from palettes import get_palette
from displaydev.auto import AutoDisplay

# Initialize display canvas (320x240)
display = AutoDisplay(width=320, height=240, canvas_id=CANVAS_ID)
display.fill(0x1082)

# Generate a 256-color wheel palette
palette = get_palette("wheel", color_depth=16, length=256, saturation=1.0)

# Draw vertical color bars
bar_width = display.width // 32
for i in range(32):
    color = palette[i * 8]
    display.fill_rect(i * bar_width, 20, bar_width, 100, color)

# Material Design amber ramp
md = get_palette("material_design", color_depth=16)
shades = [
    md.AMBER_S50, md.AMBER_S100, md.AMBER_S200, md.AMBER_S300, md.AMBER_S400,
    md.AMBER_S500, md.AMBER_S600, md.AMBER_S700, md.AMBER_S800, md.AMBER_S900
]
for i, color in enumerate(shades):
    display.fill_rect(i * 30 + 10, 140, 26, 60, color)

display.show()
print("Drawn 32 color wheel bands and 10 Material Design amber shades!")
    </textarea>
    <div class="demo-controls">
      <button class="run-btn" disabled>▶ Run</button>
      <button class="reset-btn">↺ Reset</button>
      <span class="demo-status">Initializing Python…</span>
    </div>
    <pre class="demo-output"></pre>
  </div>
  <div class="demo-canvas-pane">
    <canvas id="canvas_palettes_index" width="320" height="240" tabindex="0"></canvas>
  </div>
</div>
````

[Install it](get-started/install.md), then run
[your first program](get-started/first-program.md). The
[guides](guides/choose-a-palette.md) take one task each, the
docstrings in
[`lib/palettes`](https://github.com/PyDevices/pydevices/tree/main/palettes/lib/palettes)
document every name, and
[How it works](how-it-works/index.md) explains the design.

```{toctree}
:hidden:
:caption: Get started

get-started/install
get-started/first-program
```

```{toctree}
:hidden:
:caption: Guides

guides/choose-a-palette
guides/use-a-palette-on-a-display
guides/animate-by-cycling-colors
guides/fill-a-framebuffer-with-pygraphics
guides/color-widgets-with-pdwidgets
guides/run-in-the-browser
```

```{toctree}
:hidden:
:caption: Reference

reference/index
palettes
color-formats
platforms
```

```{toctree}
:hidden:
:caption: How it works

how-it-works/index
how-it-works/color-math
```

```{toctree}
:hidden:
:caption: Changelog

changelog
```
