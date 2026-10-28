# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List the Wi-Fi networks in range, then join yours.

The program scans and prints each network's name, signal strength and
channel, strongest first. Then it joins the network named in secrets.py
and prints the address the board was given. It uses CircuitPython's
wifi.radio API, so the same code runs on both.

Needs: a board with Wi-Fi, and a secrets.py on it that holds
WIFI_SSID and WIFI_PASSWORD. On MicroPython, copy wifi.py onto the board
too; CircuitPython has wifi built in.

Run it:
    mpremote run wifi_simpletest.py

Tested on: an ESP32-S3 board on MicroPython 1.30 preview.
"""

import wifi

from secrets import WIFI_PASSWORD, WIFI_SSID

# List every network in range, strongest first.
print("Networks in range:")
for network in wifi.radio.start_scanning_networks():
    print("  %-32s %4d dBm  channel %d" % (network.ssid, network.rssi, network.channel))
wifi.radio.stop_scanning_networks()

# Join yours. This raises ConnectionError on a wrong password or a
# network that isn't in range.
print("Joining", WIFI_SSID)
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)

# Say where the board is on the network.
print("Address:", wifi.radio.ipv4_address)
print("Signal: ", wifi.radio.ap_info.rssi, "dBm")
