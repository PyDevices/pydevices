# Architecture

The widget tree, the dirty-rectangle drawing pipeline and the event path.

## The widget tree

Every pdwidgets UI is a tree: an `App` controller, a `Display`, the active `Screen` and nested `Widget` containers.

```{mermaid}
graph TD
    App["appdev.App<br/>(Event Loop & Async Timers)"] --> Display["pdwidgets.Display<br/>(Display Driver & Viewport)"]
    Display --> Screen1["pdwidgets.Screen (Active)"]

    Screen1 --> AppBar["pd.AppBar / Header"]
    Screen1 --> Container["pd.Card / ScrollView"]
    
    Container --> Btn["pd.Button"]
    Container --> Slider["pd.Slider"]
    Container --> Label["pd.Label"]
```

The three core classes:
1. **`Display`**: Glues the physical display driver (`display_drv`) to the application event loop. Owns the focus manager and routes input events to widgets.
2. **`Screen`**: One full-display page. A display shows one at a time: assign `display.active_screen = new_screen` to switch.
3. **`Widget`**: The base class for all UI elements. Owns geometry (`x, y, w, h`), visibility, parent/child relationships, background color, corner radius, and event callbacks.


## Drawing: dirty rectangles

pdwidgets avoids full-screen redraws by tracking dirty rectangles. Widgets draw into a buffer the size of the panel, and only the changed rectangles are copied to the panel:

```{mermaid}
sequenceDiagram
    participant Code as Your code
    participant Widget as pd.Widget
    participant Display as pd.Display
    participant Panel as Display driver

    Code->>Widget: widget.value = "New text"
    Widget->>Display: Invalidated, flagged dirty up the tree
    Note over Display: Timer tick
    Display->>Widget: Draw invalid widgets into the buffer
    Display->>Display: Record each widget's Area as dirty
    Note over Display: Next tick
    Display->>Panel: Copy each dirty Area, then show()
```

What each step does:

- Changing a property, such as `widget.value = "..."` or `widget.bg = 0xF800`,
  marks the widget and its children invalid and flags the widget dirty in each
  ancestor.
- A tick that finds nothing waiting to be copied runs due tasks, then redraws
  the invalid widgets, front to back in `children` order, into the buffer. Each
  redrawn widget's `Area` joins the dirty list.
- The next tick merges dirty areas that touch or overlap and copies each to the
  driver, then calls the driver's `show()`.
- The app drives `tick()` from a shared timer every 10 ms by default
  (`Display.tick_period`), so once the app is running, redraws just happen.
- Before the app's loop starts, call `pd.tick()` yourself to render
  intermediate states.

## Input

Input events from touch screens, mouse pointers, rotary encoders and keyboards reach the widget under them:

```{mermaid}
flowchart LR
    Input[Touch / Mouse / Key] --> App[appdev.App]
    App --> Display[pd.Display]
    Display --> HitTest{Hit Test on Screen}
    HitTest -->|Inside Bounds| Widget[Target Widget]
    Widget --> Callback[Registered Callback]
```

The event types a widget can receive are listed in [Events](../events.md).
Callbacks registered with `add_event_cb` receive `(sender, event)`:

```python
def button_handler(sender, event):
    print(f"Widget {sender} received event {event.type}")

button.add_event_cb(pd.events.MOUSEBUTTONUP, button_handler)
```
