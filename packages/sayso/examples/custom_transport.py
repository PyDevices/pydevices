# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Search Spotify for artists with the app's own credentials.

Searches for artists by name with Client Credentials and prints the first five matches. The client gets your app's client ID and secret directly instead of reading them itself. HTTP is chosen automatically in ``sayso.transport`` from ``requests`` or a CircuitPython ``adafruit_requests`` session, so the same code runs on both.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/custom_transport.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient, credentials_from_config, load_config


# Change this to match your setup.
SEARCH_TEXT = "Radiohead"


def main():
    # Read the app credentials and search for artists.
    config = load_config()
    client_id, client_secret = credentials_from_config(config)
    client = SpotifyClient(client_id=client_id, client_secret=client_secret)
    results = client.search(SEARCH_TEXT, ["artist"], limit=5)

    print("artists matching", SEARCH_TEXT + ":")
    for artist in results.artists.items:
        print("-", artist.name)


if __name__ == "__main__":
    main()
