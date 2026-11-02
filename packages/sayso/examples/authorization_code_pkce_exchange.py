# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Trade a Spotify redirect URL for an access token with PKCE.

This is the second step of logging in by hand with PKCE. It reads ``callback_url`` and ``code_verifier`` from ``sayso.local.json``, exchanges them for tokens, and prints the access token and the refresh token. Most programs don't need these steps, because ``SpotifyClient()`` logs in for you.

Needs: CPython, a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI, and the ``callback_url`` and ``code_verifier`` from ``authorization_code_pkce_url.py``, also in that file.

Run it from the project root:

    python examples/authorization_code_pkce_exchange.py
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, load_config, redirect_uri_from_config


def main():
    # Read the redirect URL, the verifier and the state from the config file.
    config = load_config()
    callback_url = config.get("callback_url")
    code_verifier = config.get("code_verifier")
    expected_state = config.get("auth_state")

    if not callback_url:
        raise SystemExit("Set callback_url in sayso.local.json to the full URL Spotify redirected to")
    if not code_verifier:
        raise SystemExit("Set code_verifier in sayso.local.json from authorization_code_pkce_url.py")

    # Trade the code in the URL for tokens, proving it with the verifier.
    client_id, client_secret = credentials_from_config(config)
    auth = AuthorizationCodeAuth(
        client_id,
        client_secret,
        redirect_uri_from_config(config),
        code_verifier=code_verifier,
    )
    access_token = auth.exchange_callback_url(callback_url, expected_state=expected_state)

    print("access_token:", access_token)
    if auth.refresh_token is not None:
        print("refresh_token:", auth.refresh_token)


if __name__ == "__main__":
    main()
