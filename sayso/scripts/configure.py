import getpass
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sayso import DEFAULT_CONFIG_PATH, save_config


def main():
    print("Create {}".format(DEFAULT_CONFIG_PATH))
    print("Register the redirect URI in your Spotify app dashboard.")
    print()

    client_id = input("Spotify client_id: ").strip()
    client_secret = getpass.getpass("Spotify client_secret: ").strip()
    redirect_uri = input("Redirect URI [http://127.0.0.1:8080]: ").strip() or "http://127.0.0.1:8080"

    if not client_id or not client_secret:
        raise SystemExit("client_id and client_secret are required")

    save_config(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
    )

    print()
    print("Saved {}.".format(DEFAULT_CONFIG_PATH))
    print("Run any user example or python scripts/smoke_oauth.py to authenticate in the browser.")


if __name__ == "__main__":
    main()
