# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Print the Spotify login URL for the Authorization Code flow.

This is the first step of logging in by hand. Open the printed URL in a browser, log in, and copy the URL Spotify redirects you to. Most programs don't need these steps, because ``SpotifyClient()`` logs in for you.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/authorization_code_url.py

Next, put the redirect URL in ``sayso.local.json`` as ``callback_url`` and run ``authorization_code_exchange.py``.
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, load_config, redirect_uri_from_config, scopes_from_config


def main():
    # Build the login URL from the app credentials and the scopes you want.
    config = load_config()
    client_id, client_secret = credentials_from_config(config)
    auth = AuthorizationCodeAuth(
        client_id,
        client_secret,
        redirect_uri_from_config(config),
        scope=scopes_from_config(config),
    )

    print(auth.authorize_url(state="sayso-example", show_dialog=True))


if __name__ == "__main__":
    main()
