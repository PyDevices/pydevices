# Examples

The smallest program that shows each of pydevices' core libraries working.
Each one says in its docstring what it needs and where it has been run.

| Example | What it shows |
|---|---|
| [appdev_simpletest.py](appdev_simpletest.py) | A timer, a tap and a key driving a box on the screen |
| [appdev_touch_calibrate.py](appdev_touch_calibrate.py) | Finding the touch_rotation_table for a board_config by touching four corners |
| [audiodev_simpletest.py](audiodev_simpletest.py) | Four notes from synthio through the board's speaker |
| [audiodev_mp3_player.py](audiodev_mp3_player.py) | Every MP3 file in a folder on the microSD card, one after another |
| [audiodev_voice_recorder.py](audiodev_voice_recorder.py) | The board's microphone recorded to a WAV file on the microSD card |
| [bledev_simpletest.py](bledev_simpletest.py) | The Bluetooth LE devices advertising nearby, on a board or a laptop |
| [bledev_battery_simpletest.py](bledev_battery_simpletest.py) | Showing a battery level and device details to any Bluetooth LE app |
| [bledev_cyclingpower_simpletest.py](bledev_cyclingpower_simpletest.py) | Being a cycling power meter for bike apps |
| [bledev_cyclingspeed_simpletest.py](bledev_cyclingspeed_simpletest.py) | Being a cycling speed and cadence sensor for bike apps |
| [bledev_environmental_simpletest.py](bledev_environmental_simpletest.py) | Being a weather sensor any Bluetooth LE app can read |
| [bledev_heartrate_simpletest.py](bledev_heartrate_simpletest.py) | Being a heart rate monitor for fitness apps |
| [bledev_improv_simpletest.py](bledev_improv_simpletest.py) | Letting a phone or computer set up the board's Wi-Fi over Bluetooth |
| [bledev_repl_simpletest.py](bledev_repl_simpletest.py) | Reaching the board's REPL over Bluetooth, behind a password |
| [bledev_filetransfer_simpletest.py](bledev_filetransfer_simpletest.py) | Copying files to and from the board over Bluetooth |
| [bledev_private_address.py](bledev_private_address.py) | Advertising under an address that changes |
| [bledev_runningspeed_simpletest.py](bledev_runningspeed_simpletest.py) | Being a running foot pod for fitness apps |
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
| [usb_device_audio_headset.py](usb_device_audio_headset.py) | Being a USB headset that plays back what the computer plays to it |
| [usb_device_audio_simpletest.py](usb_device_audio_simpletest.py) | Being a USB microphone that sends a tone |
| [usb_device_cdc_simpletest.py](usb_device_cdc_simpletest.py) | A second USB serial port that shouts back what you type |
| [usb_device_midi_simpletest.py](usb_device_midi_simpletest.py) | Being a USB MIDI device that plays a scale and shows what it hears |
| [usb_device_net_simpletest.py](usb_device_net_simpletest.py) | A network link to your computer over the USB cable |
| [usb_device_video_simpletest.py](usb_device_video_simpletest.py) | Being a USB webcam that shows a moving grey ramp |
| [usb_hid_absolute_pointer.py](usb_hid_absolute_pointer.py) | Moving your computer's pointer to the corners of the screen and around a circle |
| [usb_hid_gamepad.py](usb_hid_gamepad.py) | Being a USB gamepad that works through its buttons, hat and axes |
| [vtterm_simpletest.py](vtterm_simpletest.py) | The board's REPL on its display, in color |
| [wifi_ap_simpletest.py](wifi_ap_simpletest.py) | A Wi-Fi network of the board's own, with a page for visitors |
| [wifi_simpletest.py](wifi_simpletest.py) | The networks in range, then joining yours |
| [wifi_station_simpletest.py](wifi_station_simpletest.py) | Joining a board's own network and reading its page |

The ones that come in pairs, such as a central and a peripheral, are two
ends of one link: run each on its own board, or put a phone or a laptop at
the other end. hmilink, midiports, palettes and pdwidgets keep theirs in their own `examples/` folders.
The full apps are in the [apps repo](https://github.com/PyDevices/apps).
