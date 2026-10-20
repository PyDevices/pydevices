# Architecture & Lifecycle

An overview of `pdwidgets`'s component hierarchy, dirty-rectangle rendering pipeline, and event model.

---

## 🌲 Component Hierarchy

Every `pdwidgets` UI forms a tree starting with an `App` controller, a root `Display` viewport, an active `Screen`, and nested `Widget` containers:

```mermaid
graph TD
    App["appdev.App<br/>(Event Loop & Async Timers)"] --> Display["pdwidgets.Display<br/>(Display Driver & Viewport)"]
    Display --> Screen1["pdwidgets.Screen (Active)"]
    Display -.-> Screen2["pdwidgets.Screen (Background)"]
    
    Screen1 --> AppBar["pd.AppBar / Header"]
    Screen1 --> Container["pd.Card / ScrollView"]
    
    Container --> Btn["pd.Button"]
    Container --> Slider["pd.Slider"]
    Container --> Label["pd.Label"]
```

### Core Hierarchy Classes:
1. **`Display`**: Glues the physical display driver (`display_drv`) to the application event loop. Tracks focus navigation and routes input events.
2. **`Screen`**: Represents a full-screen canvas. You can define multiple screens and switch between them using `display.show_screen(new_screen)`.
3. **`Widget`**: The base class for all UI elements. Owns geometry (`x, y, w, h`), visibility, parent/child relationships, background color, corner radius, and event callbacks.

---

## ⚡ The Rendering Pipeline & Dirty Rectangles

`pdwidgets` avoids costly full-screen redraws on embedded microcontrollers by tracking **dirty rectangles**:

```mermaid
sequenceDiagram
    participant User as User / Event
    participant Widget as pd.Widget
    participant Screen as pd.Screen
    participant Display as pd.Display
    participant Panel as Hardware Driver

    User->>Widget: widget.value = "New Text"
    Widget->>Widget: Mark self dirty
    Widget->>Screen: Bubble dirty Area(x, y, w, h)
    Note over Display: Event loop tick fires
    Display->>Screen: Flush dirty widgets
    Screen->>Panel: Bulk blit_rect(only changed region)
    Display->>Panel: panel.show()
```

### Lifecycle Rules:
* **Modifying State**: When you change a property (e.g. `widget.value = "..."` or `widget.bg = 0xF800`), the widget computes its bounding `Area` and schedules a redraw.
* **Flushing Draws**: Once the app's loop is running, redraws happen automatically on each frame tick.
* **Pre-run Setup**: If you configure widgets in a loop *before* the app's loop starts, call `pd.tick()` to force-render intermediate states.

---

## 🎮 Event Dispatch Pipeline

Input events from touch screens, mouse pointers, rotary encoders, or keyboards flow cleanly from the hardware driver to the targeted widget:

```mermaid
flowchart LR
    Input[Touch / Mouse / Key] --> App[appdev.App]
    App --> Display[pd.Display]
    Display --> HitTest{Hit Test on Screen}
    HitTest -->|Inside Bounds| Widget[Target Widget]
    Widget --> Callback[Registered Callback]
```

### Event Callback Signature:
Callbacks registered with `add_event_cb` receive `(sender, event)`:

```python
def button_handler(sender, event):
    print(f"Widget {sender} received event {event.type}")

button.add_event_cb(pd.events.MOUSEBUTTONUP, button_handler)
```
