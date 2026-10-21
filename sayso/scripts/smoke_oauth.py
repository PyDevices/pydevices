import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sayso import SpotifyClient, load_config, token_cache_from_config


def main():
    config = load_config()
    cache = token_cache_from_config(config)
    needs_login = not cache.load().get("refresh_token")

    print("Spotify OAuth smoke test")
    if needs_login:
        print("No saved login found. Browser authorization is required.")
    else:
        print("Using saved login from {}.".format(cache.path))
    print()

    try:
        client = SpotifyClient()
    except Exception as error:
        raise SystemExit("Smoke test failed: {}".format(error))

    print()
    print("Calling GET /me ...")
    user = client.me()

    print()
    print("Success")
    print("  id:", user.id)
    print("  display_name:", user.display_name)
    print("  product:", user.product)


if __name__ == "__main__":
    main()
