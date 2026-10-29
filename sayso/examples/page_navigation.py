# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Read one page of an album's tracks, then the next.

Fetches two tracks of an album with ``limit=2``, prints them, then follows ``next_page()`` to print the following two. Use the same pattern for any paged result. It needs no user login. Success is two groups of tracks printing.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/page_navigation.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


# Change these to match your setup.
ALBUM_ID = "4aawyAB9vmqN3uQ7FjRGTy"


def main():
    client = SpotifyClient()
    # Ask for two tracks at a time, so there is a second page to follow.
    page = client.album_tracks(ALBUM_ID, market="US", limit=2)

    print("first page:")
    print_tracks(page)

    # next_page() returns None when there are no more pages.
    next_page = client.next_page(page)
    if next_page is not None:
        print("next page:")
        print_tracks(next_page)


def print_tracks(page):
    for track in page:
        print("-", track.track_number, track.name)


if __name__ == "__main__":
    main()
