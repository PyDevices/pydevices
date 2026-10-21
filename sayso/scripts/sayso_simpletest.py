import os
import sys

# This file lives in the scripts directory but should be run from the parent directory, so we need to add the parent directory to the path
sys.path.insert(0, os.getcwd())
    
from sayso import SpotifyClient

client = SpotifyClient()
me = client.me()
print(me)
