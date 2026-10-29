# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List the albums you saved most recently.

Prints five saved albums with the date you saved each. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_saved_albums.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.saved_albums(limit=5)

    for saved_album in page:
        album = saved_album.album
        print("-", saved_album.added_at, album.name)


if __name__ == "__main__":
    main()
