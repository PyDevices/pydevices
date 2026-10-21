from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    page = client.saved_tracks(market="US", limit=5)

    print_tracks(page)

    next_page = client.next_page(page)
    if next_page is not None:
        print("next page:")
        print_tracks(next_page)


def print_tracks(page):
    for saved_track in page:
        track = saved_track.track
        print("-", saved_track.added_at, track.name)


if __name__ == "__main__":
    main()
