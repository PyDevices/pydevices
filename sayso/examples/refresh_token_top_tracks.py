from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.top_tracks(limit=5)

    for track in page:
        print("-", track.name)


if __name__ == "__main__":
    main()
