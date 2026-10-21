from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient, snapshot_id
from config import config_value, load_write_examples_config, require_write_examples


DEFAULT_TRACK_URI = "spotify:track:11dFghVXANMlKmJXsNCbNl"


def main():
    require_write_examples()
    config = load_write_examples_config()
    playlist_id = config_value(config, "playlist_id")
    if not playlist_id:
        raise SystemExit("Set playlist_id in examples/write_examples.json")

    uri = config_value(config, "track_uri", DEFAULT_TRACK_URI)

    client = SpotifyClient()
    result = client.add_playlist_items(playlist_id, [uri])

    print("snapshot_id:", snapshot_id(result))


if __name__ == "__main__":
    main()
