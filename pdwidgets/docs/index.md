# pdwidgets

<div class="hero-banner">
  <h1>pdwidgets</h1>
  <p><strong>A fast, pure-Python UI & Widget Toolkit</strong> for microcontrollers, embedded touch displays, desktop Python, and the web. Over 50 rich components with zero native C dependencies.</p>
  <div style="display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:0.75rem;">
    <span class="badge badge-orange">MIP: pdwidgets</span>
    <span class="badge badge-orange">TestPyPI: pydevices-pdwidgets</span>
    <span class="badge badge-green">50+ Modern Widgets</span>
    <span class="badge">MicroPython · CPython · Direct WebAssembly · Pyodide</span>
  </div>
</div>

<div class="grid cards">
  <div>
    <h3>Declarative Hierarchy</h3>
    <p>Build composable UI trees with <code>Display</code>, <code>Screen</code>, and nested container widgets that handle layout and clipping automatically.</p>
  </div>
  <div>
    <h3>Dirty-Rect Rendering</h3>
    <p>Efficient frame updates only repaint what changed using <code>pygraphics.Area</code> bounding boxes, maximizing frame rates on embedded SPI panels.</p>
  </div>
  <div>
    <h3>Touch, Keys & Encoders</h3>
    <p>Unified input handling across touch screens, mouse pointers, rotary encoders, joysticks, and physical keyboards with focus navigation.</p>
  </div>
  <div>
    <h3>Material Theming</h3>
    <p>Built-in integration with <code>palettes</code> for Material Design color tokens, rounded corner radii, and lightweight compiled icon assets.</p>
  </div>
</div>

---

## 🚀 Installation

=== "MicroPython (MIP)"

    ```python
    import mip
    # Install pdwidgets and its PyDevices companion packages
    mip.install("pydevices", index="https://PyDevices.github.io/mip")
    mip.install("pygraphics", index="https://PyDevices.github.io/mip")
    mip.install("palettes", index="https://PyDevices.github.io/mip")
    mip.install("pdwidgets", index="https://PyDevices.github.io/mip")
    ```

=== "CPython (TestPyPI)"

    ```bash
    pip install -i https://test.pypi.org/simple/ \
      --extra-index-url https://pypi.org/simple/ pydevices-pdwidgets
    ```

    Current releases are on TestPyPI. Production PyPI holds one older
    release, parked to reserve the name, so a plain
    `pip install pydevices-pdwidgets` works but gives you that older one.

=== "PyScript / Browser"

    The wheel is named `pydevices-pdwidgets`; the module you import is
    `pdwidgets`. micropip resolves the rest (`pydevices`,
    `pydevices-pygraphics`, `pydevices-palettes`) from the wheel metadata.

    ```python
    import micropip
    await micropip.install(
        "pydevices-pdwidgets", index_urls="https://test.pypi.org/simple/"
    )

    import pdwidgets as pd
    ```

    On MicroPython the MIP package names are unprefixed
    (`mip.install("pdwidgets", index="https://PyDevices.github.io/mip")`).

---

## 🎨 Live Interactive Demo

Click the interactive button and slider below to interact with `pdwidgets` live in your browser:

<div class="pydevices-live-demo">
  <div class="demo-editor-pane">
    <textarea class="code-editor">
import appdev
import pdwidgets as pd
from displaydev.auto import AutoDisplay

# 1. Setup Display and App
display_drv = AutoDisplay(width=320, height=240, canvas_id=CANVAS_ID)
app = appdev.App(display_drv)
display = pd.Display(display_drv, app)
screen = pd.Screen(display, bg=0x18C3)

# 2. Build Interactive Widgets
title = pd.Label(screen, value="pdwidgets Live Demo", x=16, y=16, bg=screen.bg)
status = pd.Label(screen, value="Status: Waiting for tap...", x=16, y=45, bg=screen.bg)

count = 0
btn = pd.Button(screen, label="Tap Me", x=16, y=80, w=130, h=38, radius=6, style="raised")

def on_tap(sender, event):
    global count
    count += 1
    status.value = f"Status: Tapped {count} time{'s' if count != 1 else ''}!"

btn.add_event_cb(pd.events.MOUSEBUTTONUP, on_tap)

slider = pd.Slider(screen, value=0.5, x=16, y=140, w=200, h=24)

# 3. That's it -- the app runs itself.
print("pdwidgets event loop running! Click 'Tap Me' on canvas.")
    </textarea>
    <div class="demo-controls">
      <button class="run-btn" disabled>▶ Run</button>
      <button class="reset-btn">↺ Reset</button>
      <span class="demo-status">Initializing Python…</span>
    </div>
    <pre class="demo-output"></pre>
  </div>
  <div class="demo-canvas-pane">
    <canvas id="canvas_pdwidgets_index" width="320" height="240" tabindex="0"></canvas>
  </div>
</div>

---

## Practical App Skeleton

Every `pdwidgets` application follows a standard three-stage pattern:

```python
import board_config
import appdev
import pdwidgets as pd

# 1. Initialize Display and Application Controller
app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

# 2. Build UI Hierarchy
label = pd.Label(screen, value="System Ready", x=10, y=10)
button = pd.Button(screen, label="Start", x=10, y=40, radius=4)

def on_click(sender, event):
    label.value = "Running!"
button.add_event_cb(pd.events.MOUSEBUTTONUP, on_click)

# 3. That's it -- the app keeps itself alive and handles input from here.
```

---

## 🎨 Featured Interactive Applications

Explore full-featured GUI applications built with `pdwidgets`:

<div class="grid cards">
  <div>
    <h3>Pocket Calculator</h3>
    <p>Tactile raised 3D buttons with full arithmetic engine and real-time display readout.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=calc_widgets,calc_engine&deps=pydevices-pdwidgets,pydevices-pygraphics" target="_blank" rel="noopener"><strong>Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>Clinic Check-In Kiosk</h3>
    <p>Multi-tab front-desk kiosk with appointment queue, form validation, and confirm dialogs.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_clinic_queue&deps=pydevices-pdwidgets,pydevices-pygraphics" target="_blank" rel="noopener"><strong>Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>Energy Telemetry Panel</h3>
    <p>Real-time sparkline telemetry charts, analog gauges, and status monitoring dashboard.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_energy_panel&deps=pydevices-pdwidgets,pydevices-pygraphics" target="_blank" rel="noopener"><strong>Launch Live Demo</strong></a></p>
  </div>
  <div>
    <h3>Smart Locker Kiosk</h3>
    <p>PIN entry keypad terminal for secure pickup with numeric buttons and card transitions.</p>
    <p><a href="https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_locker_kiosk&deps=pydevices-pdwidgets,pydevices-pygraphics" target="_blank" rel="noopener"><strong>Launch Live Demo</strong></a></p>
  </div>
</div>

---

## 📚 Documentation Map

* [**Architecture & Lifecycle**](architecture.md) — Display hierarchy, dirty rectangle redraws, and event loop integration.
* [**Widget Catalog**](widget-catalog.md) — Complete guide and live demos for all 50+ UI components.
* [**Layout & Sizing**](layout-guide.md) — `ALIGN` anchors, percentage sizing (`pct`), and responsive grids.
* [**Input & Events**](input-and-events.md) — Touch gestures, mouse clicks, rotary encoders, and keyboard focus rings.
* [**Theming & Icons**](theming.md) — Palette styling, Material Design colors, corner radii, and icon modules.
* [**App Recipes**](app-recipes.md) — Complete blueprints for Calculators, Smartwatches, and Dashboards.
* [**API Reference**](reference/pdwidgets/index.md) — Autogenerated class and method reference.
