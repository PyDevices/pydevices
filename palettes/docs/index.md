# palettes

<div class="hero-banner">
  <h1>🎨 palettes</h1>
  <p><strong>A lightweight, pure-Python color palette and UI theme engine</strong> for microcontrollers, embedded displays, desktop Python, and the browser.</p>
  <div style="display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:0.75rem;">
    <span class="badge badge-orange">📦 MIP: palettes</span>
    <span class="badge badge-orange">🐍 PyPI: pydevices-palettes</span>
    <span class="badge badge-green">⚡ Zero C Dependencies</span>
    <span class="badge">🌐 CPython · WebAssembly · MicroPython · CircuitPython</span>
  </div>
</div>

<div class="grid cards">
  <div>
    <h3>🌈 Color Wheels</h3>
    <p>Generate continuous color ramps and rainbow gradients with configurable saturation and hue lengths.</p>
  </div>
  <div>
    <h3>🎯 Material Design</h3>
    <p>Access standardized semantic UI palettes with shades from 50 to 900 for modern themes and widgets.</p>
  </div>
  <div>
    <h3>🧊 Color Cubes</h3>
    <p>Evenly distributed 8, 27, 64, and 125 color spaces optimized for dithering and quantized graphics.</p>
  </div>
  <div>
    <h3>🔄 Byte-Swapping</h3>
    <p>First-class 16-bit RGB565 byte swapping (<code>swapped=True</code>) for direct SPI panel compatibility.</p>
  </div>
</div>

---

## 🚀 Quick Install

=== "MicroPython (MIP)"

    ```python
    import mip
    mip.install("palettes", index="https://PyDevices.github.io/mip")
    ```

=== "CPython (TestPyPI)"

    ```bash
    pip install -i https://test.pypi.org/simple/ \
      --extra-index-url https://pypi.org/simple/ pydevices-palettes
    ```

=== "CircuitPython"

    Copy the `palettes/` folder from the repository into your board's `CIRCUITPY/lib/` folder.

=== "PyScript / Pyodide"

    In PyScript headers or Pyodide configurations, declare:
    ```python
    import micropip
    await micropip.install(
        "pydevices-palettes", index_urls="https://test.pypi.org/simple/"
    )

    from palettes import get_palette
    ```

    The wheel is named `pydevices-palettes`; the module you import is
    `palettes`. On MicroPython the MIP package name is `palettes`
    (`mip.install("palettes", index="https://PyDevices.github.io/mip")`).

=== "From source"

    ```bash
    git clone https://github.com/PyDevices/palettes && cd palettes
    pip install -e .                                  # or just PYTHONPATH=lib
    PYTHONPATH=lib python3 -m unittest discover -s tests
    ruff check lib tests scripts
    ```

    The last two are what CI runs.

`pydevices-palettes` is also parked on production PyPI, one release behind, so
a plain `pip install pydevices-palettes` succeeds and gives you the older one.
TestPyPI is the current channel.

---

## 💻 Live Interactive Demo

Try tweaking the palette parameters below. Click **▶ Run** to execute the code with direct MicroPython WebAssembly:

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

---

## 📖 Practical Usage Pattern

Construct a palette once and index it inside your application draw loop:

```python
from palettes import get_palette

# Match the display's native color depth (16-bit RGB565)
palette = get_palette(name="wheel", color_depth=16, length=256, saturation=1.0)

# Index directly into the palette
for i in range(16):
    display_drv.fill_rect(0, i * 8, 80, 8, palette[i * 16])
```

If the physical display expects byte-swapped 16-bit values (common on SPI TFTs like the ST7789 or ILI9341), pass `swapped=True`:

```python
palette = get_palette(name="wheel", color_depth=16, swapped=True)
```

---

## 🎮 Featured Browser Demos

Explore full-color gradient and animation applications built with `palettes`:

<div class="grid cards">
  <div>
    <h3>🎨 Palettes Gallery Showcase</h3>
    <p>Interactive color visualizer exploring Material Design tokens, HSV wheels, and RGB cubes.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=palettes_demo&deps=pydevices-palettes,pydevices-pygraphics" target="_blank" rel="noopener"><strong>▶ Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>🪶 Rainbow Feathers</h3>
    <p>Geometric generative art rendering smooth multi-chromatic feather curves.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=feathers&deps=pydevices-palettes,pydevices-pygraphics" target="_blank" rel="noopener"><strong>▶ Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>🔄 Palette Rotations</h3>
    <p>Real-time palette cycling and rotational sweeps demonstrating zero-cost animations.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=rotations&deps=pydevices-palettes,pydevices-pygraphics" target="_blank" rel="noopener"><strong>▶ Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>📜 Gradient Scrolling</h3>
    <p>Hardware vertical scrolling demonstration paired with high-precision palette shading.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=scroll&deps=pydevices-palettes,pydevices-pygraphics" target="_blank" rel="noopener"><strong>▶ Launch Live Demo</strong></a></p>
  </div>
</div>

---

## 📚 Documentation Map

* 🎨 [**Palette Gallery**](palette-gallery.md) — Visual previews and tables for Wheel, Material Design, Cube, and Win16 palettes.
* 🔢 [**Color Math & Formats**](color-math.md) — RGB565 bit-packing, endianness swapping, and HSV math.
* 🧩 [**Integrations**](integrations.md) — Recipes for `pygraphics`, `pdwidgets`, and hardware display drivers.
* 📚 [**API Reference**](reference/palettes/index.md) — Complete docstrings and class references.
