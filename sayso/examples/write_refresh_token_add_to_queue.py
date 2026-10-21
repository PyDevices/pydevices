from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient
from config import config_value, load_write_examples_config, require_write_examples


DEFAULT_TRACK_URI = "spotify:track:11dFghVXANMlKmJXsNCbNl"


def main():
    require_write_examples()
    config = load_write_examples_config()
    uri = config_value(config, "track_uri", DEFAULT_TRACK_URI)

    client = SpotifyClient()
    client.add_to_queue(uri)

    print("queued:", uri)


if __name__ == "__main__":
    main()
