# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check usb.host.net against a real CDC-ECM adapter.

Finds the adapter, brings it up, waits for DHCP and prints the address, the
frame counts and a DNS lookup. A CDC-ECM adapter is a USB Ethernet dongle whose
descriptor says class 2 subclass 6 (check with a plain usb.core.find), or a
board or computer presenting one. Plug the adapter into a network with DHCP.

Needs: an ESP32-S3 or P4 board running a firmware built with the usbhost
change that lets host_net_start take an alternate setting, and the adapter on
the host port.

Run it:

    mpftp run --follow tests/hardware/usb_host_ecm_check.py

Expect: kind CDC-ECM, a MAC address, an address from the network's DHCP, rx and
tx frame counts above zero, and an address for the host name.
"""

import socket
import time

import usb.core
from usb.host.net import Tether

usb.core.start()
net = Tether()
print("kind", net.kind)
net.active(True)
print("mac", net.config("mac"))
for _ in range(100):
    if net.isconnected():
        break
    time.sleep_ms(200)
net.set_default()
print("ifconfig", net.ifconfig())
print("stats", net.stats())
print("lookup", socket.getaddrinfo("example.com", 80)[0][-1])
net.active(False)
