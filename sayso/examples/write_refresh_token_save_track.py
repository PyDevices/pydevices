from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient
from config import require_write_examples


TRACK_ID = "11dFghVXANMlKmJXsNCbNl"


def main():
    require_write_examples()
    client = SpotifyClient()
    client.save_tracks([TRACK_ID])

    saved = client.contains_saved_tracks([TRACK_ID])
    print("saved:", saved[0])


if __name__ == "__main__":
    main()
