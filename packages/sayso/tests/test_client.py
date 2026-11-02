import unittest

from sayso import SpotifyClient
from sayso.local import EarfulAdapter
from sayso.auth import ClientCredentialsAuth
from sayso.transport import TransportError


class _CountingAuth(ClientCredentialsAuth):
    def __init__(self):
        super().__init__("client-id", "client-secret")
        self.access_token = "token-1"
        self.expires_at = 9999999999
        self.refresh_count = 0

    def refresh(self):
        self.refresh_count += 1
        self.access_token = "token-{}".format(self.refresh_count + 1)
        self.expires_at = 9999999999
        return self.access_token


class SpotifyClientRetryTest(unittest.TestCase):
    def test_retries_once_after_401_when_auth_is_available(self):
        import sayso.client as client_module

        auth = _CountingAuth()
        client = SpotifyClient(auth=auth, auto_set=False)
        calls = []

        def fake_get_json(path, access_token=None, query=None):
            calls.append(access_token)
            if access_token == "token-1":
                raise TransportError("HTTP status 401", 401, None)
            return {"id": "me", "display_name": "User", "type": "user"}

        original = client_module.get_json
        client_module.get_json = fake_get_json
        try:
            user = client.me()
        finally:
            client_module.get_json = original

        self.assertEqual(user.display_name, "User")
        self.assertEqual(calls, ["token-1", "token-2"])
        self.assertEqual(auth.refresh_count, 1)

    def test_does_not_retry_401_without_auth(self):
        import sayso.client as client_module

        client = SpotifyClient(access_token="static-token", auto_set=False)

        def fake_get_json(path, access_token=None, query=None):
            raise TransportError("HTTP status 401", 401, None)

        original = client_module.get_json
        client_module.get_json = fake_get_json
        try:
            with self.assertRaises(TransportError) as context:
                client.me()
        finally:
            client_module.get_json = original

        self.assertEqual(context.exception.status, 401)


class _EarfulDevice:
    name = "earful"
    device_id = "earful-id"
    active = True
    playing = True
    volume = 42
    track = "spotify:track:fixture"

    def __init__(self):
        self.calls = []

    def pause(self): self.calls.append(("pause",))
    def next(self): self.calls.append(("next",))
    def prev(self): self.calls.append(("prev",))
    def seek(self, value): self.calls.append(("seek", value))
    def play(self, value=None): self.calls.append(("play", value))


class LocalEarfulBridgeTest(unittest.TestCase):
    def test_controls_use_explicit_local_device(self):
        device = _EarfulDevice()
        client = SpotifyClient(access_token="unused", auto_set=False, local_device=device)
        client.pause(device_id="earful-id")
        client.next_track(device_id="earful")
        client.seek(1234, device_id="earful-id")
        self.assertEqual(device.calls, [("pause",), ("next",), ("seek", 1234)])

    def test_other_device_keeps_web_api_path(self):
        device = _EarfulDevice()
        client = SpotifyClient(access_token="unused", auto_set=False, local_device=device)
        original = client._put_json
        calls = []
        client._put_json = lambda *args, **kwargs: calls.append((args, kwargs))
        client.pause(device_id="other")
        self.assertEqual(len(calls), 1)
        self.assertEqual(device.calls, [])

    def test_local_play_maps_context_and_position(self):
        class Device:
            def __init__(self):
                self.calls = []

            def play(self, **kwargs):
                self.calls.append(kwargs)

        device = Device()
        adapter = EarfulAdapter(device)
        adapter.play(context_uri="spotify:playlist:agents", position_ms=60000)
        adapter.play(uris=["spotify:track:fixture"], position_ms=1234)
        self.assertEqual(device.calls, [
            {"context": "spotify:playlist:agents", "position": 60000},
            {"uri": "spotify:track:fixture", "position": 1234},
        ])

    def test_local_state_and_volume_surface(self):
        class Device:
            name = "earful"
            device_id = "earful-id"
            active = True
            playing = False
            volume = 0
            track = "spotify:track:fixture"
            position = 15000
            duration = 180000
            playlist = "spotify:playlist:agents"

            def __init__(self):
                self.volume_calls = []

        device = Device()
        adapter = EarfulAdapter(device)
        adapter.set_volume(100)
        self.assertEqual(device.volume, 100)
        state = adapter.state()
        self.assertEqual(state["device_id"], "earful-id")
        self.assertEqual(state["position_ms"], 15000)
        self.assertEqual(state["context"], "spotify:playlist:agents")


if __name__ == "__main__":
    unittest.main()
