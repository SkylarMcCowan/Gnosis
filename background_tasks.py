"""App-owned daytime jobs. No daemon is installed; the GUI owns every worker."""
from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from core.background import BackgroundPool
from core.knowledge_maintenance import atomic_json, read_json

ROOT = Path(__file__).resolve().parent
JOBS = {'discover': 300, 'index': 900, 'research': 1800}


def run_job(name, root):
    from core import config
    config._root_override = str(root)
    from core.autonomous_research import discover_gaps, run_research
    from core.knowledge_maintenance import maintain_knowledge
    if name == 'discover':
        return {'queued': discover_gaps(root)}
    from nightly import cycle_lock
    try:
        with cycle_lock(root):
            if name == 'index':
                return maintain_knowledge(root)
            if name == 'research':
                result = run_research(root, batch_size=1)
                if result.get('saved_sources'):
                    maintain_knowledge(root)
                return result
    except BlockingIOError:
        return {'outcome': 'skipped', 'reason': 'Maintenance already running'}
    raise ValueError(name)


def process_job(name, root, token, timeout=360):
    root = Path(root)
    log = root / 'knowledge_state/background_logs' / (name + '.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as stream:
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'background_tasks.py'), name, str(root)],
                                   cwd=root, stdout=stream, stderr=stream, start_new_session=True,
                                   env={**os.environ, 'GNOSIS_BACKGROUND': '1'})
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                token.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'{name} exceeded {timeout}s')
                token.wait(.1)
            token.check()
            if process.returncode:
                raise RuntimeError(f'{name} failed; see {log}')
            return read_json(root / 'knowledge_state/background_results' / (name + '.json'), {})
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


class DaytimeTasks:
    def __init__(self, root):
        self.root = Path(root)
        self.pool = BackgroundPool(workers=3)
        now = time.monotonic()
        self.next_due = {name: now + delay for name, delay in [('discover', 30), ('index', 60), ('research', 120)]}
        self.pending = {}
        self.results = {}
        self.closed = False
        self.paused = False

    def tick(self, foreground=False):
        """Called by a GUI timer: no model, network, or blocking waits here."""
        if self.closed:
            return
        now = time.monotonic()
        for name, future in list(self.pending.items()):
            if not future.done():
                continue
            try:
                result = future.result()
                status = 'completed'
                if isinstance(result, dict):
                    if result.get('errors'):
                        status = 'error'
                    elif result.get('outcome') == 'skipped':
                        status = 'skipped'
                self.results[name] = {'status': status, 'result': result}
            except CancelledError:
                self.results[name] = {'status': 'cancelled'}
            except Exception as error:
                self.results[name] = {'status': 'error', 'error': str(error)}
            del self.pending[name]
        if self.paused or foreground:
            return
        for name, interval in JOBS.items():
            if now >= self.next_due[name] and name not in self.pending:
                self.pending[name] = self.pool.submit(name, lambda token, name=name: process_job(name, self.root, token))
                self.next_due[name] = now + interval

    def pause(self, paused):
        self.paused = paused
        if paused:
            for key in self.pool.snapshot():
                self.pool.cancel(key)

    def snapshot(self):
        return {'paused': self.paused, 'active': self.pool.snapshot(), 'recent': dict(self.results)}

    def shutdown(self):
        self.closed = True
        self.pool.shutdown()


if __name__ == '__main__':
    name, root = sys.argv[1], Path(sys.argv[2])
    if name not in JOBS:
        raise SystemExit('Unknown background task')
    result = run_job(name, root)
    atomic_json(root / 'knowledge_state/background_results' / (name + '.json'), result)
    print(json.dumps(result))
