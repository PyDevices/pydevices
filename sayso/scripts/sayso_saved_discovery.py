import os
import sys

sys.path.insert(0, os.getcwd())

from sayso import SpotifyClient

client = SpotifyClient()
me = client.me()
print("me.display_name:", me.display_name)

saved_tracks = client.saved_tracks(limit=2)
if len(saved_tracks) == 0:
    raise SystemExit("No saved tracks found")

print("saved_tracks.total:", saved_tracks.total)
saved_track = saved_tracks[0]
print("saved_track.added_at:", saved_track.added_at)
print("saved_track.track.name:", saved_track.track.name)
print("saved_track.track.artists[0].name:", saved_track.track.artists[0].name)

if len(saved_tracks) > 1:
    print("saved_tracks[1].track.name:", saved_tracks[1].track.name)

next_tracks = client.next_page(saved_tracks)
if next_tracks is not None:
    print("next saved_tracks page total:", next_tracks.total)
    print("next saved_tracks[0].track.name:", next_tracks[0].track.name)

saved_albums = client.saved_albums(limit=2)
if len(saved_albums) == 0:
    raise SystemExit("No saved albums found")

print("saved_albums.total:", saved_albums.total)
saved_album = saved_albums[0]
print("saved_album.added_at:", saved_album.added_at)
print("saved_album.album.name:", saved_album.album.name)
print("saved_album.album.artists[0].name:", saved_album.album.artists[0].name)

if len(saved_albums) > 1:
    print("saved_albums[1].album.name:", saved_albums[1].album.name)

next_albums = client.next_page(saved_albums)
if next_albums is not None:
    print("next saved_albums page total:", next_albums.total)
    print("next saved_albums[0].album.name:", next_albums[0].album.name)
