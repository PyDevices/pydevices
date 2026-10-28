# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Make your own Wi-Fi network, and greet whoever joins it.

The board starts an access point, a network of its own that needs no
router, and serves a one-line web page on it. It prints the address of
each visitor. Use it where there's no network to join, or to set a board
up from a phone.

The visitor can be another board running wifi_station_simpletest.py, or a
phone or laptop: join the network, then open http://192.168.4.1/.

Needs: a board with Wi-Fi, and MicroPython with wifi installed.

Run it:
    mpremote run wifi_ap_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, visited by
another running wifi_station_simpletest.py.
"""

import socket

import wifi

# Change these to match your setup.
SSID = "PyDevices AP"
PASSWORD = "pydevices"  # eight characters or more; "" for an open network
VISITS = 3

# Start the access point. The board is the router, so its address is fixed.
wifi.radio.start_ap(SSID, PASSWORD)
address = wifi.radio.ipv4_address_ap
print("Started", SSID, "at", address)

# Listen for web browsers on port 80.
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(socket.getaddrinfo("0.0.0.0", 80)[0][-1])
server.listen(1)

# Answer each visit with a greeting, and say who it was.
for _ in range(VISITS):
    client, peer = server.accept()
    print("Visited by", peer[0] if isinstance(peer, tuple) else peer)
    client.recv(1024)  # the request; any page gets the same answer
    client.send(b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
    client.send(b"Hello from " + SSID.encode() + b"\n")
    client.close()

# Close the network once the visits are done.
server.close()
wifi.radio.stop_ap()
print("Stopped", SSID)
