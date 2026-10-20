# Newcomer's guide to pdwidgets

`pdwidgets` is PyDevices' pure-Python widget toolkit for touchscreen, desktop,
and web interfaces. It builds buttons, forms, navigation, charts, dialogs, and
layout containers on a PyDevices display driver and `pygraphics`.

## Start by building a widget tree

The normal application path is `appdev.App` → `Display` → `Screen` → widgets.
`Display` connects a board's display driver to the shared app coordinator, so
the app owns input and periodic rendering; most applications do not call
`app.run()` themselves.

The README's [Quick Start](https://github.com/PyDevices/pdwidgets#quick-start-interactive-button--screen)
builds a screen with a label and a button on that path.

Labels use `value=` and buttons use `label=`; there is no `text=` keyword.
Callbacks receive `(sender_or_data, event)` in that order.

## Installation

For MicroPython, install the package and its MIP dependencies explicitly:

```python
import mip
for package in ("pydevices", "pygraphics", "palettes", "pdwidgets"):
    mip.install(package, index="https://PyDevices.github.io/mip")
```

For desktop CPython, install `pydevices-pdwidgets` from TestPyPI. The example's
`board_config` comes from `pydevices-desktop`; Linux and macOS also need SDL2.
The root README has the supported commands and platform details.

## How a frame moves

```text
input -> appdev.App -> Display -> widget hit testing -> callback
                               |
widget state change -> dirty Area -> render tick -> driver flush
```

`Widget` provides geometry, parent/child ownership, visibility, invalidation,
and event callbacks. `Screen` is a full-display page. State changes mark only
their affected `Area` dirty, allowing the driver to flush changed regions
instead of redrawing the panel. Call `pd.tick()` only when setup needs an
intermediate render before the app loop has started.

## Repository map

| Path | Purpose |
|---|---|
| `lib/pdwidgets/` | Core display, screen, widget, task, theme, and utility code. |
| `lib/pdwidgets/widgets/` | Lazily imported concrete widgets and layout containers. |
| `lib/pdwidgets/icons/` | Importable bitmap icons; no runtime asset files are required. |
| `docs/architecture.md` | Authoritative tree, dirty-render, and lifecycle description. |
| `docs/input-and-events.md` | Input sources, callbacks, and focus navigation. |
| `docs/layout-guide.md` | Alignment, percentage sizing, and Row/Column layouts. |
| `tests/` | Unit, API, import, rendering, and documentation-example checks. |

The top-level module imports the core eagerly but resolves widget classes
lazily. On a memory-constrained target, use a direct import such as
`from pdwidgets.widgets.button import Button` when import cost matters.

## Layout and themes

Use `ALIGN`, `pct`, `Row`, and `Column` before hard-coding a screen layout.
Themes come from `palettes` and belong to the display. `Widget` is also a
lightweight custom container; subclasses retain its hit testing and
invalidation behavior. See [the layout guide](layout-guide.md),
[theming](theming.md), and [the widget catalog](widget-catalog.md).

## Contributor boundary

The package is source-only and development imports sibling `pydevices`,
`pygraphics`, and `palettes` checkouts. Follow the `PYTHONPATH` test command
in [AGENTS.md](https://github.com/PyDevices/pdwidgets/blob/main/AGENTS.md); bare unit-test discovery cannot resolve those
dependencies. Regenerate the widget dependency graph after widget edits with
`scripts/pdwidgets_widget_deps.py`.

Safe first contributions are a focused widget test, a documentation recipe,
or a correction to an existing widget API. Keep custom widgets on the normal
event and invalidation path rather than adding a separate render loop.
