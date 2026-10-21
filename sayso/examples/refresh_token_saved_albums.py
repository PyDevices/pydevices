from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.saved_albums(limit=5)

    for saved_album in page:
        album = saved_album.album
        print("-", saved_album.added_at, album.name)


if __name__ == "__main__":
    main()
