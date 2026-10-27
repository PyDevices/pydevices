# Lay out widgets

Hard-coded `x` and `y` values fit one screen. This page shows how to pin
widgets to an edge or the center, size them as a share of their parent, and
stack them in rows and columns, so one program fits panels of different sizes.

## Pin a widget to a spot

`align` says which spot in the parent a widget hangs from, and `x` and `y` then
move it from that spot:

```python
import pdwidgets as pd

# A top bar across the screen
bar = pd.Widget(screen, w=screen.width, h=30, bg=0x2124, align=pd.ALIGN.TOP)

# Text in the middle of a card
card = pd.Card(screen, w=200, h=120, align=pd.ALIGN.CENTER)
title = pd.Label(card, value="Settings", align=pd.ALIGN.TOP, y=8)
```

Each flag names the edge or corner it sits against:

| Flag | Where the widget goes |
|---|---|
| `ALIGN.CENTER` | The middle of the parent. This is a `Label`'s default. |
| `ALIGN.TOP`, `ALIGN.BOTTOM` | Against that edge, centered along it. |
| `ALIGN.LEFT`, `ALIGN.RIGHT` | Against that edge, centered along it. |
| `ALIGN.TOP_LEFT`, `ALIGN.TOP_RIGHT`, `ALIGN.BOTTOM_LEFT`, `ALIGN.BOTTOM_RIGHT` | That corner. This is the default for most widgets, `Button` included. |

A few widgets start somewhere else: a `Label` is centered, a `Slider` and a
`ScrollBar` sit at the bottom (the right edge when vertical), an `AppBar` at the
top, and a `Keyboard` and a `Toast` at the bottom. Their `x` and `y` count from
that spot, so a label placed with `x` and `y` alone lands off where you expect.
Pass `align=pd.ALIGN.TOP_LEFT` to count from the top-left corner.

## Put one widget beside another

The `OUTER_` flags place a widget outside another one, and `align_to` names
which:

```python
name = pd.Label(screen, value="Volume", align=pd.ALIGN.TOP_LEFT, x=10, y=10)
level = pd.Label(screen, value="80%", align=pd.ALIGN.OUTER_RIGHT, align_to=name)
```

`OUTER_RIGHT` puts `level` just past the right edge of `name`. There is an
outer flag for each of the eight edges and corners, such as `OUTER_BOTTOM` and
`OUTER_TOP_LEFT`.

## Size by percentage

`pd.pct.Width` and `pd.pct.Height` give a size that follows another widget's.
Pass one as `w` or `h`:

```python
import pdwidgets as pd

# A card 90% as wide and 80% as tall as the screen
card = pd.Card(screen, w=pd.pct.Width(90, screen), h=pd.pct.Height(80, screen),
               align=pd.ALIGN.CENTER)

# Two buttons, each 45% of the card's width
cancel = pd.Button(card, label="Cancel", w=pd.pct.Width(45, card), h=36,
                   align=pd.ALIGN.BOTTOM_LEFT)
ok = pd.Button(card, label="OK", w=pd.pct.Width(45, card), h=36,
               align=pd.ALIGN.BOTTOM_RIGHT)
```

If the reference widget is resized, the percentage size follows it.

## Stack widgets in a row or column

`Row` and `Column` place their children one after another with a fixed
`spacing` between them:

```python
col = pd.Column(card, x=10, y=10, spacing=10)

pd.Label(col, value="Enter details:")
pd.TextInput(col, hint="Name", w=180)
pd.TextInput(col, hint="Email", w=180)
pd.Button(col, label="Submit", w=180)
```

`Grid` fills fixed columns instead: `pd.Grid(parent, columns=3, spacing=4)`.
Each child gets a cell, in the order you create them.

## Fit different panels

Work from the display's size instead of numbers. `screen.width` and
`screen.height` are the panel's size in pixels, so these hold on any panel:

- On a small panel, use one column of cards with little padding.
- On a medium panel, a top `AppBar` with the content under it works.
- On a large landscape panel, put a `Drawer` or a side column beside the content.
