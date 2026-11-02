# Events

Widgets receive these six event types. Input devices on the app produce them,
and `Display` routes each to the widget it hits. They are constants on
`pd.events`; [Respond to input](guides/respond-to-input.md) shows how to
register for one.

| Constant | Comes from | Fires when |
|---|---|---|
| `MOUSEBUTTONDOWN` | Touch screen, mouse, encoder button | A touch lands, or a button goes down. |
| `MOUSEBUTTONUP` | Touch screen, mouse, encoder button | The touch lifts, or the button is released. |
| `MOUSEMOTION` | Touch screen, mouse | The pointer moves, or a finger drags. |
| `MOUSEWHEEL` | Mouse wheel, rotary encoder | The wheel or encoder turns a step. |
| `KEYDOWN` | Keyboard, keypad | A key goes down. |
| `KEYUP` | Keyboard, keypad | A key is released. |

Pointer events carry `event.pos`, the `(x, y)` of the touch on the display. Key
events carry `event.key`.

A joystick reports `JOYAXISMOTION`, `JOYBUTTONDOWN` and similar events to the
app, but widgets don't receive them. Listen with `app.on(...)` and call into
your widgets from there.

The callback signature is `callback(sender, event)`. The value-change callback
set with `set_change_cb` is separate: it takes `callback(widget)`.
