# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List your playlists.

Prints the name of ten of your playlists and how many items each has. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_playlists.py

Tested on: CPython 3.12.3 on Linux (WSL2).
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.current_user_playlists(limit=10)

    for playlist in page:
        print("-", playlist.name, "items:", playlist.items.total)


if __name__ == "__main__":
    main()
