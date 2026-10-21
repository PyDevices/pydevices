from _bootstrap import bootstrap

bootstrap()

from sayso import SpotifyClient, credentials_from_config, load_config


def main():
    config = load_config()
    client_id, client_secret = credentials_from_config(config)
    client = SpotifyClient(client_id=client_id, client_secret=client_secret)
    markets = client.available_markets()

    print("markets:", len(markets))
    print(", ".join(markets[:10]))


if __name__ == "__main__":
    main()
