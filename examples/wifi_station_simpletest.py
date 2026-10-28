# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Join a board's own Wi-Fi network and read its web page.

The board joins an access point by name, prints the address it was given,
and fetches the page at the access point's address.

The access point can be another board running wifi_ap_simpletest.py, or
any network with a web server on it: change SSID, PASSWORD, PAGE_HOST and PAGE_PORT.
Joining it leaves the network the board was on, so reset the board to
rejoin.

Needs: a board with Wi-Fi: CircuitPython, or MicroPython with wifi
installed.

Run it:
    mpremote run wifi_station_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running wifi_ap_simpletest.py.
"""

import wifi

# Change these to match your setup.
SSID = "PyDevices AP"
PASSWORD = "pydevices"
PAGE_HOST = "192.168.4.1"  # an access point board's own address
PAGE_PORT = 8080

# CircuitPython makes sockets from a pool on the radio; MicroPython has socket.
try:
    import socketpool

    pool = socketpool.SocketPool(wifi.radio)
except ImportError:
    import socket as pool


def receive(sock, buf):
    """Read what has arrived into buf, and return how many bytes.

    CircuitPython's sockets read with recv_into, MicroPython's with recv.
    """
    if hasattr(sock, "recv_into"):
        return sock.recv_into(buf)
    data = sock.recv(len(buf))
    buf[: len(data)] = data
    return len(data)


# Join the access point.
print("Joining", SSID)
wifi.radio.connect(SSID, PASSWORD)
print("Joined, with address", wifi.radio.ipv4_address)

# Fetch the page and print what it says.
s = pool.socket()
s.connect(pool.getaddrinfo(PAGE_HOST, PAGE_PORT)[0][-1])
s.send(b"GET / HTTP/1.0\r\nHost: " + PAGE_HOST.encode() + b"\r\n\r\n")

# Read until the page closes the connection.
chunk = bytearray(512)
reply = b""
while True:
    n = receive(s, chunk)
    if not n:
        break
    reply += chunk[:n]
s.close()
print("The page says:", reply.split(b"\r\n\r\n", 1)[-1].decode().strip())
