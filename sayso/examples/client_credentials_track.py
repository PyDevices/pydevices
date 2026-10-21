from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


TRACK_ID = "11dFghVXANMlKmJXsNCbNl"


def main():
    client = SpotifyClient()
    track = client.track(TRACK_ID, market="US")

    print("track:", track.name)
    print("album:", track.album.name)
    print("artists:")
    for artist in track.artists:
        print("-", artist.name)


if __name__ == "__main__":
    main()
