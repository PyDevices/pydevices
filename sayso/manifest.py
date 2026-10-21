# MicroPython manifest: freeze sayso and the spotify_remote app.
#
# Every .py in both packages. A firmware that includes this runs the remote
# with no files but its config:
#   micropython -m spotify_remote [speaker-name]
# from a directory holding sayso.local.json and tokens.json (see
# apps/spotify_remote/README.md).
package("sayso")
package("spotify_remote", base_path="apps")
