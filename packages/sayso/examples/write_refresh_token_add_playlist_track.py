# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Add a track to a Spotify playlist.

Adds the track in ``track_uri`` from ``write_examples.json``, or a default one, to the playlist in ``playlist_id`` and prints the new snapshot ID. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and write examples turned on: copy ``examples/write_examples.json.example`` to ``examples/write_examples.json`` and set ``allow_write_examples`` to true. This example changes your Spotify account.

Run it from the project root:

    python examples/write_refresh_token_add_playlist_track.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient, snapshot_id
from config import config_value, load_write_examples_config, require_write_examples


# Change these to match your setup.
DEFAULT_TRACK_URI = "spotify:track:11dFghVXANMlKmJXsNCbNl"


def main():
    # Stop unless write examples are turned on in write_examples.json.
    require_write_examples()
    config = load_write_examples_config()
    playlist_id = config_value(config, "playlist_id")
    if not playlist_id:
        raise SystemExit("Set playlist_id in examples/write_examples.json")

    uri = config_value(config, "track_uri", DEFAULT_TRACK_URI)

    client = SpotifyClient()
    result = client.add_playlist_items(playlist_id, [uri])

    print("snapshot_id:", snapshot_id(result))


if __name__ == "__main__":
    main()
