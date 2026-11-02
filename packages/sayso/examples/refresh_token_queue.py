# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Show your Spotify queue.

Prints what is playing and what is queued next. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_queue.py

Tested on: CPython 3.12.3 on Linux (WSL2).
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    queue = client.queue()

    if queue.currently_playing is not None:
        print("currently_playing:", queue.currently_playing.name)
    else:
        print("currently_playing: None")

    # Then everything waiting behind it.
    if not queue.queue:
        print("queue: empty")
        return

    print("queue:")
    for item in queue.queue:
        print("-", item.type, item.name)


if __name__ == "__main__":
    main()
