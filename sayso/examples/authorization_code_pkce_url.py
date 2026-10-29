# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Print the Spotify login URL for the PKCE flow.

This is the first step of logging in by hand with PKCE. It makes a code verifier and prints it with the login URL. Open the URL in a browser, log in, and copy the URL Spotify redirects you to. Most programs don't need these steps, because ``SpotifyClient()`` logs in for you.

Needs: CPython and a ``sayso.local.json`` in the project root with your Spotify app's client ID, client secret and redirect URI.

Run it from the project root:

    python examples/authorization_code_pkce_url.py

Next, put the redirect URL and the code verifier in ``sayso.local.json`` and run ``authorization_code_pkce_exchange.py``.

Tested on: CPython 3.12.3 on Linux (WSL2).
"""

from _bootstrap import bootstrap

# Make the sayso library importable from this checkout.
bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, generate_code_verifier, load_config, redirect_uri_from_config, scopes_from_config


def main():
    # Make a one-time verifier, and build the login URL that commits to it.
    config = load_config()
    client_id, client_secret = credentials_from_config(config)
    code_verifier = generate_code_verifier()
    auth = AuthorizationCodeAuth(
        client_id,
        client_secret,
        redirect_uri_from_config(config),
        scope=scopes_from_config(config),
        code_verifier=code_verifier,
    )

    print("code_verifier:", code_verifier)
    print(auth.authorize_url(state="sayso-pkce-example", show_dialog=True))


if __name__ == "__main__":
    main()
