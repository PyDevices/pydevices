# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""List the tracks you saved most recently.

Prints five saved tracks with the date you saved each, then the next five, to show paging. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_saved_tracks.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.saved_tracks(market="US", limit=5)

    print_tracks(page)

    # next_page() returns None when there are no more pages.
    next_page = client.next_page(page)
    if next_page is not None:
        print("next page:")
        print_tracks(next_page)


def print_tracks(page):
    for saved_track in page:
        track = saved_track.track
        print("-", saved_track.added_at, track.name)


if __name__ == "__main__":
    main()
