import os
import sys

sys.path.insert(0, os.getcwd())

from sayso import SpotifyClient

client = SpotifyClient()
me = client.me()
print("me.display_name:", me.display_name)
current_user_playlists = client.current_user_playlists()

playlist = None
for pl in current_user_playlists:
    if pl.owner and pl.owner.id == me.id:
        playlist = pl
        break

if playlist is None:
    raise SystemExit("No owned playlist found")

print("playlist.name:", playlist.name)
images = playlist.images
if images:
    print("playlist.images[0].url:", images[0].url)

playlist_item = playlist.items[0]
added_by = playlist_item.added_by
if added_by is not None:
    print("playlist_item.added_by.id:", added_by.id)

track = playlist_item.item
print("track.name:", track.name)
artist = track.artists[0]
print("artist.name:", artist.name)
print("artist.genres:", artist.genres)

album = artist.albums[0]
print("album.name:", album.name)
print("album.label:", album.label)
album_tracks = album.tracks
if album_tracks is not None and len(album_tracks) > 0:
    print("album.tracks[0].name:", album_tracks[0].name)
