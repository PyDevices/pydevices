from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.top_artists(limit=5)

    for artist in page:
        print("-", artist.name)


if __name__ == "__main__":
    main()
