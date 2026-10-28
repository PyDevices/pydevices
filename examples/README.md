# Examples

The smallest program that shows each of pydevices' core libraries working.
Each one says in its docstring what it needs and where it has been run.

| Example | What it shows |
|---|---|
| [appdev_simpletest.py](appdev_simpletest.py) | A timer, a tap and a key driving a box on the screen |
| [audiodev_simpletest.py](audiodev_simpletest.py) | Four notes from synthio through the board's speaker |
| [bledev_simpletest.py](bledev_simpletest.py) | The Bluetooth LE devices advertising nearby, on a board or a laptop |
| [bledev_central_simpletest.py](bledev_central_simpletest.py) | Reading a Bluetooth LE counter and writing it a message |
| [bledev_hid_host_simpletest.py](bledev_hid_host_simpletest.py) | Reading the keys a Bluetooth keyboard sends |
| [bledev_hid_keyboard_simpletest.py](bledev_hid_keyboard_simpletest.py) | Being a Bluetooth keyboard, with Adafruit's adafruit_hid |
| [bledev_midi_controller_simpletest.py](bledev_midi_controller_simpletest.py) | Playing notes on a Bluetooth MIDI instrument |
| [bledev_midi_instrument_simpletest.py](bledev_midi_instrument_simpletest.py) | Being a Bluetooth MIDI instrument that prints the notes it gets |
| [bledev_nus_client_simpletest.py](bledev_nus_client_simpletest.py) | Sending lines over a Bluetooth serial link and reading the answers |
| [bledev_nus_server_simpletest.py](bledev_nus_server_simpletest.py) | Answering lines sent over a Bluetooth serial link |
| [bledev_peripheral_simpletest.py](bledev_peripheral_simpletest.py) | Serving a Bluetooth LE counter for a phone or a board to read |
| [boarddev_simpletest.py](boarddev_simpletest.py) | What hardware a board offers, and a setting made before it starts |
| [displaydev_simpletest.py](displaydev_simpletest.py) | Boxes and a label drawn straight on the display |
| [events_simpletest.py](events_simpletest.py) | Input events, told apart by type, and one of your own |
| [keys_simpletest.py](keys_simpletest.py) | Key names, a Ctrl+S shortcut, and a USB keyboard's codes |
| [multimer_simpletest.py](multimer_simpletest.py) | Two timers at once, stopped by a third |
| [wifi_ap_simpletest.py](wifi_ap_simpletest.py) | A Wi-Fi network of the board's own, with a page for visitors |
| [wifi_simpletest.py](wifi_simpletest.py) | The networks in range, then joining yours |
| [wifi_station_simpletest.py](wifi_station_simpletest.py) | Joining a board's own network and reading its page |

The ones that come in pairs, such as a central and a peripheral, are two
ends of one link: run each on its own board, or put a phone or a laptop at
the other end. appkit, hmilink and midiports keep theirs in their own `examples/` folders.
The full apps are in
[pydevices-examples](https://github.com/PyDevices/pydevices-examples).
