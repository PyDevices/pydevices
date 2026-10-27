# How pdwidgets works

pdwidgets is a widget toolkit written in pure Python, for touchscreen, desktop
and browser interfaces. It builds buttons, forms, navigation, charts, dialogs
and layout containers on a pydevices display driver and
[pygraphics](https://pygraphics.readthedocs.io), with no native code to
compile.

## A widget tree

An application is a tree. `appdev.App` owns input and timers, a `Display` joins
it to a display driver, a `Screen` fills the display, and widgets nest inside
the screen. Each widget has a parent, a rectangle, and a list of children.

`Display` connects a board's display driver to the shared app coordinator, so
the app owns input and the periodic redraw. That is why most programs never call
a draw function: they create widgets, set `value` and register callbacks, and
the app does the rest. [Your first program](../get-started/first-program.md)
builds one.

## How a frame moves

```text
input -> appdev.App -> Display -> widget hit test -> callback
                                |
widget state change -> dirty Area -> render tick -> driver flush
```

A widget changing a property marks itself invalid. The change climbs to the
`Display`, which draws only the invalid widgets into an off-screen buffer on its
next tick and then copies only the changed rectangles, each an `Area`, to the
panel. A static screen costs nothing per frame. The
[architecture page](architecture.md) follows one frame through the code.

Call `pd.tick()` to force a frame by hand, such as when setup needs a render
before the app's loop has started.

## What it costs

`Display` keeps one buffer the size of the panel at the panel's color depth, so
a 320 by 480 panel at 16 bits is 307,200 bytes. That's a large allocation
on a small board, so pdwidgets suits boards with PSRAM, or a smaller panel.

The top-level `pdwidgets` module loads the core eagerly and each widget class
the first time you name it. On a board short of memory, import the widget you
need directly, such as `from pdwidgets.widgets.button import Button`.

## Themes and layout

Layout uses `ALIGN`, `pct`, `Row`, `Column` and `Grid`, so a screen follows its
panel's size; see [Lay out widgets](../guides/lay-out-widgets.md). Colors come
from a Material Design palette each display builds with
[palettes](https://palettes.readthedocs.io), and from color roles on the display;
see [Theme an app](../guides/theme-an-app.md). `Widget` is also a plain
container, and a subclass keeps its hit testing and redraw behavior, so a custom
widget stays on the normal event and invalidation path instead of adding a
render loop of its own.

## What it depends on

pdwidgets imports `appdev` from pydevices, `palettes` and `pygraphics`.
[Install](../get-started/install.md) brings them in. To work on pdwidgets
itself, see [CONTRIBUTING.md](https://github.com/PyDevices/pydevices/blob/main/pdwidgets/CONTRIBUTING.md).
