# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Make your own Wi-Fi network, and greet whoever joins it.

The board starts an access point, a network of its own that needs no
router, and serves a one-line web page on it. It prints the address of
each visitor. Use it where there's no network to join, or to set a board
up from a phone.

The visitor can be another board running wifi_station_simpletest.py, or a
phone or laptop: join the network, then open http://192.168.4.1:8080/.

Needs: a board with Wi-Fi: CircuitPython, or MicroPython with wifi
installed.

Run it:
    mpremote run wifi_ap_simpletest.py
On CircuitPython, copy it to the board as code.py.

Tested on: ESP32-S3 boards on MicroPython 1.30 preview and CircuitPython
11.0 alpha, each with the other running wifi_station_simpletest.py.
"""

import wifi

# Change these to match your setup.
SSID = "PyDevices AP"
PASSWORD = "pydevices"  # eight characters or more; "" for an open network
VISITS = 3
PORT = 8080  # not 80: CircuitPython's own web workflow may hold it

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


# Start the access point. The board is the router, so its address is fixed.
wifi.radio.start_ap(SSID, PASSWORD)
address = None
while address is None:  # CircuitPython gives it a moment after starting
    address = wifi.radio.ipv4_address_ap
print("Started", SSID, "at", address)

# Close the network once the visits are done, or on Ctrl-C: on
# CircuitPython the access point outlives the program otherwise.
try:
    # Listen for web browsers.
    server = pool.socket()
    server.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
    server.bind(pool.getaddrinfo("0.0.0.0", PORT)[0][-1])
    server.listen(1)

    # Answer each visit with a greeting, and say who it was.
    request = bytearray(1024)
    for _ in range(VISITS):
        client, peer = server.accept()
        client.settimeout(5)  # wait for the request; CircuitPython's may not
        print("Visited by", peer[0] if isinstance(peer, tuple) else peer)
        receive(client, request)  # the request; any page gets the same answer
        client.send(b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n")
        client.send(b"Hello from " + SSID.encode() + b"\n")
        client.close()
    server.close()
finally:
    wifi.radio.stop_ap()
print("Stopped", SSID)
