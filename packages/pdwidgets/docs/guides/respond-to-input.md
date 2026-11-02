# Respond to input

Widgets get taps, clicks, key presses and wheel turns from the app, and call
back into your code. This page shows how to listen for them, how to react when
a value changes, and how to move keyboard focus between text fields. The list
of events is in [Events](../events.md).

## Run code when a widget is clicked

Use `add_event_cb` on any widget. The callback is called as
`callback(sender, event)`: the widget first, then the event.

```python
import pdwidgets as pd

button = pd.Button(screen, label="Click me", x=10, y=10)

def handle_click(sender, event):
    print("clicked at", event.pos)

button.add_event_cb(pd.events.MOUSEBUTTONUP, handle_click)
```

`MOUSEBUTTONUP` is a touch lifting off or a mouse button released, which is
the usual moment to act. `MOUSEBUTTONDOWN` fires when it first lands. Touch
screens, mice and encoder buttons all arrive as these same events, so one
callback serves all of them.

To pass your own object instead of the widget, give `add_event_cb` a `data`
argument. The callback receives it as its first argument.

## React when a value changes

Any widget whose `value` changes can tell you. Set a change callback, which
gets the widget:

```python
slider = pd.Slider(screen, value=0.0, x=10, y=60)   # the value runs from 0 to 1

def on_change(widget):
    print("slider is at", widget.value)

slider.set_change_cb(on_change)
```

This is the same for a `Switch`, a `NumberStepper`, a `CheckBox` and the rest:
read `value` in the callback. Setting `value` from your own code calls it too.

## Turn the wheel or press a key

A rotary encoder reports as `MOUSEWHEEL` for its turns and
`MOUSEBUTTONDOWN` and `MOUSEBUTTONUP` for its button. A keypad or keyboard
reports `KEYDOWN` and `KEYUP`. Register for them the same way:

```python
def on_key(sender, event):
    print("key", event.key)

screen.add_event_cb(pd.events.KEYDOWN, on_key)
```

A `ScrollView` already scrolls on a wheel turn, and a `Slider` follows a drag,
so you only register for events a built-in widget doesn't handle.

## Move keyboard focus between text fields

`TextInput` and `PasswordField` take keystrokes while they have focus. A click
on one focuses it. Without a pointer, `Tab` moves focus to the next field,
`Shift+Tab` to the previous one, and the arrow keys move it too. Give focus
from code with the display's focus manager:

```python
name = pd.TextInput(screen, hint="Name", x=10, y=10, w=200)
email = pd.TextInput(screen, hint="Email", x=10, y=50, w=200)

display.focus_manager.focus(name)
```

Only text fields join the focus ring. A `Button` or a `Switch` isn't reached by
`Tab`, so a device with no touch needs another way to activate them, such as
a callback on a key you choose.

An on-screen `Keyboard` types into whichever field has focus:
`pd.Keyboard(screen, target=name)`.
