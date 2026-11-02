# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Print your Spotify profile.

Prints your user ID, display name and account type. Success is your details printing. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/refresh_token_user_profile.py

Tested on: CPython 3.12.3 on Linux (WSL2).
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    user = client.me()

    print("id:", user.id)
    print("display_name:", user.display_name)
    print("product:", user.product)


if __name__ == "__main__":
    main()
