from concurrent.futures import CancelledError
import queue
import threading

import pytest

from core.background import BackgroundPool, CancelToken, foreground_activity, foreground_active, model_slot


def test_bounded_workers_deduplicate_and_honor_queue_priority():
    pool = BackgroundPool(workers=1, capacity=2)
    started, release = threading.Event(), threading.Event()
    order = []
    def busy(token):
        started.set()
        assert release.wait(2)
    try:
        first = pool.submit('busy', busy)
        assert started.wait(1)
        assert pool.submit('busy', lambda _: pytest.fail('duplicate')) is first
        low = pool.submit('low', lambda _: order.append('low'), priority=10)
        high = pool.submit('high', lambda _: order.append('high'), priority=1)
        with pytest.raises(queue.Full):
            pool.submit('overflow', lambda _: None)
        release.set()
        first.result(2); high.result(2); low.result(2)
        assert order == ['high', 'low']
    finally:
        release.set()
        pool.shutdown()


def test_foreground_blocks_background_and_shutdown_cancels_waiters():
    pool = BackgroundPool(workers=1)
    waiting = threading.Event()
    def job(token):
        waiting.set()
        with model_slot(background=True):
            return 'ran'
    with foreground_activity():
        assert foreground_active()
        future = pool.submit('model', job)
        assert waiting.wait(1)
        pool.shutdown()
        with pytest.raises(CancelledError):
            future.result(1)
    assert not foreground_active()


def test_foreground_gets_slot_before_waiting_background():
    pool = BackgroundPool(workers=1)
    waiting = threading.Event()
    order = []
    def job(token):
        waiting.set()
        with model_slot(background=True):
            order.append('background')
    try:
        with foreground_activity():
            future = pool.submit('model', job)
            assert waiting.wait(1)
            with model_slot(background=False):
                order.append('foreground')
        future.result(2)
        assert order == ['foreground', 'background']
    finally:
        pool.shutdown()


def test_stream_close_releases_model_slot(monkeypatch):
    from core import models
    class Client:
        def chat(self, **kwargs):
            yield {'message': {'content': 'hello'}}
            yield {'message': {'content': 'world'}}
    monkeypatch.setattr(models, 'ollama', Client())
    stream = models.chat('test', [], stream=True)
    next(stream)
    stream.close()
    assert not foreground_active()
    with model_slot():
        pass


def test_scheduler_waits_for_foreground_and_stops_on_close(tmp_path, monkeypatch):
    import background_tasks as bg
    calls = []
    monkeypatch.setattr(bg, 'process_job', lambda name, root, token: calls.append(name))
    tasks = bg.DaytimeTasks(tmp_path)
    try:
        tasks.next_due = {name: 0 for name in bg.JOBS}
        tasks.tick(foreground=True)
        assert not calls and not tasks.pending
        tasks.tick()
        for future in tasks.pending.values():
            future.result(2)
        assert set(calls) == set(bg.JOBS)
        tasks.tick()
        assert set(tasks.results) == set(bg.JOBS)
        tasks.shutdown()
        assert tasks.closed and all(not thread.is_alive() for thread in tasks.pool.threads)
    finally:
        tasks.shutdown()


def test_process_cancel_kills_and_reaps_child(tmp_path, monkeypatch):
    import background_tasks as bg
    calls = []
    class Process:
        pid = 99
        def poll(self): return None
        def wait(self): calls.append('reaped')
    monkeypatch.setattr(bg.subprocess, 'Popen', lambda *a, **kw: Process())
    monkeypatch.setattr(bg.os, 'killpg', lambda pid, sig: calls.append(pid))
    token = CancelToken()
    token.event.set()
    with pytest.raises(CancelledError):
        bg.process_job('index', tmp_path, token)
    assert calls == [99, 'reaped']


def test_priority_is_shared_with_subprocess(isolated_data_dir):
    import subprocess
    import sys
    code = '''
import sys
from core import config
config._root_override = sys.argv[1]
from core.background import model_slot
print('ready', flush=True)
with model_slot(background=True):
    print('ran', flush=True)
'''
    process = None
    try:
        with foreground_activity():
            process = subprocess.Popen([sys.executable, '-B', '-c', code, str(isolated_data_dir)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert process.stdout.readline().strip() == 'ready'
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=.2)
        output, error = process.communicate(timeout=3)
        assert process.returncode == 0, error
        assert 'ran' in output
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()


def test_failures_dont_kill_workers_and_cancel_callbacks_do_not_deadlock():
    pool = BackgroundPool(workers=1)
    entered = threading.Event()
    def wait(token):
        entered.set()
        while True:
            token.wait(.1)
    try:
        bad = pool.submit('bad', lambda _: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            bad.result(1)
        running = pool.submit('running', wait)
        assert entered.wait(1)
        queued = pool.submit('queued', lambda _: None)
        queued.add_done_callback(lambda _: pool.snapshot())
        pool.cancel('queued')
        assert queued.cancelled()
        pool.cancel('running')
        with pytest.raises(CancelledError):
            running.result(1)
    finally:
        pool.shutdown()


def test_job_errors_and_skips_are_visible_in_status(tmp_path, monkeypatch):
    import background_tasks as bg
    monkeypatch.setattr(bg, 'process_job', lambda name, root, token: (
        {'errors': ['offline']} if name == 'research' else {'outcome': 'skipped'}))
    tasks = bg.DaytimeTasks(tmp_path)
    try:
        tasks.next_due = {name: 0 for name in bg.JOBS}
        tasks.tick()
        for future in tasks.pending.values():
            future.result(2)
        tasks.tick()
        assert tasks.results['research']['status'] == 'error'
        assert tasks.results['index']['status'] == 'skipped'
    finally:
        tasks.shutdown()
