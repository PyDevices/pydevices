# Input & Events

Managing touch, mouse, rotary encoder, joystick, and keyboard interactions in `pdwidgets`.

---

## 1. Supported Input Devices

`pdwidgets` abstracts multiple physical input streams into unified event objects via `appdev.App`:

* **Touch & Pointer**: Touch screens (CST816, FT6236, XPT2046) and mouse pointers.
* **Rotary Encoders**: Incremental dials for scrolling lists and adjusting sliders.
* **Physical Joysticks & D-Pads**: Directional navigation across widget grids.
* **Keyboards**: Physical buttons or virtual on-screen keyboards.

---

## 2. Event Types

| Event Constant | Origin | Description |
|:---|:---|:---|
| `events.MOUSEBUTTONDOWN` | Pointer / Touch | Touch pressed or left mouse button clicked down |
| `events.MOUSEBUTTONUP` | Pointer / Touch | Touch lifted or mouse button released |
| `events.MOUSEMOTION` | Pointer / Drag | Pointer moved across the screen |
| `events.MOUSEWHEEL` | Wheel / Encoder | Rotary encoder step or scroll wheel turn |
| `events.KEYDOWN` | Keyboard / D-pad | Key or physical button pressed down |
| `events.KEYUP` | Keyboard / D-pad | Key released |
| `events.JOYAXISMOTION` | Analog Joystick | Joystick axis tilted |
| `events.JOYBUTTONDOWN` | Gamepad Button | Gamepad button pressed |

---

## 3. Registering Event Callbacks

Use `add_event_cb` on any widget. The callback receives `(sender, event)`:

```python
import pdwidgets as pd
import events

button = pd.Button(screen, label="Click Me", x=10, y=10)

def handle_click(sender, event):
    print(f"Button '{sender.label.value}' clicked at coordinates: {event.pos}")

button.add_event_cb(events.MOUSEBUTTONUP, handle_click)
```

### State Change Callbacks
Many controls (such as `Slider`, `Switch`, `NumberStepper`, `CheckBox`) also support simplified value change callbacks:

```python
slider = pd.Slider(screen, value=0.0, x=10, y=60)  # value is normalized to [0, 1]

def on_change(widget):
    print(f"New slider value: {widget.value}")

slider.set_change_cb(on_change)
```

---

## 4. Focus Navigation & Keyboard Focus Rings

For devices without touchscreens (e.g. rotary encoder or directional button setups), `pdwidgets` includes a built-in focus manager:

* **Tab / Next**: Advances focus to the next focusable widget.
* **Shift+Tab / Prev**: Moves focus to the previous widget.
* **Enter / Space**: Triggers the currently focused widget's action.
* **Focus Ring**: Focused widgets draw a highlight border (`focus_color`).

```python
# Programmatically set focus
display.focus_manager.focus(button)
```
