# MicroPython cannot import names re-exported from sayso/__init__.py; use submodules.
import os
import time

from sayso.auth import (
    AuthorizationCodeAuth,
    SpotifyAuthError,
    TokenCache,
    authorize_with_local_server,
    credentials_from_config,
    load_config,
    redirect_uri_from_config,
    PLAYBACK_READ_SCOPES,
    PLAYBACK_WRITE_SCOPES,
    LIBRARY_READ_SCOPES,
    LIBRARY_WRITE_SCOPES,
    PLAYLIST_READ_SCOPES,
    PLAYLIST_WRITE_SCOPES,
    USER_PROFILE_SCOPES,
)
from sayso.client import SpotifyClient
from sayso.transport import TransportError
from spotify_remote import artwork_cache
from spotify_remote import config as remote_config
from spotify_remote import genre_seeds
from spotify_remote import gil

SCOPES = (
    USER_PROFILE_SCOPES
    + PLAYBACK_READ_SCOPES
    + PLAYBACK_WRITE_SCOPES
    + LIBRARY_READ_SCOPES
    + LIBRARY_WRITE_SCOPES
    + PLAYLIST_READ_SCOPES
    + PLAYLIST_WRITE_SCOPES
    + ("user-follow-read",)
)


class NoActiveDeviceError(Exception):
    pass


def _error_message(error):
    if isinstance(error, TransportError):
        data = getattr(error, "data", None)
        if isinstance(data, dict):
            nested = data.get("error")
            if isinstance(nested, dict):
                message = nested.get("message", "") or ""
                if message:
                    return message
            message = data.get("message", "") or ""
            if message:
                return message
        if isinstance(data, str):
            return data
    return str(error)


def is_no_active_device_error(error):
    if isinstance(error, NoActiveDeviceError):
        return True
    if isinstance(error, TransportError) and getattr(error, "status", None) == 404:
        return "no active device" in _error_message(error).lower()
    return False


def _http_status(error):
    status = getattr(error, "status", None)
    if isinstance(status, str) and status.isdigit():
        return int(status)
    return status


def _is_scope_error(error):
    if not isinstance(error, TransportError) or _http_status(error) != 403:
        return False
    return "scope" in _error_message(error).lower()


def needs_authorization(error):
    if isinstance(error, SpotifyAuthError):
        return True
    if isinstance(error, TransportError):
        status = _http_status(error)
        if status == 401:
            return True
        if _is_scope_error(error):
            return True
    return False


def is_transient_error(error):
    if isinstance(error, TransportError):
        status = _http_status(error)
        if status == 429:
            return True
        if status and status >= 500:
            return True
    return False


def friendly_error(error):
    if is_no_active_device_error(error):
        return "Select a device to play"
    if isinstance(error, TransportError):
        status = _http_status(error)
        if status == 401:
            return "Not authorized - sign in again"
        if status == 403:
            return "Permission denied - check app scopes"
        if status == 404:
            return "Not found"
        if status == 429:
            wait = getattr(error, "retry_after", None)
            if wait and wait >= 120:
                if wait >= 5400:
                    when = "about %d hours" % ((wait + 1800) // 3600)
                else:
                    when = "about %d minutes" % ((wait + 30) // 60)
                return "Spotify is limiting this app - back in %s" % when
            return "Too many requests - wait a moment"
        if status and status >= 500:
            return "Spotify service error ({})".format(status)
    message = str(error)
    if len(message) > 120:
        return message[:117] + "..."
    return message


def _app_dir():
    try:
        path = __file__.replace("\\", "/")
        if "/" in path:
            return path.rsplit("/", 1)[0]
    except NameError:
        pass
    return os.getcwd()


def _data_dir():
    """Where config, tokens and caches live.

    The app's own directory when it runs from source. Frozen into firmware
    it has none (its __file__ names no real directory), so it uses the
    directory it was launched from.
    """
    app_dir = _app_dir()
    try:
        os.stat(app_dir)
        return app_dir
    except OSError:
        return os.getcwd().replace("\\", "/")


def _join_dir(directory, name):
    if directory.endswith("/"):
        return directory + name
    return directory + "/" + name


def _config_path(name):
    """Prefer app-local config, falling back when Windows cannot follow its WSL symlink."""
    # Open rather than stat: over \\wsl.localhost a symlink stats fine but
    # cannot be opened.
    # Then the launch directory: a board that installs the app under /lib (or
    # overlays the frozen copy) keeps its config and tokens at /.
    app_path = _join_dir(_data_dir(), name)
    cwd_path = _join_dir(os.getcwd().replace("\\", "/"), name)
    for path in (app_path, _join_dir(_data_dir(), "../../" + name), cwd_path):
        try:
            open(path, "rb").close()
            return path
        except OSError:
            pass
    return app_path


CONFIG_PATH = _config_path("sayso.local.json")
TOKEN_PATH = _config_path("tokens.json")
ART_CACHE_PATH = _join_dir(_data_dir(), "art_cache")
THUMB_CACHE_PATH = _join_dir(_data_dir(), "thumb_cache")
DEVICE_CACHE_SECONDS = 15


def _granted_scopes(cache):
    scope = cache.load().get("scope", "")
    if isinstance(scope, str):
        if not scope:
            return set()
        return set(scope.split())
    if scope:
        return set(scope)
    return set()


def _ensure_scopes(auth, cache):
    required = set(SCOPES)
    granted = _granted_scopes(cache)
    if granted and required.issubset(granted):
        return

    auth.scope = SCOPES
    authorize_with_local_server(
        auth,
        redirect_uri=auth.redirect_uri,
        state="spotify_remote",
    )


def _cache_memory_bytes(setting, board_default):
    if setting is not None:
        return setting
    import sys

    return board_default if sys.platform == "esp32" else 0


class SpotifyController:
    def __init__(self):
        auth_config = load_config(CONFIG_PATH)
        client_id, client_secret = credentials_from_config(auth_config)
        cache = TokenCache(TOKEN_PATH)
        auth = AuthorizationCodeAuth(
            client_id,
            client_secret,
            redirect_uri_from_config(auth_config),
            scope=SCOPES,
            token_cache=cache,
        )
        cache.load_auth(auth)
        _ensure_scopes(auth, cache)
        self._auth = auth
        self._cache = cache
        self.client = SpotifyClient(auth=auth)
        self.art_cache = artwork_cache.ArtworkCache(
            ART_CACHE_PATH,
            max_items=remote_config.ART_CACHE_MAX_ITEMS,
            memory_bytes=_cache_memory_bytes(remote_config.ART_CACHE_MEMORY_BYTES, 1024 * 1024),
        )
        self.thumb_cache = artwork_cache.ArtworkCache(
            THUMB_CACHE_PATH,
            max_items=remote_config.THUMB_CACHE_MAX_ITEMS,
            memory_bytes=_cache_memory_bytes(remote_config.THUMB_CACHE_MEMORY_BYTES, 512 * 1024),
        )
        self._me = None
        self._library_cache = {}
        self._library_limit = remote_config.LIBRARY_LIST_LIMIT
        self._browse_limit = remote_config.BROWSE_LIST_LIMIT
        self._queue_limit = remote_config.QUEUE_LIST_LIMIT
        self._recent_limit = remote_config.RECENT_LIST_LIMIT
        self._search_limit = remote_config.SEARCH_RESULT_LIMIT
        self._cached_saved_track_id = None
        self._cached_saved_state = None
        self._cached_saved_album_id = None
        self._cached_album_saved_state = None
        self._genre_presets = None
        self._genre_presets_from_api = False
        self._cached_artist_track_id = None
        self._cached_artists = ()
        self._cached_active_device = None
        self._cached_active_device_at = 0
        self._context_name_cache = {}

    def _ensure_scopes_on_403(self, error):
        if not self._is_scope_error(error):
            return False
        _ensure_scopes(self._auth, self._cache)
        return True

    def _is_scope_error(self, error):
        return _is_scope_error(error)

    def _spotify_uri(self, item_type, object_id):
        return "spotify:{}:{}".format(item_type, object_id)

    def me(self):
        if self._me is None:
            self._me = self.client.me()
        return self._me

    def _empty_playback_state(self, device="", device_id=None, volume=None):
        return {
            "playing": False,
            "track": "",
            "artist": "",
            "album": "",
            "artists": (),
            "item_id": None,
            "item_uri": None,
            "item_type": None,
            "context_type": None,
            "context_name": "",
            "context_uri": None,
            "album_id": None,
            "album_uri": None,
            "saved": None,
            "album_saved": None,
            "art_url": None,
            "art_path": None,
            "progress_ms": 0,
            "duration_ms": 0,
            "shuffle": None,
            "repeat": None,
            "volume": volume,
            "device": device,
            "device_id": device_id,
        }

    def refresh_now_playing(self):
        current = self.client.current_playback()
        if current is None or not current.raw():
            active = self._active_device()
            if active is not None:
                return self._empty_playback_state(
                    device=active.name or "",
                    device_id=active.id,
                    volume=active.volume_percent,
                )
            return self._empty_playback_state()

        item = current.item
        item_id = None
        item_uri = None
        item_type = current.currently_playing_type or None
        track = ""
        artist = ""
        album_name = ""
        album_id = None
        album_uri = None
        artists = ()
        duration_ms = 0
        art_url = None
        art_path = None
        saved = None
        album_saved = None
        context_type = None
        context_name = ""
        context_uri = None

        context = getattr(current, "context", None)
        if context is not None:
            context_type = getattr(context, "type", None)
            context_uri = getattr(context, "uri", None)

        if item is not None:
            item_id = getattr(item, "id", None)
            item_uri = getattr(item, "uri", None)
            item_type = item_type or getattr(item, "type", None)
            track = item.name or ""
            duration_ms = getattr(item, "duration_ms", 0) or 0
            item_artists = getattr(item, "artists", None)
            artists = self._artist_entries(item_artists)
            if artists:
                artist = ", ".join(entry["name"] for entry in artists)
            album = getattr(item, "album", None)
            if album is not None:
                album_name = album.name or ""
                album_id = getattr(album, "id", None)
                album_uri = getattr(album, "uri", None)
                art_url = self._best_image_url(getattr(album, "images", ()))
            if not art_url:
                show = getattr(item, "show", None)
                if show is not None:
                    album_name = show.name or ""
                art_url = self._best_image_url(getattr(item, "images", ()))

        if context_type == "album":
            context_name = album_name
        elif context_type == "playlist" and context_uri:
            context_id = context_uri.rsplit(":", 1)[-1]
            cached = getattr(self, "_context_name_cache", {}).get(context_uri)
            if cached is None:
                try:
                    cached = self.client.playlist(context_id).name or ""
                except Exception:
                    cached = ""
                self._context_name_cache[context_uri] = cached
            context_name = cached

        if art_url:
            art_path = self.art_cache.path_for_url(art_url)

        if item_type == "track" and item_id:
            saved = self._track_saved(item_id)
        if album_id:
            album_saved = self._album_saved(album_id)
        if item_type == "track" and artists:
            if item_id and item_id == self._cached_artist_track_id:
                artists = self._cached_artists
            else:
                uris = []
                for artist_entry in artists:
                    uri = artist_entry.get("uri")
                    if uri:
                        uris.append(uri)
                if uris:
                    followed_map = self.library_contains_batch(uris)
                    enriched = []
                    for artist_entry in artists:
                        entry = {
                            "id": artist_entry["id"],
                            "name": artist_entry["name"],
                            "uri": artist_entry.get("uri"),
                        }
                        uri = entry.get("uri")
                        if uri in followed_map:
                            entry["followed"] = followed_map[uri]
                        enriched.append(entry)
                    artists = tuple(enriched)
                self._cached_artist_track_id = item_id
                self._cached_artists = artists

        device = ""
        device_id = None
        volume = None
        if current.device is not None:
            device = current.device.name or ""
            device_id = current.device.id
            volume = current.device.volume_percent

        return {
            "playing": bool(current.is_playing),
            "track": track,
            "artist": artist,
            "album": album_name,
            "artists": artists,
            "item_id": item_id,
            "item_uri": item_uri,
            "item_type": item_type,
            "context_type": context_type,
            "context_name": context_name,
            "context_uri": context_uri,
            "album_id": album_id,
            "album_uri": album_uri,
            "saved": saved,
            "album_saved": album_saved,
            "art_url": art_url,
            "art_path": art_path,
            "progress_ms": current.progress_ms or 0,
            "duration_ms": duration_ms,
            "shuffle": current.shuffle_state,
            "repeat": current.repeat_state,
            "volume": volume,
            "device": device,
            "device_id": device_id,
        }

    def _track_saved(self, track_id):
        for attempt in range(2):
            try:
                if track_id != self._cached_saved_track_id:
                    uri = self._spotify_uri("track", track_id)
                    values = self.client.library_contains([uri])
                    self._cached_saved_track_id = track_id
                    self._cached_saved_state = bool(values[0]) if values else False
                return self._cached_saved_state
            except TransportError as error:
                if attempt == 0 and self._ensure_scopes_on_403(error):
                    continue
                return None

    def _album_saved(self, album_id):
        for attempt in range(2):
            try:
                if album_id != self._cached_saved_album_id:
                    uri = self._spotify_uri("album", album_id)
                    values = self.client.library_contains([uri])
                    self._cached_saved_album_id = album_id
                    self._cached_album_saved_state = bool(values[0]) if values else False
                return self._cached_album_saved_state
            except TransportError as error:
                if attempt == 0 and self._ensure_scopes_on_403(error):
                    continue
                return None

    def toggle_save_track(self, track_id, saved):
        uri = self._spotify_uri("track", track_id)
        if saved:
            self.client.remove_library_items([uri])
            self._cached_saved_state = False
        else:
            self.client.save_library_items([uri])
            self._cached_saved_state = True
        self._cached_saved_track_id = track_id
        self._library_cache.pop("tracks", None)

    def toggle_save_album(self, album_id, saved):
        uri = self._spotify_uri("album", album_id)
        if saved:
            self.client.remove_library_items([uri])
            self._cached_album_saved_state = False
        else:
            self.client.save_library_items([uri])
            self._cached_album_saved_state = True
        self._cached_saved_album_id = album_id
        self._library_cache.pop("albums", None)

    def toggle_save_episode(self, episode_id, saved):
        if saved:
            self.client.remove_saved_episodes([episode_id])
        else:
            self.client.save_episodes([episode_id])
        self._library_cache.pop("episodes", None)

    def toggle_save_audiobook(self, audiobook_id, saved):
        if saved:
            self.client.remove_saved_audiobooks([audiobook_id])
        else:
            self.client.save_audiobooks([audiobook_id])
        self._library_cache.pop("audiobooks", None)

    def editable_playlists(self):
        me = self.me()
        entries = []
        for playlist in self.client.current_user_playlists(limit=self._browse_limit):
            if playlist.owner is None or playlist.owner.id != me.id:
                continue
            entries.append(
                self._library_entry(
                    playlist.name,
                    "Playlist",
                    playlist.uri,
                    "playlist",
                    playlist.id,
                )
            )
        return entries

    def add_to_playlist(self, playlist_id, track_uri):
        self.client.add_playlist_items(playlist_id, [track_uri])

    def remove_from_playlist(self, playlist_id, track_uri):
        self.client.remove_playlist_items(playlist_id, [track_uri])

    def create_playlist(self, name):
        playlist = self.client.create_current_user_playlist(name, public=False)
        return playlist.id

    def add_to_queue(self, uri, device_id=None):
        self.ensure_active_device()
        self.client.add_to_queue(uri, device_id=device_id)

    def play_now(self, uri, item_type="track"):
        self.play_library_item(uri, item_type)

    def play_context(self, context_uri, shuffle=False):
        self.ensure_active_device()
        self.client.play(context_uri=context_uri)
        if shuffle:
            self.client.shuffle(True)

    def toggle_follow_artist(self, artist_id, followed):
        uri = self._spotify_uri("artist", artist_id)
        if followed:
            self.client.remove_library_items([uri])
        else:
            self.client.save_library_items([uri])
        self._library_cache.pop("artists", None)

    def library_contains_batch(self, uris):
        if not uris:
            return {}
        unique = []
        seen = set()
        for uri in uris:
            if uri and uri not in seen:
                seen.add(uri)
                unique.append(uri)
        for attempt in range(2):
            try:
                values = self.client.library_contains(unique)
                return {uri: bool(values[index]) for index, uri in enumerate(unique)}
            except TransportError as error:
                if attempt == 0 and self._ensure_scopes_on_403(error):
                    continue
                return {}
        return {}

    def seek_absolute(self, position_ms):
        self.ensure_active_device()
        self.client.seek(int(position_ms))

    def recently_played_entries(self, limit=None):
        if limit is None:
            limit = self._recent_limit
        entries = []
        for item in self.client.recently_played(limit=limit):
            track = getattr(item, "track", None)
            if track is None:
                continue
            entries.append(self._track_entry(track))
        self._apply_track_saved(entries)
        return entries

    def build_search_query(self, query, result_type, genre_preset=False):
        if genre_preset and result_type in ("track", "artist"):
            slug = query.lower().replace(" ", "-")
            return "genre:{}".format(slug)
        return query

    def genres_from_api(self):
        return bool(self._genre_presets_from_api)

    def find_genre_presets(self, refresh=False):
        if self._genre_presets is not None and not refresh:
            return self._genre_presets

        presets = ()
        from_api = False
        try:
            genres = self.client.recommendation_genres()
            if genres:
                presets = tuple(sorted(set(str(genre) for genre in genres)))
                from_api = True
        except TransportError:
            pass

        if not presets:
            presets = genre_seeds.FALLBACK_GENRES
            from_api = False

        self._genre_presets = presets
        self._genre_presets_from_api = from_api
        return presets

    def search_entries(self, query, result_type="track", limit=None, offset=0):
        if limit is None:
            limit = self._search_limit
        results = self.client.search(
            query, [result_type], limit=limit, offset=offset
        )
        if result_type == "track":
            return self._search_track_entries(results)
        if result_type == "artist":
            return self._search_artist_entries(results)
        if result_type == "album":
            return self._search_album_entries(results)
        if result_type == "playlist":
            return self._search_playlist_entries(results)
        if result_type == "episode":
            return self._search_episode_entries(results)
        if result_type == "show":
            return self._search_show_entries(results)
        if result_type == "audiobook":
            return self._search_audiobook_entries(results)
        return []

    def search_tracks(self, query, limit=None):
        return self.search_entries(query, "track", limit=limit)

    def _search_track_entries(self, results):
        entries = []
        tracks = getattr(results, "tracks", None)
        if tracks is None:
            return entries
        for track in tracks:
            entries.append(self._track_entry(track))
        self._apply_track_saved(entries)
        return entries

    def _search_artist_entries(self, results):
        entries = []
        artists = getattr(results, "artists", None)
        if artists is None:
            return entries
        uris = []
        for artist in artists:
            uri = getattr(artist, "uri", None)
            if uri:
                uris.append(uri)
        followed_map = self.library_contains_batch(uris)
        for artist in artists:
            uri = getattr(artist, "uri", None)
            entries.append(self._artist_entry(artist, followed=followed_map.get(uri)))
        return entries

    def _search_album_entries(self, results):
        entries = []
        albums = getattr(results, "albums", None)
        if albums is None:
            return entries
        uris = []
        for album in albums:
            uri = getattr(album, "uri", None)
            if uri:
                uris.append(uri)
        saved_map = self.library_contains_batch(uris)
        for album in albums:
            uri = getattr(album, "uri", None)
            entries.append(
                self._album_entry(album, saved=saved_map.get(uri))
            )
        return entries

    def _search_playlist_entries(self, results):
        entries = []
        playlists = getattr(results, "playlists", None)
        if playlists is None:
            return entries
        me = self.me()
        for playlist in playlists:
            owner = ""
            owned = False
            if playlist.owner is not None:
                owner = playlist.owner.display_name or playlist.owner.id or ""
                owned = playlist.owner.id == me.id
            entries.append(
                self._library_entry(
                    playlist.name,
                    owner,
                    playlist.uri,
                    "playlist",
                    playlist.id,
                    owned=owned,
                    art_url=self._thumb_url(getattr(playlist, "images", ())),
                )
            )
        return entries

    def _artist_entry(self, artist, followed=None):
        return self._library_entry(
            artist.name,
            "Artist",
            getattr(artist, "uri", None),
            "artist",
            getattr(artist, "id", None),
            followed=followed,
            art_url=self._thumb_url(getattr(artist, "images", ())),
        )

    def _album_entry(self, album, saved=None):
        artist = self._artist_names(getattr(album, "artists", None))
        return self._library_entry(
            album.name,
            artist,
            getattr(album, "uri", None),
            "album",
            getattr(album, "id", None),
            saved=saved,
            art_url=self._thumb_url(getattr(album, "images", ())),
        )

    def _episode_entry(self, episode, saved=None):
        show = getattr(episode, "show", None)
        subtitle = show.name if show is not None else "Episode"
        return self._library_entry(
            episode.name,
            subtitle,
            getattr(episode, "uri", None),
            "episode",
            getattr(episode, "id", None),
            saved=saved,
            art_url=self._thumb_url(getattr(episode, "images", ())),
        )

    def _show_entry(self, show):
        publisher = getattr(show, "publisher", None) or "Show"
        return self._library_entry(
            show.name,
            publisher,
            getattr(show, "uri", None),
            "show",
            getattr(show, "id", None),
            art_url=self._thumb_url(getattr(show, "images", ())),
        )

    def _audiobook_entry(self, audiobook, saved=None):
        authors = getattr(audiobook, "authors", None) or ()
        names = []
        for author in authors:
            name = getattr(author, "name", None)
            if name:
                names.append(name)
        subtitle = ", ".join(names) if names else "Audiobook"
        return self._library_entry(
            audiobook.name,
            subtitle,
            getattr(audiobook, "uri", None),
            "audiobook",
            getattr(audiobook, "id", None),
            saved=saved,
            art_url=self._thumb_url(getattr(audiobook, "images", ())),
        )

    def _search_episode_entries(self, results):
        entries = []
        episodes = getattr(results, "episodes", None)
        if episodes is None:
            return entries
        uris = []
        for episode in episodes:
            uri = getattr(episode, "uri", None)
            if uri:
                uris.append(uri)
        saved_map = self.library_contains_batch(uris)
        for episode in episodes:
            uri = getattr(episode, "uri", None)
            entries.append(
                self._episode_entry(episode, saved=saved_map.get(uri))
            )
        return entries

    def _search_show_entries(self, results):
        entries = []
        shows = getattr(results, "shows", None)
        if shows is None:
            return entries
        for show in shows:
            entries.append(self._show_entry(show))
        return entries

    def _search_audiobook_entries(self, results):
        entries = []
        audiobooks = getattr(results, "audiobooks", None)
        if audiobooks is None:
            return entries
        uris = []
        for audiobook in audiobooks:
            uri = getattr(audiobook, "uri", None)
            if uri:
                uris.append(uri)
        saved_map = self.library_contains_batch(uris)
        for audiobook in audiobooks:
            uri = getattr(audiobook, "uri", None)
            entries.append(
                self._audiobook_entry(audiobook, saved=saved_map.get(uri))
            )
        return entries

    def _track_art_url(self, track):
        # Read embedded data only: album-track pages omit "album", and
        # getattr would fetch every track to fill it in.
        data = track.raw()
        album = data.get("album") or {}
        return self._thumb_url(album.get("images")) or self._thumb_url(data.get("images"))

    def _track_entry(self, track, **extra):
        artist = self._artist_names(getattr(track, "artists", None))
        return self._library_entry(
            track.name,
            artist,
            track.uri,
            "track",
            track.id,
            art_url=self._track_art_url(track),
            **extra
        )

    def album_tracks(self, album_id, limit=None, offset=0):
        if limit is None:
            limit = self._browse_limit
        entries = []
        for track in self.client.album_tracks(
            album_id, limit=limit, offset=offset
        ):
            entries.append(self._track_entry(track, context_id=album_id))
        self._apply_track_saved(entries)
        return entries

    def artist_albums(self, artist_id, limit=None, offset=0):
        if limit is None:
            limit = remote_config.ARTIST_ALBUMS_PAGE_LIMIT
        limit = min(limit, remote_config.ARTIST_ALBUMS_PAGE_LIMIT)
        entries = []
        for album in self.client.artist_albums(
            artist_id, limit=limit, offset=offset
        ):
            artist = self._artist_names(getattr(album, "artists", None))
            entries.append(
                self._library_entry(album.name, artist, album.uri, "album", album.id)
            )
        return entries

    def show_episodes(self, show_id, limit=None, offset=0):
        if limit is None:
            limit = self._browse_limit
        entries = []
        for episode in self.client.show_episodes(
            show_id, limit=limit, offset=offset
        ):
            entries.append(self._episode_entry(episode))
        return entries

    def playlist_tracks(self, playlist_id, owned=False, limit=None, offset=0):
        if limit is None:
            limit = self._browse_limit
        entries = []
        for item in self.client.playlist_items(
            playlist_id, limit=limit, offset=offset
        ):
            # Playlist entries carry the track under "item" (Feb 2026 API).
            track = getattr(item, "item", None)
            if track is None or getattr(track, "type", "track") != "track":
                continue
            entries.append(
                self._track_entry(
                    track,
                    context_id=playlist_id if owned else None,
                )
            )
        self._apply_track_saved(entries)
        return entries

    def playlist_is_owned(self, playlist_id):
        me = self.me()
        playlist = self.client.playlist(playlist_id)
        if playlist.owner is None:
            return False
        return playlist.owner.id == me.id

    def track_is_saved(self, track_id):
        return self._track_saved(track_id)

    def available_devices(self):
        self._cached_active_device_at = 0
        devices = []
        for device in self.client.devices():
            devices.append(
                {
                    "id": device.id,
                    "name": device.name or "Unknown device",
                    "active": bool(device.is_active),
                    "type": getattr(device, "type", None) or "",
                }
            )
        return devices

    def transfer_device(self, device_id, play=True):
        self._cached_active_device_at = 0
        self.client.transfer_playback([device_id], play=play)

    def active_device_id(self, state=None):
        if state is None:
            state = self.refresh_now_playing()
        return state.get("device_id")

    def ensure_active_device(self, state=None):
        if not self.active_device_id(state):
            raise NoActiveDeviceError()

    def _active_device(self, refresh=False):
        now = time.time()
        if (
            not refresh
            and self._cached_active_device_at
            and now - self._cached_active_device_at < DEVICE_CACHE_SECONDS
        ):
            return self._cached_active_device

        active = None
        for device in self.client.devices():
            if device.is_active:
                active = device
                break
        self._cached_active_device = active
        self._cached_active_device_at = now
        return active

    def _thumb_url(self, images):
        """Smallest image that still fills a list thumbnail."""
        return self._best_image_url(images, preferred_width=64)

    def _best_image_url(self, images, preferred_width=300):
        best_fit = None
        best_fit_width = -1
        smallest_larger = None
        smallest_larger_width = None
        for image in images or ():
            if isinstance(image, dict):
                url = image.get("url")
                width = image.get("width") or 0
            else:
                url = getattr(image, "url", None)
                width = getattr(image, "width", None) or 0
            if not url:
                continue
            if width <= preferred_width and width > best_fit_width:
                best_fit = url
                best_fit_width = width
            elif width > preferred_width and (
                smallest_larger_width is None or width < smallest_larger_width
            ):
                smallest_larger = url
                smallest_larger_width = width
        return best_fit or smallest_larger

    def set_playing(self, play):
        """Resume or pause, when the caller already knows which it wants.

        play_pause() asks the Web API for the state first; a UI that shows the
        state saves that round trip.
        """
        self.ensure_active_device()
        if play:
            self.client.play()
        else:
            self.client.pause()

    def play_pause(self):
        state = self.refresh_now_playing()
        self.ensure_active_device(state)
        if state["playing"]:
            self.client.pause()
        else:
            self.client.play()

    def next_track(self):
        self.ensure_active_device()
        self.client.next_track()

    def previous_track(self):
        self.ensure_active_device()
        self.client.previous_track()

    def seek_relative(self, delta_ms):
        state = self.refresh_now_playing()
        self.ensure_active_device(state)
        duration = state["duration_ms"] or 0
        position = (state["progress_ms"] or 0) + delta_ms
        if position < 0:
            position = 0
        if duration and position > duration:
            position = duration
        self.client.seek(position)

    def toggle_shuffle(self):
        state = self.refresh_now_playing()
        self.ensure_active_device(state)
        self.client.shuffle(not bool(state["shuffle"]))

    def cycle_repeat(self):
        state = self.refresh_now_playing()
        self.ensure_active_device(state)
        current = state["repeat"] or "off"
        if current == "off":
            next_state = "context"
        elif current == "context":
            next_state = "track"
        else:
            next_state = "off"
        self.client.repeat(next_state)

    def change_volume_absolute(self, volume):
        self.ensure_active_device()
        volume = int(volume)
        if volume < 0:
            volume = 0
        if volume > 100:
            volume = 100
        self.client.volume(volume)

    def play_library_item(self, uri, item_type):
        self.ensure_active_device()
        if item_type in ("track", "episode"):
            self.client.play(uris=[uri])
        else:
            self.client.play(context_uri=uri)

    def queue_entries(self):
        queue = self.client.queue()
        entries = []
        current = queue.currently_playing
        if current is not None:
            entry = self._queue_entry(current, "Now playing")
            entry["now_playing"] = True
            entries.append(entry)
        count = 0
        for item in queue.queue or ():
            if count >= self._queue_limit:
                break
            entries.append(self._queue_entry(item))
            count += 1
        return entries

    def _queue_entry(self, item, subtitle_prefix=""):
        item_type = getattr(item, "type", None) or "track"
        subtitle = subtitle_prefix
        if item_type == "track":
            artist = self._artist_names(getattr(item, "artists", None))
            if subtitle_prefix and artist:
                subtitle = subtitle_prefix + " • " + artist
            elif artist:
                subtitle = artist
        elif item_type == "episode":
            show = getattr(item, "show", None)
            if show is not None:
                show_name = show.name or ""
                if subtitle_prefix and show_name:
                    subtitle = subtitle_prefix + " • " + show_name
                elif show_name:
                    subtitle = show_name
        return self._library_entry(
            item.name,
            subtitle,
            getattr(item, "uri", None),
            item_type,
            getattr(item, "id", None),
        )

    def library_entries(self, category, limit=None, offset=0):
        fetch_limit = limit if limit is not None else self._library_limit
        if limit is None and offset == 0 and category in self._library_cache:
            return self._library_cache[category]

        if category == "tracks":
            entries = self.library_tracks(limit=fetch_limit, offset=offset)
        elif category == "albums":
            entries = self.library_albums(limit=fetch_limit, offset=offset)
        elif category == "artists":
            # Followed artists page by cursor, not offset: fetch through this
            # page and keep its end.
            entries = self.library_artists(limit=min(50, offset + fetch_limit))[offset:]
        elif category == "playlists":
            entries = self.library_playlists(limit=fetch_limit, offset=offset)
        elif category == "episodes":
            entries = self.library_episodes(limit=fetch_limit, offset=offset)
        elif category == "shows":
            entries = self.library_shows(limit=fetch_limit, offset=offset)
        elif category == "audiobooks":
            entries = self.library_audiobooks(limit=fetch_limit, offset=offset)
        else:
            entries = ()

        if limit is None and offset == 0:
            self._library_cache[category] = entries
        return entries

    def library_tracks(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        for saved in self.client.saved_tracks(limit=limit, offset=offset):
            track = saved.track
            if track is None:
                continue
            entries.append(self._track_entry(track, saved=True))
        return entries

    def library_albums(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        for saved in self.client.saved_albums(limit=limit, offset=offset):
            album = saved.album
            if album is None:
                continue
            artist = self._artist_names(getattr(album, "artists", None))
            entries.append(
                self._library_entry(
                    album.name,
                    artist,
                    album.uri,
                    "album",
                    album.id,
                    saved=True,
                )
            )
        return entries

    def library_artists(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        try:
            artists = self.client.followed_artists(limit=limit)
        except TransportError as error:
            if self._ensure_scopes_on_403(error):
                artists = self.client.followed_artists(limit=limit)
            else:
                raise
        for artist in artists:
            entries.append(
                self._library_entry(
                    artist.name,
                    "Artist",
                    artist.uri,
                    "artist",
                    artist.id,
                    followed=True,
                )
            )
        return entries

    def library_playlists(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        me = self.me()
        entries = []
        for playlist in self.client.current_user_playlists(limit=limit, offset=offset):
            owner = ""
            owned = False
            if playlist.owner is not None:
                owner = playlist.owner.display_name or playlist.owner.id or ""
                owned = playlist.owner.id == me.id
            entries.append(
                self._library_entry(
                    playlist.name,
                    owner,
                    playlist.uri,
                    "playlist",
                    playlist.id,
                    owned=owned,
                )
            )
        return entries

    def library_episodes(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        for saved in self.client.saved_episodes(limit=limit, offset=offset):
            episode = saved.episode
            if episode is None:
                continue
            entries.append(self._episode_entry(episode, saved=True))
        return entries

    def library_shows(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        for saved in self.client.saved_shows(limit=limit, offset=offset):
            show = saved.show
            if show is None:
                continue
            entries.append(self._show_entry(show))
        return entries

    def library_audiobooks(self, limit=None, offset=0):
        if limit is None:
            limit = self._library_limit
        entries = []
        for audiobook in self.client.saved_audiobooks(limit=limit, offset=offset):
            entries.append(self._audiobook_entry(audiobook, saved=True))
        return entries

    def _apply_track_saved(self, entries):
        uris = [entry["uri"] for entry in entries if entry.get("uri")]
        saved_map = self.library_contains_batch(uris)
        for entry in entries:
            uri = entry.get("uri")
            if uri in saved_map:
                entry["saved"] = saved_map[uri]

    def _library_entry(
        self,
        title,
        subtitle,
        uri,
        item_type,
        object_id=None,
        saved=None,
        album_saved=None,
        followed=None,
        context_id=None,
        owned=None,
        art_url=None,
        now_playing=None,
    ):
        # Every list entry passes here: let the UI thread in between them.
        gil.cooperate()
        entry = {
            "title": title or "Untitled",
            "subtitle": subtitle or "",
            "uri": uri,
            "type": item_type,
            "id": object_id,
        }
        if saved is not None:
            entry["saved"] = saved
        if album_saved is not None:
            entry["album_saved"] = album_saved
        if followed is not None:
            entry["followed"] = followed
        if context_id is not None:
            entry["context_id"] = context_id
        if owned is not None:
            entry["owned"] = owned
        if art_url is not None:
            entry["art_url"] = art_url
        if now_playing is not None:
            entry["now_playing"] = now_playing
        return entry

    def _artist_entries(self, artists):
        entries = []
        for artist in artists or ():
            artist_id = getattr(artist, "id", None)
            if not artist_id:
                continue
            entries.append(
                {
                    "id": artist_id,
                    "name": artist.name or "",
                    "uri": getattr(artist, "uri", None),
                }
            )
        return tuple(entries)

    def _artist_names(self, artists):
        if not artists:
            return ""
        return ", ".join(artist.name or "" for artist in artists)
