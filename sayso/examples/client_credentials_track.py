# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Look up a public track without logging in.

Asks Spotify for one track by ID and prints its name, album and artists. It uses the Client Credentials flow, which needs only your app's credentials and no user login. Success is the track's details printing.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/client_credentials_track.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


# Change these to match your setup.
TRACK_ID = "11dFghVXANMlKmJXsNCbNl"


def main():
    # With no login stored, the client uses the Client Credentials flow.
    client = SpotifyClient()
    track = client.track(TRACK_ID, market="US")

    print("track:", track.name)
    print("album:", track.album.name)
    print("artists:")
    for artist in track.artists:
        print("-", artist.name)


if __name__ == "__main__":
    main()
