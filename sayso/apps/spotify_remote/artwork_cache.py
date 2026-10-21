import os

from sayso.transport import get_bytes

# In-memory caches publish "mem:<hash>" in place of a file path; image_view
# resolves those here. Shared across caches: the hash is of the URL.
MEMORY_PREFIX = "mem:"
_memory = {}


def memory_bytes(path):
    """The bytes behind a "mem:" path, or None once evicted."""
    return _memory.get(path[len(MEMORY_PREFIX):])


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _mkdir(path):
    if _exists(path):
        return
    os.mkdir(path)


def _simple_hash(value):
    result = 2166136261
    for char in value:
        result ^= ord(char)
        result = (result * 16777619) & 0xFFFFFFFF
    return "{:08x}".format(result)


def _extension_from_url(url):
    path = url.split("?", 1)[0].rsplit("/", 1)[-1].lower()
    if "." in path:
        ext = path.rsplit(".", 1)[-1]
        if ext in ("jpg", "jpeg", "png", "bmp"):
            if ext == "jpeg":
                return "jpg"
            return ext
    return "jpg"


def _extension_from_bytes(data, fallback):
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"BM"):
        return "bmp"
    return fallback


class ArtworkCache:
    """Downloaded images, by URL: files in a directory, or held in memory.

    ``memory_bytes`` > 0 keeps them in RAM instead, oldest out first once the
    total passes that many bytes. On an ESP32-S3 with an RGB panel that is the
    right place: a flash write stalls the cache that PSRAM, the panel refill
    and Wi-Fi all run through, and every file lookup cost ~30 ms of flash
    reads on the UI thread, several per thumbnail (2026-09-25).
    """

    def __init__(self, directory, max_items=24, memory_bytes=0):
        self.directory = directory
        self.max_items = max_items
        self.memory_budget = memory_bytes
        self._order = []  # memory mode: hashes, oldest first
        self._size = 0
        if self.max_items and not self.memory_budget:
            self._trim_cache()

    def path_for_url(self, url):
        if not url:
            return None
        path = self.cached_path(url)
        if path:
            return path
        if self.memory_budget:
            return self._fetch_to_memory(url, _simple_hash(url))
        return self._download(url, _simple_hash(url), _extension_from_url(url))

    def cached_path(self, url):
        """Return the cached file for url, or None; never downloads."""
        if not url:
            return None
        base = _simple_hash(url)
        if self.memory_budget:
            if base in _memory:
                if base in self._order:
                    self._order.remove(base)
                    self._order.append(base)
                return MEMORY_PREFIX + base
            return None
        for ext in ("jpg", "png", "bmp", _extension_from_url(url)):
            path = self._cache_path(base, ext)
            if _exists(path):
                return path
        return None

    def _fetch_to_memory(self, url, base):
        data = get_bytes(url, base_url="")
        _memory[base] = data
        self._order.append(base)
        self._size += len(data)
        while self._size > self.memory_budget and len(self._order) > 1:
            old = self._order.pop(0)
            gone = _memory.pop(old, None)
            if gone is not None:
                self._size -= len(gone)
        return MEMORY_PREFIX + base

    def _download(self, url, base, fallback_ext):
        _mkdir(self.directory)
        data = get_bytes(url, base_url="")
        ext = _extension_from_bytes(data, fallback_ext)
        path = self._cache_path(base, ext)
        tmp_path = path + ".tmp"

        with open(tmp_path, "wb") as file:
            file.write(data)

        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(tmp_path, path)
        self._trim_cache()
        return path

    def _cache_path(self, base, ext):
        return self.directory + "/" + base + "." + ext

    def _cached_files(self):
        if not _exists(self.directory):
            return []

        files = []
        for name in os.listdir(self.directory):
            if name.endswith(".tmp"):
                continue
            path = self.directory + "/" + name
            try:
                mtime = os.stat(path)[8]
            except OSError:
                continue
            files.append((mtime, path))
        return files

    def _trim_cache(self):
        if not self.max_items:
            return

        files = self._cached_files()
        overflow = len(files) - self.max_items
        if overflow <= 0:
            return

        files.sort()
        for mtime, path in files[:overflow]:
            try:
                os.remove(path)
            except OSError:
                pass
