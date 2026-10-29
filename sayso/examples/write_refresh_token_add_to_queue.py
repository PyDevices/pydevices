# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Add a track to your Spotify queue.

Queues the track in ``track_uri`` from ``write_examples.json``, or a default one, and prints its URI. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and write examples turned on: copy ``examples/write_examples.json.example`` to ``examples/write_examples.json`` and set ``allow_write_examples`` to true. This example changes your Spotify account.

Run it from the project root:

    python examples/write_refresh_token_add_to_queue.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient
from config import config_value, load_write_examples_config, require_write_examples


# Change these to match your setup.
DEFAULT_TRACK_URI = "spotify:track:11dFghVXANMlKmJXsNCbNl"


def main():
    # Stop unless write examples are turned on in write_examples.json.
    require_write_examples()
    config = load_write_examples_config()
    uri = config_value(config, "track_uri", DEFAULT_TRACK_URI)

    client = SpotifyClient()
    client.add_to_queue(uri)

    print("queued:", uri)


if __name__ == "__main__":
    main()
