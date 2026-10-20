# App Recipes & Blueprints

Complete production recipes and architecture patterns from real `pydevices-examples` applications.

---

## 1. Recipe: Settings & Configuration Form

A multi-card settings screen with switches, sliders, and submit actions:

```python
import appdev
import pdwidgets as pd
import board_config

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x18C3)

# Card Container
card = pd.Card(screen, x=10, y=10, w=300, h=220, bg=0x2124, radius=8)
pd.Label(card, value="Settings", x=16, y=14)

# WiFi Switch
pd.Label(card, value="WiFi Enabled", x=16, y=50)
wifi_sw = pd.Switch(card, value=True, x=220, y=45)

# Brightness Slider (value is normalized to [0, 1])
pd.Label(card, value="Brightness", x=16, y=90)
bright_slider = pd.Slider(card, value=0.8, x=16, y=115, w=268)

# Save Button
save_btn = pd.Button(card, label="Save Changes", x=16, y=160, w=268, h=36, radius=4)

def on_save(s, e):
    print(f"Saved: WiFi={wifi_sw.value}, Brightness={bright_slider.value}")
save_btn.add_event_cb(pd.events.MOUSEBUTTONUP, on_save)
```

---

## 2. Recipe: Pocket Calculator

A grid-based calculator with an LCD label and push buttons:

```python
import appdev
import pdwidgets as pd
import board_config

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x0000)

# Display readout
display_label = pd.Label(screen, value="0", x=10, y=10, w=300, h=40, bg=0x1082)

# Button matrix
buttons = [
    ["7", "8", "9", "/"],
    ["4", "5", "6", "*"],
    ["1", "2", "3", "-"],
    ["C", "0", "=", "+"],
]

for row_idx, row in enumerate(buttons):
    for col_idx, key in enumerate(row):
        btn = pd.Button(screen, label=key, x=10 + col_idx * 75, y=60 + row_idx * 42, w=70, h=38, radius=4)
        def make_handler(k):
            return lambda s, e: setattr(display_label, "value", k)
        btn.add_event_cb(pd.events.MOUSEBUTTONUP, make_handler(key))
```

---

## 3. Recipe: IoT Telemetry Dashboard

Combining real-time sparkline charts, gauges, and status badges:

```python
import appdev
import pdwidgets as pd
import board_config

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x1082)

# Top Bar with a status badge
bar = pd.AppBar(screen, title="Node #42")
status = pd.Badge(screen, value="Online", align=pd.ALIGN.OUTER_RIGHT, align_to=bar)

# Telemetry Chart (value is the data series; fg sets the line color)
chart = pd.Chart(
    screen, x=10, y=50, w=300, h=100, fg=0x07E0,
    value=[20, 22, 21, 24, 28, 32, 29, 31, 35, 30],
)

# Summary Gauge (value is normalized to [0, 1])
gauge = pd.Gauge(screen, value=0.75, x=10, y=160)
```

---

## 🎮 Production Applications in `pydevices-examples`

Run complete interactive UI applications directly in your browser:

| Application | Description | Live PyScript Link |
|:---|:---|:---|
| **`calc_widgets`** | Pocket calculator with raised 3D buttons and math engine | [**▶ Launch `calc_widgets`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=calc_widgets,calc_engine&deps=pydevices-pdwidgets,pydevices-pygraphics) |
| **`widgets_clinic_queue`** | Clinic check-in kiosk with tabs, forms, and dialogs | [**▶ Launch `widgets_clinic_queue`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_clinic_queue&deps=pydevices-pdwidgets,pydevices-pygraphics) |
| **`widgets_energy_panel`** | Industrial telemetry monitor with dynamic graphs and gauges | [**▶ Launch `widgets_energy_panel`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_energy_panel&deps=pydevices-pdwidgets,pydevices-pygraphics) |
| **`widgets_locker_kiosk`** | Smart parcel locker terminal with PIN entry pad | [**▶ Launch `widgets_locker_kiosk`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=widgets_locker_kiosk&deps=pydevices-pdwidgets,pydevices-pygraphics) |
| **`paint`** | Interactive color canvas drawing and brush selector | [**▶ Launch `paint`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?modules=paint) |
| **`roku_remote`** | Smart TV touch remote with tactile raised button keypad | [**▶ Launch `roku_remote`**](https://pydevices.github.io/pydevices-examples/pyscript/pyodide.html?manifests=roku_remote&deps=pydevices-lvgl,pydevices-pygraphics,pydevices-pdwidgets) |

