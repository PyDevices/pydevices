import os
import sys
import termios
import tty

sys.path.insert(0, os.getcwd())

from sayso import SpotifyClient


DEFAULT_TRACK_URI = "spotify:track:11dFghVXANMlKmJXsNCbNl"
SEEK_MS = 30000
VOLUME_STEP = 10


class PlaybackControls:
    def __init__(self, client):
        self.client = client
        self.repeat_states = ("off", "track", "context")
        self.repeat_index = 0
        self.shuffle_on = False
        self.volume = 50
        self._device_list = list(client.devices())
        self.device_index = 0

    def play(self):
        return self.client.play()

    def pause(self):
        return self.client.pause()

    def next_track(self):
        return self.client.next_track()

    def previous_track(self):
        return self.client.previous_track()

    def seek_start(self):
        return self.client.seek(0)

    def seek_forward(self):
        return self.client.seek(SEEK_MS)

    def cycle_repeat(self):
        self.repeat_index = (self.repeat_index + 1) % len(self.repeat_states)
        state = self.repeat_states[self.repeat_index]
        return self.client.repeat(state)

    def toggle_shuffle(self):
        self.shuffle_on = not self.shuffle_on
        return self.client.shuffle(self.shuffle_on)

    def volume_up(self):
        self.volume = min(100, self.volume + VOLUME_STEP)
        return self.client.volume(self.volume)

    def volume_down(self):
        self.volume = max(0, self.volume - VOLUME_STEP)
        return self.client.volume(self.volume)

    def transfer_next_device(self):
        if not self._device_list:
            self._device_list = list(self.client.devices())
        if not self._device_list:
            raise RuntimeError("No playback devices available")

        self.device_index = (self.device_index + 1) % len(self._device_list)
        device = self._device_list[self.device_index]
        return self.client.transfer_playback([device.id], play=True)

    def play_sample_track(self):
        return self.client.play(uris=[DEFAULT_TRACK_URI])

    def add_sample_to_queue(self):
        return self.client.add_to_queue(DEFAULT_TRACK_URI)

    def current_playback(self):
        return self.client.current_playback()

    def currently_playing(self):
        return self.client.currently_playing()

    def queue(self):
        return self.client.queue()

    def devices(self):
        self._device_list = list(self.client.devices())
        return self._device_list

    def me(self):
        return self.client.me()

    def available_markets(self):
        return self.client.available_markets()

    def recommendation_genres(self):
        return self.client.recommendation_genres()

    def recently_played(self):
        return self.client.recently_played()

    def current_user_playlists(self):
        return self.client.current_user_playlists()

    def saved_albums(self):
        return self.client.saved_albums()

    def saved_tracks(self):
        return self.client.saved_tracks()

    def saved_episodes(self):
        return self.client.saved_episodes()

    def saved_shows(self):
        return self.client.saved_shows()

    def saved_audiobooks(self):
        return self.client.saved_audiobooks()

    def followed_artists(self):
        return self.client.followed_artists()

    def top_artists(self):
        return self.client.top_artists()

    def top_tracks(self):
        return self.client.top_tracks()

    def categories(self):
        return self.client.categories()

    def featured_playlists(self):
        return self.client.featured_playlists()

    def new_releases(self):
        return self.client.new_releases()


def control_table(controls):
    rows = []
    for key, label, _handler in controls:
        rows.append((key, label))
    key_width = max(len(row[0]) for row in rows)
    label_width = max(len(row[1]) for row in rows)
    for key, label in rows:
        print("  {}  {}".format(key.ljust(key_width), label.ljust(label_width)))


def build_controls(demo):
    return (
        ("p", "play()", demo.play),
        ("x", "pause()", demo.pause),
        ("n", "next_track()", demo.next_track),
        ("b", "previous_track()", demo.previous_track),
        ("[", "seek(0)", demo.seek_start),
        ("]", "seek({})".format(SEEK_MS), demo.seek_forward),
        ("r", "cycle repeat()", demo.cycle_repeat),
        ("s", "toggle shuffle()", demo.toggle_shuffle),
        ("+", "volume up", demo.volume_up),
        ("-", "volume down", demo.volume_down),
        ("t", "transfer_playback(next device)", demo.transfer_next_device),
        ("1", "play(sample track)", demo.play_sample_track),
        ("a", "add_to_queue(sample track)", demo.add_sample_to_queue),
        ("c", "current_playback()", demo.current_playback),
        ("y", "currently_playing()", demo.currently_playing),
        ("w", "queue()", demo.queue),
        ("v", "devices()", demo.devices),
        ("m", "me()", demo.me),
        ("k", "available_markets()", demo.available_markets),
        ("g", "recommendation_genres()", demo.recommendation_genres),
        ("h", "recently_played()", demo.recently_played),
        ("e", "current_user_playlists()", demo.current_user_playlists),
        ("l", "reprint key list", None),
        ("2", "saved_albums()", demo.saved_albums),
        ("3", "saved_tracks()", demo.saved_tracks),
        ("4", "saved_episodes()", demo.saved_episodes),
        ("5", "saved_shows()", demo.saved_shows),
        ("6", "saved_audiobooks()", demo.saved_audiobooks),
        ("f", "followed_artists()", demo.followed_artists),
        ("i", "top_artists()", demo.top_artists),
        ("j", "top_tracks()", demo.top_tracks),
        ("u", "categories()", demo.categories),
        ("o", "featured_playlists()", demo.featured_playlists),
        ("z", "new_releases()", demo.new_releases),
        ("Q", "quit", None),
    )


def read_key():
    if not sys.stdin.isatty():
        raise SystemExit("Playback controls require an interactive terminal.")

    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def print_result(result):
    if result is None:
        print("  result: None")
        return

    if isinstance(result, (list, tuple)):
        if not result:
            print("  result: ()")
            return
        print("  result:")
        for item in result:
            print(item)
        return

    print("  result:")
    print(result)


def run_control(label, handler):
    print()
    print("-> {}".format(label))
    try:
        result = handler()
    except Exception as error:
        print("  error:", error)
        return

    print_result(result)


def main():
    client = SpotifyClient()
    demo = PlaybackControls(client)
    controls = build_controls(demo)
    controls_by_key = {key: (label, handler) for key, label, handler in controls}

    print("Spotify playback controls")
    print("Press a key to call the matching SpotifyClient method.")
    print()
    control_table(controls)
    print()
    print("Waiting for keys. Press Q to exit.")

    while True:
        key = read_key()
        print()
        print("key:", repr(key))

        if key == "Q":
            print("exit")
            break

        if key == "l":
            print()
            control_table(controls)
            print()
            print("Waiting for keys. Press Q to exit.")
            continue

        if key not in controls_by_key:
            print("unknown key")
            continue

        label, handler = controls_by_key[key]
        if handler is None:
            print("exit")
            break

        run_control(label, handler)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("exit")
