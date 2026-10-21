import os
import sys

sys.path.insert(0, os.getcwd())

from sayso import SpotifyClient

client = SpotifyClient()
me = client.me()
print("me.display_name:", me.display_name)

saved_tracks = client.saved_tracks(limit=1)
if len(saved_tracks) == 0:
    raise SystemExit("No saved tracks found")

album = saved_tracks[0].track.album
print("album.name:", album.name)
print("album.artists[0].name:", album.artists[0].name)

images = album.images
if images:
    print("album.images[0].url:", images[0].url)

tracks = album.tracks
print("album.tracks.total:", tracks.total)
print("album.tracks[0].name:", tracks[0].name)
if tracks.total is not None and tracks.total > 1:
    print("album.tracks[1].name:", tracks[1].name)

print("album.release_date:", album.release_date)
print("album.label:", album.label)
print("album.popularity:", album.popularity)
print("album.genres:", album.genres)

copyrights = album.copyrights
if copyrights:
    print("album.copyrights[0].text:", copyrights[0].text)

external_ids = album.external_ids
if external_ids is not None:
    print("album.external_ids.upc:", external_ids.upc)
