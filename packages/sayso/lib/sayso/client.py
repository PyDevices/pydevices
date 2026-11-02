from .auth import ClientCredentialsAuth
from .objects import (
    Album,
    AlbumPage,
    Artist,
    ArtistCursorPage,
    ArtistPage,
    AudioAnalysis,
    AudioFeatures,
    Audiobook,
    AudiobookPage,
    Category,
    CategoryPage,
    Chapter,
    ChapterPage,
    CurrentlyPlaying,
    Device,
    Episode,
    EpisodePage,
    FeaturedPlaylists,
    Image,
    Playlist,
    PlaylistPage,
    PlaylistTrackPage,
    PlayHistoryCursorPage,
    PrivateUser,
    Queue,
    Recommendations,
    SavedAlbumPage,
    SavedEpisodePage,
    SavedShowPage,
    SavedTrackPage,
    SearchResults,
    Show,
    SnapshotResult,
    TrackPage,
    Track,
    User,
    set_client,
)
from .transport import (
    API_BASE_URL,
    TransportError,
    build_url,
    delete_json,
    get_json,
    post_json,
    put_body,
    put_json,
)
from .local import EarfulAdapter, discover as discover_local


class SpotifyClientError(Exception):
    pass


class SpotifyClient:
    API_BASE_URL = API_BASE_URL

    def __init__(
        self,
        access_token=None,
        client_id=None,
        client_secret=None,
        auth=None,
        auto_set=True,
        config_path=None,
        scope=None,
        authenticate_if_needed=True,
        auth_state="sayso",
        local_device=None,
    ):
        self.access_token = access_token
        self.auth = auth
        self.local = local_device if isinstance(local_device, EarfulAdapter) else (
            EarfulAdapter(local_device) if local_device is not None else discover_local()
        )

        if self.auth is None and access_token is None:
            if client_id is not None and client_secret is not None:
                self.auth = ClientCredentialsAuth(client_id, client_secret)
            else:
                from .auth import auth_from_config

                self.auth = auth_from_config(
                    config_path=config_path,
                    scope=scope,
                    authenticate_if_needed=authenticate_if_needed,
                    auth_state=auth_state,
                )

        if auto_set:
            set_client(self)

    def _get_json(self, path, query=None):
        def request(token):
            return get_json(path, access_token=token, query=query)

        return self._request_with_retry(request)

    def _put_json(self, path, data=None, query=None):
        return self._request_json(put_json, path, data=data, query=query)

    def _put_body(self, path, body, content_type, query=None):
        def request(token):
            return put_body(path, body, content_type, access_token=token, query=query)

        return self._request_with_retry(request)

    def _post_json(self, path, data=None, query=None):
        return self._request_json(post_json, path, data=data, query=query)

    def _delete_json(self, path, data=None, query=None):
        return self._request_json(delete_json, path, data=data, query=query)

    def _url(self, path, query=None):
        return build_url(path, query=query, base_url=self.API_BASE_URL)

    def _request_json(self, request, path, data=None, query=None):
        def do_request(token):
            return request(path, data=data, access_token=token, query=query)

        return self._request_with_retry(do_request)

    def _request_with_retry(self, request):
        token = self._access_token()
        if token is None:
            raise SpotifyClientError("An access_token is required for Spotify Web API requests")

        try:
            return request(token)
        except TransportError as error:
            if error.status != 401 or self.auth is None:
                raise

            self.auth.refresh()
            if self.access_token is not None and self.auth.access_token is not None:
                self.access_token = self.auth.access_token

            token = self._access_token()
            if token is None:
                raise SpotifyClientError("An access_token is required for Spotify Web API requests")

            return request(token)

    def _access_token(self):
        if self.access_token is not None:
            return self.access_token
        if self.auth is not None:
            return self.auth.token()
        return None

    def _local(self, device_id=None):
        if self.local is None:
            return None
        if device_id is None or device_id == self.local.device_id or device_id == self.local.name:
            return self.local
        return None

    def _one(self, cls, path, query=None):
        return cls(self._get_json(path, query=query))

    def _many(self, cls, field, path, ids, query=None):
        query = self._query_with_ids(ids, query=query)
        data = self._get_json(path, query=query)
        values = data.get(field, ())
        return [cls(item) for item in values]

    def _page(self, cls, path, query=None):
        return cls(self._get_json(path, query=query))

    def _page_url(self, page_url, page_class):
        if page_url is None:
            return None
        return page_class(self._get_json(page_url))

    def next_page(self, page):
        return self._page_url(page.next, page.__class__)

    def previous_page(self, page):
        return self._page_url(page.previous, page.__class__)

    def _path_id(self, value):
        return str(value)

    def track(self, object_id, market=None):
        return self._one(Track, "/tracks/" + self._path_id(object_id), self._market_query(market))

    def tracks(self, ids, market=None):
        return self._many(Track, "tracks", "/tracks", ids, self._market_query(market))

    def album(self, object_id, market=None):
        return self._one(Album, "/albums/" + self._path_id(object_id), self._market_query(market))

    def albums(self, ids, market=None):
        return self._many(Album, "albums", "/albums", ids, self._market_query(market))

    def album_tracks(self, object_id, market=None, limit=None, offset=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        return self._page(TrackPage, "/albums/" + self._path_id(object_id) + "/tracks", query)

    def artist(self, object_id):
        return self._one(Artist, "/artists/" + self._path_id(object_id))

    def artists(self, ids):
        return self._many(Artist, "artists", "/artists", ids)

    def artist_albums(self, object_id, include_groups=None, market=None, limit=None, offset=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        self._add_query(query, "include_groups", include_groups)
        return self._page(AlbumPage, "/artists/" + self._path_id(object_id) + "/albums", query)

    def artist_top_tracks(self, object_id, market=None):
        data = self._get_json("/artists/" + self._path_id(object_id) + "/top-tracks", self._market_query(market))
        tracks = data.get("tracks")
        if tracks is None:
            return ()
        return [Track(item) for item in tracks]

    def artist_related_artists(self, object_id):
        data = self._get_json("/artists/" + self._path_id(object_id) + "/related-artists")
        artists = data.get("artists")
        if artists is None:
            return ()
        return [Artist(item) for item in artists]

    def playlist(self, object_id, market=None, fields=None, additional_types=None):
        query = {}
        self._add_query(query, "market", market)
        self._add_query(query, "fields", fields)
        self._add_query(query, "additional_types", additional_types)
        return self._one(Playlist, "/playlists/" + self._path_id(object_id), query)

    def create_playlist(self, user_id, name, public=None, collaborative=None, description=None):
        data = {"name": name}
        self._add_query(data, "public", public)
        self._add_query(data, "collaborative", collaborative)
        self._add_query(data, "description", description)
        return Playlist(self._post_json("/users/" + self._path_id(user_id) + "/playlists", data=data))

    def create_current_user_playlist(self, name, public=None, collaborative=None, description=None):
        data = {"name": name}
        self._add_query(data, "public", public)
        self._add_query(data, "collaborative", collaborative)
        self._add_query(data, "description", description)
        return Playlist(self._post_json("/me/playlists", data=data))

    def update_playlist_details(self, object_id, name=None, public=None, collaborative=None, description=None):
        data = {}
        self._add_query(data, "name", name)
        self._add_query(data, "public", public)
        self._add_query(data, "collaborative", collaborative)
        self._add_query(data, "description", description)
        return self._put_json("/playlists/" + self._path_id(object_id), data=data)

    def playlist_items(self, object_id, market=None, fields=None, limit=None, offset=None, additional_types=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        self._add_query(query, "fields", fields)
        self._add_query(query, "additional_types", additional_types)
        return self._page(PlaylistTrackPage, "/playlists/" + self._path_id(object_id) + "/items", query)

    def playlist_tracks(self, object_id, market=None, fields=None, limit=None, offset=None, additional_types=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        self._add_query(query, "fields", fields)
        self._add_query(query, "additional_types", additional_types)
        return self._page(PlaylistTrackPage, "/playlists/" + self._path_id(object_id) + "/tracks", query)

    def add_playlist_items(self, object_id, uris, position=None):
        data = {"uris": self._uri_list(uris)}
        self._add_query(data, "position", position)
        return self._snapshot(self._post_json("/playlists/" + self._path_id(object_id) + "/items", data=data))

    def add_playlist_tracks(self, object_id, uris, position=None):
        data = {"uris": self._uri_list(uris)}
        self._add_query(data, "position", position)
        return self._snapshot(self._post_json("/playlists/" + self._path_id(object_id) + "/tracks", data=data))

    def remove_playlist_items(self, object_id, uris, snapshot_id=None):
        data = {
            "items": [{"uri": uri} for uri in self._uri_list(uris)],
        }
        self._add_query(data, "snapshot_id", snapshot_id)
        return self._snapshot(self._delete_json("/playlists/" + self._path_id(object_id) + "/items", data=data))

    def remove_playlist_tracks(self, object_id, uris, snapshot_id=None):
        data = {
            "tracks": [{"uri": uri} for uri in self._uri_list(uris)],
        }
        self._add_query(data, "snapshot_id", snapshot_id)
        return self._snapshot(self._delete_json("/playlists/" + self._path_id(object_id) + "/tracks", data=data))

    def replace_playlist_items(self, object_id, uris):
        return self._snapshot(
            self._put_json(
                "/playlists/" + self._path_id(object_id) + "/items",
                data={"uris": self._uri_list(uris)},
            )
        )

    def replace_playlist_tracks(self, object_id, uris):
        return self._snapshot(
            self._put_json(
                "/playlists/" + self._path_id(object_id) + "/tracks",
                data={"uris": self._uri_list(uris)},
            )
        )

    def reorder_playlist_items(self, object_id, range_start, insert_before, range_length=None, snapshot_id=None):
        data = {
            "range_start": range_start,
            "insert_before": insert_before,
        }
        self._add_query(data, "range_length", range_length)
        self._add_query(data, "snapshot_id", snapshot_id)
        return self._snapshot(self._put_json("/playlists/" + self._path_id(object_id) + "/items", data=data))

    def reorder_playlist_tracks(self, object_id, range_start, insert_before, range_length=None, snapshot_id=None):
        data = {
            "range_start": range_start,
            "insert_before": insert_before,
        }
        self._add_query(data, "range_length", range_length)
        self._add_query(data, "snapshot_id", snapshot_id)
        return self._snapshot(self._put_json("/playlists/" + self._path_id(object_id) + "/tracks", data=data))

    def follow_playlist(self, object_id, public=None):
        data = {}
        self._add_query(data, "public", public)
        return self._put_json("/playlists/" + self._path_id(object_id) + "/followers", data=data)

    def unfollow_playlist(self, object_id):
        return self._delete_json("/playlists/" + self._path_id(object_id) + "/followers")

    def playlist_followers_contains(self, object_id, ids):
        return self._bools("/playlists/" + self._path_id(object_id) + "/followers/contains", ids)

    def episode(self, object_id, market=None):
        return self._one(Episode, "/episodes/" + self._path_id(object_id), self._market_query(market))

    def episodes(self, ids, market=None):
        return self._many(Episode, "episodes", "/episodes", ids, self._market_query(market))

    def show(self, object_id, market=None):
        return self._one(Show, "/shows/" + self._path_id(object_id), self._market_query(market))

    def shows(self, ids, market=None):
        return self._many(Show, "shows", "/shows", ids, self._market_query(market))

    def show_episodes(self, object_id, market=None, limit=None, offset=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        return self._page(EpisodePage, "/shows/" + self._path_id(object_id) + "/episodes", query)

    def audiobook(self, object_id, market=None):
        return self._one(Audiobook, "/audiobooks/" + self._path_id(object_id), self._market_query(market))

    def audiobooks(self, ids, market=None):
        return self._many(Audiobook, "audiobooks", "/audiobooks", ids, self._market_query(market))

    def audiobook_chapters(self, object_id, market=None, limit=None, offset=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        return self._page(ChapterPage, "/audiobooks/" + self._path_id(object_id) + "/chapters", query)

    def chapter(self, object_id, market=None):
        return self._one(Chapter, "/chapters/" + self._path_id(object_id), self._market_query(market))

    def chapters(self, ids, market=None):
        return self._many(Chapter, "chapters", "/chapters", ids, self._market_query(market))

    def audio_features(self, object_id):
        return self._one(AudioFeatures, "/audio-features/" + self._path_id(object_id))

    def audio_features_many(self, ids):
        return self._many(AudioFeatures, "audio_features", "/audio-features", ids)

    def audio_analysis(self, object_id):
        return self._one(AudioAnalysis, "/audio-analysis/" + self._path_id(object_id))

    def recommendations(self, seed_artists=None, seed_genres=None, seed_tracks=None, limit=None, market=None, **kwargs):
        query = {}
        self._add_query(query, "seed_artists", self._join_optional(seed_artists))
        self._add_query(query, "seed_genres", self._join_optional(seed_genres))
        self._add_query(query, "seed_tracks", self._join_optional(seed_tracks))
        self._add_query(query, "limit", limit)
        self._add_query(query, "market", market)

        for key in kwargs:
            self._add_query(query, key, kwargs[key])

        return self._one(Recommendations, "/recommendations", query)

    def category(self, object_id, country=None, locale=None):
        query = {}
        self._add_query(query, "country", country)
        self._add_query(query, "locale", locale)
        return self._one(Category, "/browse/categories/" + self._path_id(object_id), query)

    def categories(self, country=None, locale=None, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        self._add_query(query, "country", country)
        self._add_query(query, "locale", locale)
        data = self._get_json("/browse/categories", query=query)
        return CategoryPage(data.get("categories", data))

    def category_playlists(self, category_id, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        data = self._get_json("/browse/categories/" + self._path_id(category_id) + "/playlists", query=query)
        return PlaylistPage(data.get("playlists", data))

    def featured_playlists(self, country=None, locale=None, timestamp=None, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        self._add_query(query, "country", country)
        self._add_query(query, "locale", locale)
        self._add_query(query, "timestamp", timestamp)
        return self._one(FeaturedPlaylists, "/browse/featured-playlists", query)

    def new_releases(self, country=None, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        self._add_query(query, "country", country)
        data = self._get_json("/browse/new-releases", query=query)
        return AlbumPage(data.get("albums", data))

    def search(self, q, item_types, market=None, limit=None, offset=None, include_external=None):
        query = self._page_query(market=market, limit=limit, offset=offset)
        self._add_query(query, "q", q)
        self._add_query(query, "type", self._join_ids(item_types))
        self._add_query(query, "include_external", include_external)
        return self._one(SearchResults, "/search", query)

    def me(self):
        return self._one(PrivateUser, "/me")

    def user(self, object_id):
        return self._one(User, "/users/" + self._path_id(object_id))

    def current_playback(self, market=None, additional_types=None):
        query = {}
        self._add_query(query, "market", market)
        self._add_query(query, "additional_types", additional_types)
        return self._one(CurrentlyPlaying, "/me/player", query)

    def currently_playing(self, market=None, additional_types=None):
        query = {}
        self._add_query(query, "market", market)
        self._add_query(query, "additional_types", additional_types)
        return self._one(CurrentlyPlaying, "/me/player/currently-playing", query)

    def queue(self):
        return self._one(Queue, "/me/player/queue")

    def transfer_playback(self, device_ids, play=None):
        data = {"device_ids": self._string_list(device_ids)}
        self._add_query(data, "play", play)
        return self._put_json("/me/player", data=data)

    def play(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        local = self._local(device_id)
        if local is not None:
            return local.play(context_uri=context_uri, uris=uris, position_ms=position_ms)
        data = {}
        self._add_query(data, "context_uri", context_uri)
        if uris is not None:
            data["uris"] = self._uri_list(uris)
        self._add_query(data, "offset", offset)
        self._add_query(data, "position_ms", position_ms)
        return self._put_json("/me/player/play", data=data, query=self._device_query(device_id))

    def pause(self, device_id=None):
        local = self._local(device_id)
        if local is not None:
            return local.pause()
        return self._put_json("/me/player/pause", query=self._device_query(device_id))

    def next_track(self, device_id=None):
        local = self._local(device_id)
        if local is not None:
            return local.next()
        return self._post_json("/me/player/next", query=self._device_query(device_id))

    def previous_track(self, device_id=None):
        local = self._local(device_id)
        if local is not None:
            return local.previous()
        return self._post_json("/me/player/previous", query=self._device_query(device_id))

    def seek(self, position_ms, device_id=None):
        local = self._local(device_id)
        if local is not None:
            return local.seek(position_ms)
        query = {"position_ms": position_ms}
        self._add_query(query, "device_id", device_id)
        return self._put_json("/me/player/seek", query=query)

    def repeat(self, state, device_id=None):
        query = {"state": state}
        self._add_query(query, "device_id", device_id)
        return self._put_json("/me/player/repeat", query=query)

    def shuffle(self, state, device_id=None):
        query = {"state": bool_string(state)}
        self._add_query(query, "device_id", device_id)
        return self._put_json("/me/player/shuffle", query=query)

    def volume(self, volume_percent, device_id=None):
        local = self._local(device_id)
        if local is not None:
            return local.set_volume(volume_percent)
        query = {"volume_percent": volume_percent}
        self._add_query(query, "device_id", device_id)
        return self._put_json("/me/player/volume", query=query)

    def add_to_queue(self, uri, device_id=None):
        query = {"uri": self._uri(uri)}
        self._add_query(query, "device_id", device_id)
        return self._post_json("/me/player/queue", query=query)

    def devices(self):
        data = self._get_json("/me/player/devices")
        devices = data.get("devices")
        result = [] if devices is None else [Device(item) for item in devices]
        if self.local is not None and self.local.device_id is not None:
            local_state = self.local.state()
            if not any(getattr(item, "id", None) == self.local.device_id for item in result):
                result.append(Device(local_state))
        return result

    def recently_played(self, limit=None, after=None, before=None):
        query = {}
        self._add_query(query, "limit", limit)
        self._add_query(query, "after", after)
        self._add_query(query, "before", before)
        return self._page(PlayHistoryCursorPage, "/me/player/recently-played", query)

    def current_user_playlists(self, limit=None, offset=None):
        return self._page(PlaylistPage, "/me/playlists", self._page_query(limit=limit, offset=offset))

    def user_playlists(self, object_id, limit=None, offset=None):
        return self._page(
            PlaylistPage,
            "/users/" + self._path_id(object_id) + "/playlists",
            self._page_query(limit=limit, offset=offset),
        )

    def saved_albums(self, market=None, limit=None, offset=None):
        return self._page(SavedAlbumPage, "/me/albums", self._page_query(market=market, limit=limit, offset=offset))

    def saved_tracks(self, market=None, limit=None, offset=None):
        return self._page(SavedTrackPage, "/me/tracks", self._page_query(market=market, limit=limit, offset=offset))

    def saved_episodes(self, market=None, limit=None, offset=None):
        return self._page(SavedEpisodePage, "/me/episodes", self._page_query(market=market, limit=limit, offset=offset))

    def saved_shows(self, limit=None, offset=None):
        return self._page(SavedShowPage, "/me/shows", self._page_query(limit=limit, offset=offset))

    def saved_audiobooks(self, limit=None, offset=None):
        return self._page(AudiobookPage, "/me/audiobooks", self._page_query(limit=limit, offset=offset))

    def contains_saved_albums(self, ids):
        return self._bools("/me/albums/contains", ids)

    def save_albums(self, ids):
        return self._put_ids("/me/albums", ids)

    def remove_saved_albums(self, ids):
        return self._delete_ids("/me/albums", ids)

    def contains_saved_tracks(self, ids):
        return self._bools("/me/tracks/contains", ids)

    def save_tracks(self, ids):
        return self._put_ids("/me/tracks", ids)

    def remove_saved_tracks(self, ids):
        return self._delete_ids("/me/tracks", ids)

    def contains_saved_episodes(self, ids):
        return self._bools("/me/episodes/contains", ids)

    def save_episodes(self, ids):
        return self._put_ids("/me/episodes", ids)

    def remove_saved_episodes(self, ids):
        return self._delete_ids("/me/episodes", ids)

    def contains_saved_shows(self, ids):
        return self._bools("/me/shows/contains", ids)

    def save_shows(self, ids):
        return self._put_ids("/me/shows", ids)

    def remove_saved_shows(self, ids):
        return self._delete_ids("/me/shows", ids)

    def contains_saved_audiobooks(self, ids):
        return self._bools("/me/audiobooks/contains", ids)

    def save_audiobooks(self, ids):
        return self._put_ids("/me/audiobooks", ids)

    def remove_saved_audiobooks(self, ids):
        return self._delete_ids("/me/audiobooks", ids)

    def library_contains(self, uris):
        return tuple(bool(value) for value in self._get_json("/me/library/contains", query=self._query_with_uris(uris)))

    def save_library_items(self, uris):
        return self._put_json("/me/library", query=self._query_with_uris(uris))

    def remove_library_items(self, uris):
        return self._delete_json("/me/library", query=self._query_with_uris(uris))

    def followed_artists(self, after=None, limit=None):
        query = {"type": "artist"}
        self._add_query(query, "after", after)
        self._add_query(query, "limit", limit)
        data = self._get_json("/me/following", query=query)
        return ArtistCursorPage(data.get("artists", data))

    def follows_artists(self, ids):
        return self._following_bools("artist", ids)

    def follows_users(self, ids):
        return self._following_bools("user", ids)

    def follow_artists(self, ids):
        return self._follow("artist", ids)

    def follow_users(self, ids):
        return self._follow("user", ids)

    def unfollow_artists(self, ids):
        return self._unfollow("artist", ids)

    def unfollow_users(self, ids):
        return self._unfollow("user", ids)

    def top_artists(self, time_range=None, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        self._add_query(query, "time_range", time_range)
        return self._page(ArtistPage, "/me/top/artists", query)

    def top_tracks(self, time_range=None, limit=None, offset=None):
        query = self._page_query(limit=limit, offset=offset)
        self._add_query(query, "time_range", time_range)
        return self._page(TrackPage, "/me/top/tracks", query)

    def playlist_cover_image(self, object_id):
        data = self._get_json("/playlists/" + self._path_id(object_id) + "/images")
        return [Image(item) for item in data]

    def set_playlist_cover_image(self, object_id, base64_jpeg):
        return self._put_body(
            "/playlists/" + self._path_id(object_id) + "/images",
            base64_jpeg,
            "image/jpeg",
        )

    def available_markets(self):
        data = self._get_json("/markets")
        markets = data.get("markets")
        if markets is None:
            return ()
        return markets

    def recommendation_genres(self):
        data = self._get_json("/recommendations/available-genre-seeds")
        genres = data.get("genres")
        if genres is None:
            return ()
        return genres

    def _market_query(self, market):
        if market is None:
            return None
        return {"market": market}

    def _page_query(self, market=None, limit=None, offset=None):
        query = {}
        self._add_query(query, "market", market)
        self._add_query(query, "limit", limit)
        self._add_query(query, "offset", offset)
        return query

    def _device_query(self, device_id):
        if device_id is None:
            return None
        return {"device_id": device_id}

    def _query_with_ids(self, ids, query=None):
        if query is None:
            query = {}
        else:
            query = dict(query)
        query["ids"] = self._join_ids(ids)
        return query

    def _query_with_uris(self, uris, query=None):
        if query is None:
            query = {}
        else:
            query = dict(query)
        query["uris"] = self._join_uris(uris)
        return query

    def _bools(self, path, ids, query=None):
        return tuple(bool(value) for value in self._get_json(path, query=self._query_with_ids(ids, query=query)))

    def _following_bools(self, item_type, ids):
        query = {"type": item_type}
        return self._bools("/me/following/contains", ids, query=query)

    def _put_ids(self, path, ids):
        return self._put_json(path, data={"ids": self._id_list(ids)})

    def _delete_ids(self, path, ids):
        return self._delete_json(path, data={"ids": self._id_list(ids)})

    def _follow(self, item_type, ids):
        return self._put_json("/me/following", data={"ids": self._id_list(ids)}, query={"type": item_type})

    def _unfollow(self, item_type, ids):
        return self._delete_json("/me/following", data={"ids": self._id_list(ids)}, query={"type": item_type})

    def _snapshot(self, data):
        if data is None:
            return None
        return SnapshotResult(data)

    def _id_list(self, ids):
        if isinstance(ids, str):
            return [ids]
        return [self._id(value) for value in ids]

    def _id(self, value):
        object_id = getattr(value, "id", None)
        if object_id is not None:
            return object_id
        return str(value)

    def _uri_list(self, values):
        if isinstance(values, str):
            return [values]
        return [self._uri(value) for value in values]

    def _uri(self, value):
        uri = getattr(value, "uri", None)
        if uri is not None:
            return uri
        return str(value)

    def _string_list(self, values):
        if isinstance(values, str):
            return [values]
        return [str(value) for value in values]

    def _join_ids(self, ids):
        if isinstance(ids, str):
            return ids
        return ",".join(str(value) for value in ids)

    def _join_uris(self, uris):
        if isinstance(uris, str):
            return uris
        return ",".join(self._uri(value) for value in uris)

    def _join_optional(self, values):
        if values is None:
            return None
        return self._join_ids(values)

    def _add_query(self, query, field, value):
        if value is not None:
            query[field] = value


def bool_string(value):
    if value:
        return "true"
    return "false"


def snapshot_id(result):
    if result is None:
        return None
    value = getattr(result, "snapshot_id", None)
    if value is not None:
        return value
    return result.get("snapshot_id")
