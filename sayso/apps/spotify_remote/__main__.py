"""`micropython -m spotify_remote [speaker-name]`: run the remote.

Frozen into a firmware (see the repo's manifest.py) this needs no files but
sayso.local.json and tokens.json in the directory it is run from.
"""

from spotify_remote import main  # noqa: F401 -- main.py builds the app on import

# Run as a script, appdev keeps the app alive after the script ends. Under
# -m (or -c) it deliberately does not -- that is how test runners start -- so
# this entry point runs the loop itself.
from display_driver import app

app.run()
