from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()

    for device in client.devices():
        print("-", device.name, device.type, device.is_active)


if __name__ == "__main__":
    main()
