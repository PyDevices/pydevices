# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The file-transfer gate, board side: serve files and the REPL over BLE and return.

Run it from ``/main.py`` (mpftp's serial connect soft-resets the board, which
turns Bluetooth off), then drive it over the air with ``files_client.py`` or
``mpftp -d ble://bledev-files``. The password is a test value, not a secret.

``PLANT = "flip"`` flips one bit in the third packet of every file read, which
the client's byte-for-byte check must catch. ``WINDOW`` is the free space the
board offers per round trip (CircuitPython offers 512).
"""
import bledev.filetransfer as ft

PASSWORD = "bledev-gate-pw"
NAME = "bledev-files"
PLANT = None
WINDOW = ft.WINDOW

if PLANT == "flip":
    _packet = ft.FileServer.packet

    def packet(self, size):
        data = _packet(self, size)
        if data is not None and len(data) > 28:
            self._plant = getattr(self, "_plant", 0) + 1
            if self._plant == 3:
                data = data[:-1] + bytes((data[-1] ^ 0x10,))
                self._pending = data
        return data

    ft.FileServer.packet = packet

ft.start(password=PASSWORD, name=NAME, window=WINDOW)
print("bledev.filetransfer serving as", NAME, "window", WINDOW, "plant", PLANT)
