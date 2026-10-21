from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.current_user_playlists(limit=10)

    for playlist in page:
        print("-", playlist.name, "items:", playlist.items.total)


if __name__ == "__main__":
    main()
