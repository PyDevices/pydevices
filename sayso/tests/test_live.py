import unittest

from sayso import config_available


def _owned_playlist(client, me):
    for playlist in client.current_user_playlists():
        if playlist.owner and playlist.owner.id == me.id:
            return playlist
    return None


@unittest.skipUnless(
    config_available(),
    "Copy sayso.local.json.example to sayso.local.json and add credentials",
)
class SpotifyLiveTest(unittest.TestCase):
    def test_spotify_client_me(self):
        from sayso import SpotifyClient

        client = SpotifyClient()
        user = client.me()

        self.assertIsNotNone(user.id)
        self.assertIsNotNone(user.display_name)

    def test_spotify_client_track_with_client_credentials(self):
        from sayso import SpotifyClient, credentials_from_config, load_config

        config = load_config()
        client_id, client_secret = credentials_from_config(config)
        client = SpotifyClient(client_id=client_id, client_secret=client_secret)
        track = client.track("11dFghVXANMlKmJXsNCbNl", market="US")

        self.assertEqual(track.id, "11dFghVXANMlKmJXsNCbNl")
        self.assertIsNotNone(track.name)
        self.assertIsNotNone(track.album.name)
        self.assertIsNotNone(track.artists[0].name)

    def test_owned_playlist_items(self):
        from sayso import SpotifyClient

        client = SpotifyClient()
        me = client.me()
        playlist = _owned_playlist(client, me)

        self.assertIsNotNone(playlist)
        self.assertGreater(len(playlist.items), 0)
        self.assertIsNotNone(playlist.items[0].item.name)

    def test_artist_albums_from_track(self):
        from sayso import SpotifyClient

        client = SpotifyClient()
        saved_tracks = client.saved_tracks(limit=1)

        self.assertGreater(len(saved_tracks), 0)

        artist = saved_tracks[0].track.artists[0]
        self.assertGreater(len(artist.albums), 0)
        self.assertIsNotNone(artist.albums[0].name)

        albums_page = client.artist_albums(artist.id, limit=10)
        self.assertGreater(len(albums_page), 0)
        self.assertIsNotNone(albums_page[0].name)

    def test_saved_tracks_page(self):
        from sayso import SpotifyClient

        client = SpotifyClient()
        page = client.saved_tracks(limit=2)

        self.assertGreater(len(page), 0)
        self.assertIsNotNone(page[0].track.name)

        if page.next is not None:
            next_page = client.next_page(page)
            self.assertIsNotNone(next_page)
            self.assertGreater(len(next_page), 0)
            self.assertIsNotNone(next_page[0].track.name)

    def test_recently_played_cursor(self):
        from sayso import SpotifyClient

        client = SpotifyClient()
        page = client.recently_played(limit=1)

        if len(page) == 0:
            self.skipTest("No recently played history")

        self.assertIsNotNone(page[0].track.name)
        if page.cursors is not None:
            self.assertIsNotNone(page.cursors.after)


if __name__ == "__main__":
    unittest.main()
