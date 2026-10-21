import unittest

from sayso import (
    AlbumPage,
    Artist,
    CurrentlyPlaying,
    HydrationError,
    Page,
    Playlist,
    PlaylistTrackPage,
    Track,
    User,
    set_client,
)
from sayso.transport import TransportError


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def track(self, object_id):
        self.calls.append(("track", object_id))
        return Track(self._responses.get(("track", object_id), {}))


class SpotifyObjectHydrationTest(unittest.TestCase):
    def test_current_playback_preserves_smart_shuffle(self):
        playback = CurrentlyPlaying(
            {
                "shuffle_state": True,
                "smart_shuffle": True,
                "repeat_state": "context",
            }
        )
        self.assertTrue(playback.shuffle_state)
        self.assertTrue(playback.smart_shuffle)
        self.assertEqual(playback.repeat_state, "context")

    def test_missing_field_hydrates_fetchable_object(self):
        client = _FakeClient(
            {
                ("track", "t1"): {
                    "id": "t1",
                    "name": "Full Track",
                    "type": "track",
                    "popularity": 77,
                },
            }
        )
        set_client(client)

        track = Track({"id": "t1", "name": "Stub", "type": "track"})
        self.assertFalse(track._fetched)
        self.assertEqual(track.popularity, 77)
        self.assertTrue(track._fetched)
        self.assertEqual(client.calls, [("track", "t1")])

    def test_present_field_does_not_hydrate(self):
        client = _FakeClient({})
        set_client(client)

        track = Track({"id": "t1", "name": "Stub", "type": "track"})
        self.assertEqual(track.name, "Stub")
        self.assertFalse(track._fetched)
        self.assertEqual(client.calls, [])

    def test_non_fetchable_object_does_not_mark_fetched(self):
        set_client(_FakeClient({}))

        user = User({"id": "u1", "display_name": "Stub", "type": "user"})
        self.assertIsNone(user.followers)
        self.assertFalse(user._fetched)

    def test_repr_does_not_hydrate(self):
        client = _FakeClient({("track", "t1"): {"id": "t1", "name": "Full", "type": "track"}})
        set_client(client)

        track = Track({"id": "t1", "type": "track"})
        repr(track)
        self.assertFalse(track._fetched)
        self.assertEqual(client.calls, [])

    def test_artist_albums_uses_page_method(self):
        class _ArtistClient(_FakeClient):
            def artist(self, object_id):
                self.calls.append(("artist", object_id))
                return Artist({"id": object_id, "name": "Artist", "type": "artist"})

            def artist_albums(self, object_id):
                self.calls.append(("artist_albums", object_id))
                return AlbumPage(
                    {
                        "href": "albums",
                        "limit": 1,
                        "next": None,
                        "offset": 0,
                        "previous": None,
                        "total": 1,
                        "items": [{"id": "a1", "name": "Album", "type": "album"}],
                    }
                )

        client = _ArtistClient({})
        set_client(client)

        artist = Artist({"id": "ar1", "name": "Artist", "type": "artist"})
        self.assertEqual(artist.albums[0].name, "Album")
        self.assertEqual(client.calls[0], ("artist", "ar1"))
        self.assertEqual(client.calls[-1], ("artist_albums", "ar1"))

    def test_playlist_items_ref_uses_page_method(self):
        class _PlaylistClient(_FakeClient):
            def playlist(self, object_id):
                self.calls.append(("playlist", object_id))
                return Playlist(
                    {
                        "id": object_id,
                        "name": "Mine",
                        "items": {"href": "x", "total": 1},
                    }
                )

            def playlist_items(self, object_id):
                self.calls.append(("playlist_items", object_id))
                return PlaylistTrackPage(
                    {
                        "href": "items",
                        "limit": 1,
                        "next": None,
                        "offset": 0,
                        "previous": None,
                        "total": 1,
                        "items": [
                            {
                                "added_at": "2026-01-01T00:00:00Z",
                                "item": {"id": "t1", "name": "Song", "type": "track"},
                            }
                        ],
                    }
                )

        client = _PlaylistClient({})
        set_client(client)

        playlist = Playlist({"id": "pl1", "name": "Mine", "items": {"href": "x", "total": 1}})
        items = playlist.items
        self.assertEqual(items.total, 1)
        self.assertEqual(client.calls, [])

        item = items[0]
        self.assertEqual(item.item.name, "Song")
        self.assertEqual(client.calls, [("playlist_items", "pl1")])

    def test_hydration_error_includes_context(self):
        class _FailingClient(_FakeClient):
            def track(self, object_id):
                self.calls.append(("track", object_id))
                raise TransportError("HTTP status 403", 403, None)

        client = _FailingClient({})
        set_client(client)

        track = Track({"id": "t1", "name": "Stub", "type": "track"})
        with self.assertRaises(HydrationError) as context:
            track.popularity

        self.assertIn("Track", str(context.exception))
        self.assertIn("track()", str(context.exception))
        self.assertIn("403", str(context.exception))
        self.assertIsInstance(context.exception.cause, TransportError)

    def test_page_items_uses_peek(self):
        page = Page(
            {
                "href": "h",
                "limit": 1,
                "next": None,
                "offset": 0,
                "previous": None,
                "total": 1,
                "items": [{"id": "t1", "name": "Song", "type": "track"}],
            }
        )
        page._item_class = "Track"
        self.assertEqual(page[0].name, "Song")
        self.assertFalse(page._fetched)


if __name__ == "__main__":
    unittest.main()
