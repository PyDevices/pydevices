from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.recently_played(limit=5)

    for item in page:
        track = item.track
        print("-", item.played_at, track.name)


if __name__ == "__main__":
    main()
