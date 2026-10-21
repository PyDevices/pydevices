from _bootstrap import bootstrap

bootstrap()

from sayso import AuthorizationCodeAuth, credentials_from_config, load_config, redirect_uri_from_config, scopes_from_config


def main():
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
