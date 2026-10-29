# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List your top artists.

Prints your five most-played artists. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_top_artists.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.top_artists(limit=5)

    for artist in page:
        print("-", artist.name)


if __name__ == "__main__":
    main()
