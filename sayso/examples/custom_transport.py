# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List the markets Spotify is available in.

Fetches the available markets with Client Credentials and prints how many there are and the first ten. HTTP is chosen automatically in ``sayso.transport`` from ``requests`` or a CircuitPython ``adafruit_requests`` session, so the same code runs on both.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/custom_transport.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient, credentials_from_config, load_config


def main():
    # Read the app credentials and ask for the list of markets.
    config = load_config()
    client_id, client_secret = credentials_from_config(config)
    client = SpotifyClient(client_id=client_id, client_secret=client_secret)
    markets = client.available_markets()

    print("markets:", len(markets))
    print(", ".join(markets[:10]))


if __name__ == "__main__":
    main()
