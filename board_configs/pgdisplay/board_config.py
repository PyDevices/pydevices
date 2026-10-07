"""
Board configuration for PyGame.
"""

import sys

if sys.platform == "win32":
    from boarddev import env_get, env_set

    # SDL2's default Windows audio driver (WASAPI) has a compatibility issue
    # with pygame.mixer.Channel's play()/queue() small-chunk playback pattern
    # that produces periodic audible glitches (confirmed: identical PCM output
    # via SDL_AUDIODRIVER=directsound is glitch-free; SDL_QueueAudio-based
    # output, e.g. audiodev.sdl2_audio, is unaffected on Windows either
    # way). DirectSound is SDL2's own supported alternative Windows backend.
    # Must be set here, before PGDisplay's pg.init() below -- SDL locks in its
    # audio driver at the first SDL_InitSubSystem(SDL_INIT_AUDIO), so setting
    # this later in audiodev.pygame_audio (which opens the mixer lazily
    # on first audio_out() use, well after PGDisplay has already called
    # pg.init()) is too late.
    # Only when unset, so an explicit user choice still wins.
    if env_get("SDL_AUDIODRIVER") is None:
        env_set("SDL_AUDIODRIVER", "directsound")

from displaydev.pgdisplay import PGDisplay as DTDisplay

width = 320
height = 480
rotation = 0
scale = 2.0

display_drv = DTDisplay(
    width=width,
    height=height,
    rotation=rotation,
    title=f"{sys.implementation.name} on {sys.platform}",
    scale=scale,
)

host_read = display_drv.get_events

display_drv.fill(0)

from board_peripherals import PERIPHERALS, load_peripherals

load_peripherals(globals())
