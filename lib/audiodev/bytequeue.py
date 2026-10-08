"""A byte FIFO for PCM waiting between a writer and a device, kept in small chunks.

The host and browser backends buffer PCM between ``write()`` and the device.
A bytearray grown at the back and cut at the front needs one contiguous block
the size of everything pending each time it grows, about a megabyte at
44.1 kHz stereo, and on a MicroPython heap shared with a UI there is
sometimes no such block: ``MemoryError`` in the middle of playback.

``ByteQueue`` holds the same bytes in fixed-size chunks, so the largest block
it ever asks for is one chunk, and it only holds as many chunks as there are
bytes pending (plus a few spares it reuses). ``limit`` caps what it accepts.

It is not thread-safe: one writer and one reader on the same thread, or a
caller-held lock.
"""

CHUNK = 8192
_SPARES = 4


class ByteQueue:
    def __init__(self, limit=None, chunk=CHUNK):
        self.limit = None if limit is None else max(1, int(limit))
        self._size = max(16, int(chunk))
        self._chunks = []  # bytearrays; the data runs from _head in the first
        self._spare = []
        self._head = 0
        self._len = 0

    def __len__(self):
        return self._len

    def __bool__(self):
        return self._len > 0

    def free(self):
        """Bytes that can still be written (a large number when unlimited)."""
        if self.limit is None:
            return 1 << 30
        return self.limit - self._len

    def clear(self):
        while self._chunks:
            self._release(self._chunks.pop())
        self._head = 0
        self._len = 0

    def _new(self):
        return self._spare.pop() if self._spare else bytearray(self._size)

    def _release(self, chunk):
        if len(self._spare) < _SPARES:
            self._spare.append(chunk)

    def write(self, data):
        """Append as much of ``data`` as fits; return how many bytes were taken."""
        src = memoryview(data)
        count = min(len(src), self.free())
        done = 0
        size = self._size
        while done < count:
            end = self._head + self._len
            used = end - (len(self._chunks) - 1) * size if self._chunks else size
            if used >= size:
                self._chunks.append(self._new())
                used = 0
            n = min(size - used, count - done)
            self._chunks[-1][used : used + n] = src[done : done + n]
            done += n
            self._len += n
        return count

    def unread(self, data):
        """Put ``data`` back at the front, ahead of what is queued.

        Takes as much as fits, keeping the newest end of ``data``. Returns how
        many bytes were taken.
        """
        src = memoryview(data)
        count = min(len(src), self.free())
        done = 0
        while done < count:
            if self._head == 0 or not self._chunks:
                self._chunks.insert(0, self._new())
                self._head = self._size
            n = min(self._head, count - done)
            stop = len(src) - done
            self._chunks[0][self._head - n : self._head] = src[stop - n : stop]
            self._head -= n
            self._len += n
            done += n
        return count

    def peek(self, count):
        """A view of up to ``count`` of the oldest bytes, without consuming them.

        Never copies, so it may be shorter than ``count`` where the bytes run
        on into the next chunk. Valid until the next change to the queue.
        """
        if not self._chunks:
            return memoryview(b"")
        n = min(int(count), self._len, self._size - self._head)
        return memoryview(self._chunks[0])[self._head : self._head + max(0, n)]

    def consume(self, count):
        """Drop up to ``count`` of the oldest bytes; return how many were dropped."""
        count = min(max(0, int(count)), self._len)
        self._len -= count
        self._head += count
        while self._chunks and (self._head >= self._size or not self._len):
            if not self._len:
                self.clear()
                break
            self._release(self._chunks.pop(0))
            self._head -= self._size
        return count

    def copy_into(self, buf, count=None, skip=0):
        """Copy up to ``count`` (default ``len(buf)``) queued bytes into ``buf``.

        Starts ``skip`` bytes after the oldest. Leaves them queued; returns how
        many were copied.
        """
        dst = memoryview(buf)
        skip = min(max(0, int(skip)), self._len)
        want = min(len(dst) if count is None else int(count), len(dst), self._len - skip)
        if want <= 0:
            return 0
        size = self._size
        pos = self._head + skip
        index = pos // size
        offset = pos % size
        done = 0
        while done < want:
            n = min(size - offset, want - done)
            dst[done : done + n] = memoryview(self._chunks[index])[offset : offset + n]
            done += n
            index += 1
            offset = 0
        return want

    def head(self, count):
        """A copy of up to ``count`` of the oldest bytes, as bytes; they stay queued."""
        out = bytearray(min(max(0, int(count)), self._len))
        self.copy_into(out)
        return bytes(out)

    def tail(self, count):
        """A copy of up to ``count`` of the newest bytes, as bytes; they stay queued."""
        count = min(max(0, int(count)), self._len)
        out = bytearray(count)
        self.copy_into(out, skip=self._len - count)
        return bytes(out)

    def push(self, data):
        """Append ``data``, dropping the oldest bytes to make room: a rolling window.

        Needs a ``limit``.
        """
        src = memoryview(data)
        if len(src) >= self.limit:
            self.clear()
            return self.write(src[len(src) - self.limit :])
        over = len(src) - self.free()
        if over > 0:
            self.consume(over)
        return self.write(src)

    def readinto(self, buf, count=None):
        """Move up to ``count`` (default ``len(buf)``) of the oldest bytes into ``buf``."""
        return self.consume(self.copy_into(buf, count))

    def take(self, count):
        """Remove and return up to ``count`` of the oldest bytes, in a new bytearray."""
        out = bytearray(min(max(0, int(count)), self._len))
        self.readinto(out)
        return out
