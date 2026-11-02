# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One background thread for blocking calls, shared by every app.

An app hands it work through its scope and gets the answer back on the
main thread::

    def main(scope):
        def done(value, error):
            label.set_text(str(error or value))

        scope.worker.submit(lambda: fetch(url), done, key="fetch")

``work()`` runs on the worker thread. ``done(value, error)`` runs later on
the main thread, at a safe point, with what ``work()`` returned or the
exception it raised. A second job with the same *key* replaces one still
waiting, so a burst of volume taps sends one request.

The thread outlives the apps: starting one per app would leak its stack,
which on a board is scarce internal RAM. When an app closes, what it queued
and hasn't started is dropped, and a job of its that finishes afterwards is
not delivered.

Where there are no threads (the browser, CircuitPython on a board,
MicroPython's Windows port) a :class:`TimerWorker` runs each job on a timer
instead, one per tick, so the screen still gets a turn between jobs.
"""

import sys

import multimer

#: The worker thread's stack on a board, in bytes. A TLS handshake needs
#: about 20 KB; 12 KB overflowed.
STACK = 24 * 1024


def _gone(owner):
    """True once *owner* (an app's scope) has closed or is closing."""
    return bool(getattr(owner, "closed", False) or getattr(owner, "_closing", False))


def _report(exc):
    print("appkit.worker: a done() failed: %r" % (exc,))
    pe = getattr(sys, "print_exception", None)
    if pe is not None:
        pe(exc)


def _call_done(done, owner, value, error):
    if _gone(owner):
        return
    try:
        done(value, error)
    except Exception as exc:
        _report(exc)


class _Base:
    def __init__(self):
        self._jobs = []  # [key, work, done, owner]
        #: True while a job is running, whichever app's it is.
        self.busy = False
        self._key = None  # the running job's key
        #: Jobs run, and jobs whose work() raised.
        self.ran = 0
        self.errors = 0

    def _queue(self, work, done, key, owner):
        if not callable(work):
            raise ValueError("work must be callable")
        if done is not None and not callable(done):
            raise ValueError("done must be callable")
        if key is not None:
            self._jobs = [j for j in self._jobs if j[0] != key or j[3] is not owner]
        self._jobs.append([key, work, done, owner])

    def _run(self, job):
        key, work, done, owner = job
        self._key = key
        self.busy = True
        value = error = None
        try:
            value = work()
        except Exception as exc:
            error = exc
            self.errors += 1
        self.busy = False
        self._key = None
        self.ran += 1
        return done, owner, value, error

    def queued(self, owner=None):
        """How many jobs are waiting; only *owner*'s when given."""
        return len([j for j in self._jobs if owner is None or j[3] is owner])


class Worker(_Base):
    """One background thread that runs jobs in the order they were submitted."""

    def __init__(self, stack=None):
        import _thread

        _Base.__init__(self)
        self._lock = _thread.allocate_lock()
        self._wake = _thread.allocate_lock()
        self._wake.acquire()
        if stack is None and _on_board():
            stack = STACK
        if stack:
            try:
                _thread.stack_size(stack)
            except Exception:
                pass
        try:
            _thread.start_new_thread(self._loop, ())
        finally:
            if stack:
                try:
                    _thread.stack_size(0)
                except Exception:
                    pass

    def submit(self, work, done=None, key=None, owner=None):
        """Run ``work()`` on the thread, then ``done(value, error)`` on the main thread."""
        with self._lock:
            self._queue(work, done, key, owner)
        if self._wake.locked():
            try:
                self._wake.release()
            except RuntimeError:
                pass

    def pending(self, key, owner=None):
        """True while a job with *key* is waiting or running."""
        if self._key is not None and self._key == key:
            return True
        with self._lock:
            return any(j[0] == key and j[3] is owner for j in self._jobs)

    def cancel(self, owner):
        """Drop everything *owner* queued that hasn't started."""
        with self._lock:
            self._jobs = [j for j in self._jobs if j[3] is not owner]

    def _loop(self):
        while True:
            job = None
            with self._lock:
                if self._jobs:
                    job = self._jobs.pop(0)
            if job is None:
                self._wake.acquire()
                continue
            done, owner, value, error = self._run(job)
            job = None
            if done is not None and not _gone(owner):
                _deliver(done, owner, value, error)
            done = owner = value = error = None


def _deliver(done, owner, value, error):
    def run(_):
        _call_done(done, owner, value, error)

    for _ in range(50):
        try:
            multimer.schedule(run, None)
            return
        except RuntimeError:
            # The schedule queue is full; it drains fast.
            import time

            sleep_ms = getattr(time, "sleep_ms", None)
            if sleep_ms is not None:
                sleep_ms(10)
            else:
                time.sleep(0.01)
    print("appkit.worker: dropped a done(): the schedule queue stayed full")


class TimerWorker(_Base):
    """The worker where there are no threads: each job runs on a timer, on
    the main thread, one per tick."""

    def __init__(self):
        _Base.__init__(self)
        self._timer = None

    def submit(self, work, done=None, key=None, owner=None):
        """Run ``work()`` soon on a timer, then ``done(value, error)``."""
        self._queue(work, done, key, owner)
        self._kick()

    def pending(self, key, owner=None):
        if self._key is not None and self._key == key:
            return True
        return any(j[0] == key and j[3] is owner for j in self._jobs)

    def cancel(self, owner):
        self._jobs = [j for j in self._jobs if j[3] is not owner]

    def _kick(self):
        t = self._timer
        if t is None or not t.running:
            self._timer = multimer.after(1, self._step, name="appkit.worker")

    def _step(self, timer):
        self._timer = None
        if not self._jobs:
            return
        job = self._jobs.pop(0)
        done, owner, value, error = self._run(job)
        job = None
        if done is not None:
            _call_done(done, owner, value, error)
        done = owner = value = error = None
        if self._jobs:
            self._kick()


class ScopedWorker:
    """The shared worker as one app sees it: its jobs are its scope's, and
    are dropped when the scope closes. This is ``scope.worker``."""

    def __init__(self, worker, owner):
        self.worker = worker
        self.owner = owner

    @property
    def busy(self):
        """True while the shared thread is running a job, this app's or
        another's: say, before closing a connection a job may be using."""
        return self.worker.busy

    def submit(self, work, done=None, key=None):
        """Run ``work()`` in the background, then ``done(value, error)`` on the main thread."""
        if _gone(self.owner):
            raise RuntimeError("scope %r is closed" % (getattr(self.owner, "name", None),))
        self.worker.submit(work, done, key=key, owner=self.owner)

    def pending(self, key):
        """True while this app's job with *key* is waiting or running."""
        return self.worker.pending(key, self.owner)

    def queued(self):
        """How many of this app's jobs are waiting."""
        return self.worker.queued(self.owner)

    def cancel(self):
        """Drop every job this app queued that hasn't started."""
        self.worker.cancel(self.owner)


def _on_board():
    from .data import desktop

    return not desktop()


def threads():
    """True where this interpreter can start a thread."""
    try:
        import _thread  # noqa: F401
    except ImportError:
        return False
    return True


_shared = None


def shared():
    """The program's one worker, started on first use: a :class:`Worker`
    where there are threads, a :class:`TimerWorker` where there aren't."""
    global _shared
    if _shared is None:
        _shared = Worker() if threads() else TimerWorker()
    return _shared
