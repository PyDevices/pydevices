# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Upload a cover image for a Spotify playlist.

Reads the JPEG named by ``playlist_cover_jpeg`` in ``write_examples.json``, uploads it as the cover of the playlist in ``playlist_id``, and prints the path. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and write examples turned on: copy ``examples/write_examples.json.example`` to ``examples/write_examples.json`` and set ``allow_write_examples`` to true. This example changes your Spotify account.

Run it from the project root:

    python examples/write_refresh_token_set_playlist_cover.py
"""

import base64

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient
from config import config_value, load_write_examples_config, require_write_examples


def main():
    # Stop unless write examples are turned on in write_examples.json.
    require_write_examples()
    config = load_write_examples_config()
    playlist_id = config_value(config, "playlist_id")
    image_path = config_value(config, "playlist_cover_jpeg")

    if not playlist_id:
        raise SystemExit("Set playlist_id in examples/write_examples.json")
    if not image_path:
        raise SystemExit("Set playlist_cover_jpeg in examples/write_examples.json")

    # The API takes the JPEG as base64 text.
    with open(image_path, "rb") as file:
        base64_jpeg = base64.b64encode(file.read()).decode("ascii")

    client = SpotifyClient()
    client.set_playlist_cover_image(playlist_id, base64_jpeg)

    print("uploaded:", image_path)


if __name__ == "__main__":
    main()
