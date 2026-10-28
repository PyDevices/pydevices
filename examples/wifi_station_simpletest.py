# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Join a board's own Wi-Fi network and read its web page.

The board joins an access point by name, prints the address it was given,
and fetches the page at the access point's address.

The access point can be another board running wifi_ap_simpletest.py, or
any network with a web server on it: change SSID, PASSWORD and PAGE_HOST.
Joining it leaves the network the board was on, so reset the board to
rejoin.

Needs: a board with Wi-Fi, and MicroPython with wifi installed.

Run it:
    mpremote run wifi_station_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview, joining another
running wifi_ap_simpletest.py.
"""

import socket

import wifi

# Change these to match your setup.
SSID = "PyDevices AP"
PASSWORD = "pydevices"
PAGE_HOST = "192.168.4.1"  # an access point board's own address

# Join the access point.
print("Joining", SSID)
wifi.radio.connect(SSID, PASSWORD)
print("Joined, with address", wifi.radio.ipv4_address)

# Fetch the page and print what it says.
s = socket.socket()
s.connect(socket.getaddrinfo(PAGE_HOST, 80)[0][-1])
s.send(b"GET / HTTP/1.0\r\nHost: " + PAGE_HOST.encode() + b"\r\n\r\n")
reply = b""
while True:
    data = s.recv(512)
    if not data:
        break
    reply += data
s.close()
print("The page says:", reply.split(b"\r\n\r\n", 1)[-1].decode().strip())
