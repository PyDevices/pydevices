# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Trade a Spotify redirect URL for an access token.

This is the second step of logging in by hand. It reads ``callback_url`` from ``sayso.local.json``, exchanges it for tokens, and prints the access token and the refresh token. Most programs don't need these steps, because ``SpotifyClient()`` logs in for you.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and the ``callback_url`` Spotify redirected to after ``authorization_code_url.py``, also in that file. Set ``auth_state`` there too if you passed a state.

Run it from the project root:

    python examples/authorization_code_exchange.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, load_config, redirect_uri_from_config


def main():
    # Read the redirect URL and the state you sent from the config file.
    config = load_config()
    callback_url = config.get("callback_url")
    expected_state = config.get("auth_state")

    if not callback_url:
        raise SystemExit("Set callback_url in sayso.local.json to the full URL Spotify redirected to")

    # Check the state matches, then trade the code in the URL for tokens.
    client_id, client_secret = credentials_from_config(config)
    auth = AuthorizationCodeAuth(
        client_id,
        client_secret,
        redirect_uri_from_config(config),
    )
    access_token = auth.exchange_callback_url(callback_url, expected_state=expected_state)

    print("access_token:", access_token)
    if auth.refresh_token is not None:
        print("refresh_token:", auth.refresh_token)


if __name__ == "__main__":
    main()
