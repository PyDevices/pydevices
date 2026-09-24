# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Wi-Fi throughput from a laptop: read ``coex_server.py``'s TCP source.

    python tcp_pull.py BOARD_IP [SECONDS]

Prints KB/s for each second and the average.
"""
import socket
import sys
import time

ip = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 10
s = socket.create_connection((ip, 5001), timeout=5)
total = 0
t0 = time.monotonic()
mark, marked = t0, 0
while time.monotonic() - t0 < seconds:
    data = s.recv(65536)
    if not data:
        break
    total += len(data)
    now = time.monotonic()
    if now - mark >= 1:
        print("  {:.1f} s: {:.1f} KB/s".format(now - t0, (total - marked) / 1024 / (now - mark)), flush=True)
        mark, marked = now, total
elapsed = time.monotonic() - t0
s.close()
print("TCP {} bytes in {:.1f} s = {:.1f} KB/s".format(total, elapsed, total / 1024 / elapsed))
