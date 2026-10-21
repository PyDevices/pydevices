import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sayso import SpotifyClient, credentials_from_config, load_config


def main():
    try:
        config = load_config()
        client_id, client_secret = credentials_from_config(config)
        client = SpotifyClient(client_id=client_id, client_secret=client_secret)
    except Exception as error:
        raise SystemExit(str(error))

    track = client.track("11dFghVXANMlKmJXsNCbNl", market="US")

    print("track:", track.name)
    print("album:", track.album.name)
    print("artist:", track.artists[0].name)


if __name__ == "__main__":
    main()
