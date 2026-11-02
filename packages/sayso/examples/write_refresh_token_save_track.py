# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Save a track to your Spotify library.

Saves one track, then asks Spotify whether it is saved and prints the answer, which should be ``True``. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and write examples turned on: copy ``examples/write_examples.json.example`` to ``examples/write_examples.json`` and set ``allow_write_examples`` to true. This example changes your Spotify account.

Run it from the project root:

    python examples/write_refresh_token_save_track.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient
from config import require_write_examples


# Change these to match your setup.
TRACK_ID = "11dFghVXANMlKmJXsNCbNl"


def main():
    # Stop unless write examples are turned on in write_examples.json.
    require_write_examples()
    client = SpotifyClient()
    client.save_tracks([TRACK_ID])

    # Ask Spotify whether it is saved now.
    saved = client.contains_saved_tracks([TRACK_ID])
    print("saved:", saved[0])


if __name__ == "__main__":
    main()
