"""Bounded application workers and cooperative foreground inference priority."""
from concurrent.futures import Future, CancelledError
from contextlib import contextmanager
import fcntl
import itertools
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from core import config

_local = threading.local()


class CancelToken:
    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            raise CancelledError('Background task cancelled')

    def wait(self, seconds):
        self.event.wait(seconds)
        self.check()


def runtime_dir():
    path = Path(config.project_root()) / 'knowledge_state/runtime'
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def foreground_activity():
    """Held file locks survive arbitrary-length voice sessions, not process crashes."""
    directory = runtime_dir() / 'foreground'
    directory.mkdir(exist_ok=True)
    path = directory / uuid.uuid4().hex
    temporary = runtime_dir() / ('.foreground-' + path.name)
    with temporary.open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        os.replace(temporary, path)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def foreground_active():
    directory = runtime_dir() / 'foreground'
    if not directory.exists():
        return False
    for path in directory.iterdir():
        try:
            with path.open('r') as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                # Unlocked markers belong to a terminated process. No PID reuse issue.
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    return False


@contextmanager
def background_work(token=None):
    previous = getattr(_local, 'token', None)
    _local.token = token or CancelToken()
    try:
        yield
    finally:
        _local.token = previous


@contextmanager
def model_slot(check=None, background=None):
    """Serialize local inference across GUI, workers and nightly subprocesses.

    Foreground callers jump ahead of queued background callers. An in-flight
    Ollama request is not forcibly preempted; its existing timeout still applies.
    """
    token = getattr(_local, 'token', None)
    if background is None:
        background = token is not None or os.getenv('GNOSIS_BACKGROUND') == '1'
    caller_check = check
    def check():
        if token:
            token.check()
        if caller_check:
            caller_check()
    marker = None if background else foreground_activity()
    if marker:
        marker.__enter__()
    try:
        with (runtime_dir() / 'inference.lock').open('a') as handle:
            while True:
                check()
                if background and foreground_active():
                    time.sleep(.05)
                    continue
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    time.sleep(.05)
                    continue
                if background and foreground_active():
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    continue
                break
            try:
                check()
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        if marker:
            marker.__exit__(None, None, None)


class BackgroundPool:
    """Three reusable daemon workers; bounded queue, keyed dedupe, cooperative stop.

    Jobs receive a CancelToken and must use it while waiting. Worker callbacks
    never touch Qt widgets. Futures carry results/errors back to callers.
    """
    def __init__(self, workers=3, capacity=24):
        self.queue = queue.PriorityQueue(maxsize=capacity)
        self.lock = threading.Lock()
        self.jobs = {}
        self.closed = False
        self.counter = itertools.count()
        self.threads = [threading.Thread(target=self._work, name=f'gnosis-background-{i}', daemon=True)
                        for i in range(workers)]
        for thread in self.threads:
            thread.start()

    def submit(self, key, function, priority=10):
        with self.lock:
            if self.closed:
                raise RuntimeError('Background pool is closed')
            if key in self.jobs:
                return self.jobs[key][0]
            future, token = Future(), CancelToken()
            self.queue.put_nowait((priority, next(self.counter), key, function, future, token))
            self.jobs[key] = (future, token)
            return future

    def cancel(self, key):
        with self.lock:
            job = self.jobs.get(key)
        if job:
            job[1].event.set()
            job[0].cancel()

    def _work(self):
        while True:
            try:
                _, _, key, function, future, token = self.queue.get(timeout=.1)
            except queue.Empty:
                if self.closed:
                    return
                continue
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        token.check()
                        with background_work(token):
                            result = function(token)
                        future.set_result(result)
                    except BaseException as error:
                        future.set_exception(error)
            finally:
                with self.lock:
                    if self.jobs.get(key, (None,))[0] is future:
                        del self.jobs[key]
                self.queue.task_done()

    def snapshot(self):
        with self.lock:
            return {key: 'running' if f.running() else 'queued' for key, (f, _) in self.jobs.items()}

    def shutdown(self, timeout=1):
        with self.lock:
            self.closed = True
            jobs = list(self.jobs.values())
        for future, token in jobs:
            token.event.set()
            future.cancel()
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
