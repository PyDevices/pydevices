# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show what you are playing on Spotify.

Prints whether something is playing, how far into it you are, which device is playing, and the track or episode with its artists, album and context. It prints ``No active playback.`` when nothing is playing. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_currently_playing.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    current = client.current_playback()

    # An empty answer means nothing is playing.
    if not current.raw():
        print("No active playback.")
        return

    print("is_playing:", current.is_playing)
    print("currently_playing_type:", current.currently_playing_type)
    print("progress_ms:", current.progress_ms)

    # Show the device, then the track or episode and its context.
    if current.device is not None:
        print("device:", current.device.name, "({})".format(current.device.type))

    if current.item is not None:
        print("item:", current.item.name)
        print("item_type:", current.item.type)

        artists = getattr(current.item, "artists", ())
        if artists:
            print("artists:", ", ".join(artist.name for artist in artists))

        album = getattr(current.item, "album", None)
        if album is not None:
            print("album:", album.name)

    if current.context is not None:
        print("context:", current.context.type, current.context.uri)


if __name__ == "__main__":
    main()
