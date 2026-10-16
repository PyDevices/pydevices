# Freezing midiports into a firmware. adafruit_midi isn't here: package.json
# fetches it from Adafruit at a pinned tag, and a firmware that wants it
# frozen adds Adafruit's files itself. The desktop ports (windows, linux)
# stay out of a board's flash. usb_device needs micropython-lib's
# usb-device-midi; require it here too if the firmware freezes MIDI over USB.
# usb_host needs usbif's usb-core (usb.core) and a firmware with its host.
metadata(
    description="MIDI ports for adafruit_midi: USB device, UART, and a computer's own MIDI ports.",
    version="0.0.1",
    license="MIT",
)

package("midiports", files=("__init__.py", "uart.py", "usb_device.py", "usb_host.py", "usbif_shim.py"))
