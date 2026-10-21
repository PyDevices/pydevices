from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


ALBUM_ID = "4aawyAB9vmqN3uQ7FjRGTy"


def main():
    client = SpotifyClient()
    page = client.album_tracks(ALBUM_ID, market="US", limit=2)

    print("first page:")
    print_tracks(page)

    next_page = client.next_page(page)
    if next_page is not None:
        print("next page:")
        print_tracks(next_page)


def print_tracks(page):
    for track in page:
        print("-", track.track_number, track.name)


if __name__ == "__main__":
    main()
