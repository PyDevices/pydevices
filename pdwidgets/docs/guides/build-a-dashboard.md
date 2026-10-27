# Build a dashboard

A dashboard shows readings: a title bar, a status badge, a chart and a gauge.
This page builds one and shows how to update it.

```python
import board_config
import appdev
import pdwidgets as pd

app = appdev.App(board_config)
display = pd.Display(board_config.display_drv, app)
screen = pd.Screen(display, bg=0x1082)

bar = pd.AppBar(screen, title="Node #42")
status = pd.Badge(screen, value="Online", align=pd.ALIGN.RIGHT, align_to=bar)

chart = pd.Chart(screen, x=10, y=50, w=300, h=100, fg=0x07E0,
                 value=[20, 22, 21, 24, 28, 32, 29, 31, 35, 30])

gauge = pd.Gauge(screen, value=0.75, x=10, y=160)   # 0 to 1
```

`Chart`'s `value` is the list of numbers to plot and `fg` sets the line color.
`Gauge`'s value runs from 0 to 1.

To keep it live, assign a new `value` and the widget redraws only what
changed. The display runs your task on a timer:

```python
readings = [20, 22, 21, 24, 28, 32, 29, 31, 35, 30]

def update():
    readings.pop(0)
    readings.append(readings[-1] + 1)      # a new reading would go here
    chart.value = list(readings)
    gauge.value = min(1.0, gauge.value + 0.01)

display.add_task(update, 1000)   # every 1000 ms
```

`add_task(callback, delay)` takes a zero-argument function and an interval in
milliseconds, and returns a task you can pass to `display.remove_task`.
