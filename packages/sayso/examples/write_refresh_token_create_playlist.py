# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Create a private Spotify playlist.

Creates a private playlist for ``user_id`` from ``write_examples.json``, named by ``playlist_name`` or a default, and prints its name and ID. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and write examples turned on: copy ``examples/write_examples.json.example`` to ``examples/write_examples.json`` and set ``allow_write_examples`` to true. This example changes your Spotify account.

Run it from the project root:

    python examples/write_refresh_token_create_playlist.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient
from config import config_value, load_write_examples_config, require_write_examples


def main():
    # Stop unless write examples are turned on in write_examples.json.
    require_write_examples()
    config = load_write_examples_config()
    user_id = config_value(config, "user_id")
    if not user_id:
        raise SystemExit("Set user_id in examples/write_examples.json")

    # Use the playlist name and description from the config, or defaults.
    name = config_value(config, "playlist_name", "sayso example playlist")
    description = config_value(
        config,
        "playlist_description",
        "Created by sayso example code",
    )

    # Create it private.
    client = SpotifyClient()
    playlist = client.create_playlist(user_id, name, public=False, description=description)

    print("playlist:", playlist.name)
    print("id:", playlist.id)


if __name__ == "__main__":
    main()
