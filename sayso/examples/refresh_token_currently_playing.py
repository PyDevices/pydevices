from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    current = client.current_playback()

    if not current.raw():
        print("No active playback.")
        return

    print("is_playing:", current.is_playing)
    print("currently_playing_type:", current.currently_playing_type)
    print("progress_ms:", current.progress_ms)

    if current.device is not None:
        print("device:", current.device.name, "({})".format(current.device.type))

    if current.item is not None:
        print("item:", current.item.name)
        print("item_type:", current.item.type)

        artists = getattr(current.item, "artists", ())
        if artists:
            print("artists:", ", ".join(artist.name for artist in artists))

        album = getattr(current.item, "album", None)
        if album is not None:
            print("album:", album.name)

    if current.context is not None:
        print("context:", current.context.type, current.context.uri)


if __name__ == "__main__":
    main()
