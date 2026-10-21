import base64

from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient
from config import config_value, load_write_examples_config, require_write_examples


def main():
    require_write_examples()
    config = load_write_examples_config()
    playlist_id = config_value(config, "playlist_id")
    image_path = config_value(config, "playlist_cover_jpeg")

    if not playlist_id:
        raise SystemExit("Set playlist_id in examples/write_examples.json")
    if not image_path:
        raise SystemExit("Set playlist_cover_jpeg in examples/write_examples.json")

    with open(image_path, "rb") as file:
        base64_jpeg = base64.b64encode(file.read()).decode("ascii")

    client = SpotifyClient()
    client.set_playlist_cover_image(playlist_id, base64_jpeg)

    print("uploaded:", image_path)


if __name__ == "__main__":
    main()
