# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Log in to Spotify with PKCE through a local web page and print your profile.

``SpotifyClient`` starts a small server on your redirect URI, opens the Spotify login page, catches the redirect itself, and then prints your user ID and display name. Success is your name printing. On first run it opens a browser to log in to Spotify and saves the tokens in ``tokens.json``, which later runs reuse.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/authorization_code_pkce_local_server.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import SpotifyClient


def main():
    # The client runs the whole login, then the first call returns your profile.
    client = SpotifyClient(auth_state="sayso-pkce-local-server")
    user = client.me()

    print("id:", user.id)
    print("display_name:", user.display_name)


if __name__ == "__main__":
    main()
