from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient


def main():
    client = SpotifyClient()
    user = client.me()

    print("id:", user.id)
    print("display_name:", user.display_name)
    print("product:", user.product)


if __name__ == "__main__":
    main()
