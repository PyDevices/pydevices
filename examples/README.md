# Examples

The smallest program that shows each of pydevices' core libraries working.
Each one says in its docstring what it needs and where it has been run.

| Example | What it shows |
|---|---|
| [appdev_simpletest.py](appdev_simpletest.py) | A timer, a tap and a key driving a box on the screen |
| [audiodev_simpletest.py](audiodev_simpletest.py) | Four notes from synthio through the board's speaker |
| [bledev_simpletest.py](bledev_simpletest.py) | The Bluetooth LE devices advertising nearby, on a board or a laptop |
| [bledev_hid_host_simpletest.py](bledev_hid_host_simpletest.py) | Reading the keys a Bluetooth keyboard sends |
| [bledev_hid_keyboard_simpletest.py](bledev_hid_keyboard_simpletest.py) | Being a Bluetooth keyboard, with Adafruit's adafruit_hid |
| [boarddev_simpletest.py](boarddev_simpletest.py) | What hardware a board offers, and a setting made before it starts |
| [displaydev_simpletest.py](displaydev_simpletest.py) | Boxes and a label drawn straight on the display |
| [events_simpletest.py](events_simpletest.py) | Input events, told apart by type, and one of your own |
| [keys_simpletest.py](keys_simpletest.py) | Key names, a Ctrl+S shortcut, and a USB keyboard's codes |
| [multimer_simpletest.py](multimer_simpletest.py) | Two timers at once, stopped by a third |
| [wifi_simpletest.py](wifi_simpletest.py) | The networks in range, then joining yours |

appkit, hmilink and midiports keep theirs in their own `examples/` folders.
The full apps are in
[pydevices-examples](https://github.com/PyDevices/pydevices-examples).
