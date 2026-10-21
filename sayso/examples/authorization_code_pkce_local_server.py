from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient(auth_state="sayso-pkce-local-server")
    user = client.me()

    print("id:", user.id)
    print("display_name:", user.display_name)


if __name__ == "__main__":
    main()
