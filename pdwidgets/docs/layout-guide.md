# Layout & Sizing

Building flexible, responsive layouts for diverse microcontroller screen sizes and resolutions.

---

## 1. Alignment Anchors (`pd.ALIGN`)

Instead of hard-coding absolute $(x, y)$ coordinates for every screen size, use **`ALIGN`** flags on widgets:

| Alignment Flag | Position within Parent Container |
|:---|:---|
| `ALIGN.TOP` | Centered horizontally against top edge |
| `ALIGN.BOTTOM` | Centered horizontally against bottom edge |
| `ALIGN.LEFT` | Centered vertically against left edge |
| `ALIGN.RIGHT` | Centered vertically against right edge |
| `ALIGN.CENTER` | Centered both horizontally and vertically |
| `ALIGN.TOP_LEFT` | Top-left corner |
| `ALIGN.TOP_RIGHT` | Top-right corner |
| `ALIGN.BOTTOM_LEFT` | Bottom-left corner |
| `ALIGN.BOTTOM_RIGHT` | Bottom-right corner |

```python
import pdwidgets as pd

# Top navigation bar
bar = pd.Widget(screen, w=screen.width, h=30, bg=0x2124, align=pd.ALIGN.TOP)

# Centered modal title
title = pd.Label(card, value="Settings", align=pd.ALIGN.CENTER)
```

---

## 2. Percentage-Based Sizing (`pct`)

`pdwidgets.pct` enables proportional dimensions relative to the parent's width and height:

```python
import pdwidgets as pd
from pdwidgets import pct

# A card occupying 90% of screen width and 80% of screen height
card = pd.Card(screen, w=pct.w(90), h=pct.h(80), align=pd.ALIGN.CENTER)

# Two buttons each taking 45% width
btn1 = pd.Button(card, label="Cancel", w=pct.w(45), h=36)
btn2 = pd.Button(card, label="OK", w=pct.w(45), h=36)
```

---

## 3. Flex Containers: `Row` and `Column`

`Row` and `Column` automatically arrange children along horizontal or vertical axes with consistent spacing:

```python
# Vertical layout column with 10px gap between children
col = pd.Column(card, x=10, y=10, spacing=10)

pd.Label(col, value="Enter Details:")
pd.TextInput(col, hint="Name", w=180)
pd.TextInput(col, hint="Email", w=180)
pd.Button(col, label="Submit", w=180)
```

---

## 4. Multi-Resolution Best Practices

| Target Panel | Resolution | Best Layout Approach |
|:---|:---|:---|
| **Round Smartwatch** | 240×240 (GC9A01) | Radial / centered stack using `ALIGN.CENTER` |
| **Small TFT / OLED** | 128×128 / 160×128 (ST7735) | Single-column cards with minimal padding |
| **Standard TFT** | 320×240 (ILI9341 / ST7789) | Two-column cards or top AppBar + content area |
| **Large Landscape** | 480×320 / 800×480 | Multi-column grid with side navigation Drawer |
