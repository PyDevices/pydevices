from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    queue = client.queue()

    if queue.currently_playing is not None:
        print("currently_playing:", queue.currently_playing.name)
    else:
        print("currently_playing: None")

    if not queue.queue:
        print("queue: empty")
        return

    print("queue:")
    for item in queue.queue:
        print("-", item.type, item.name)


if __name__ == "__main__":
    main()
