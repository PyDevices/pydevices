import os
import sys

# This file lives in the scripts directory but should be run from the sayso folder, so lib/ (which holds the package) goes on the path
sys.path.insert(0, os.path.join(os.getcwd(), "lib"))
    
from sayso import SpotifyClient

client = SpotifyClient()
me = client.me()
print(me)
