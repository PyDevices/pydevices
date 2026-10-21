from _bootstrap import bootstrap

bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, load_config, redirect_uri_from_config


def main():
    config = load_config()
    callback_url = config.get("callback_url")
    code_verifier = config.get("code_verifier")
    expected_state = config.get("auth_state")

    if not callback_url:
        raise SystemExit("Set callback_url in sayso.local.json to the full URL Spotify redirected to")
    if not code_verifier:
        raise SystemExit("Set code_verifier in sayso.local.json from authorization_code_pkce_url.py")

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
