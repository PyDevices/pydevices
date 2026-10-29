# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List your Spotify devices.

Prints the name, type and active state of every device that can play your music. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_devices.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()

    for device in client.devices():
        print("-", device.name, device.type, device.is_active)


if __name__ == "__main__":
    main()
