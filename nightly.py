#!/usr/bin/env python3
"""Idle-aware nightly worker. Each stage gets a separate process and time budget."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import sys

from core.knowledge_maintenance import atomic_json, read_json

ROOT = Path(__file__).resolve().parent
LABEL = 'com.gnosis.nightly'
STAGES = [('knowledge', 600), ('historian', 1200), ('research', 600), ('study', 600),
          ('index', 600), ('selfimprove', 900), ('tools', 600)]


@contextmanager
def cycle_lock(root):
    path = Path(root) / 'knowledge_state' / 'nightly.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def due_date(now):
    return (now - timedelta(hours=2)).date().isoformat()


def idle_seconds():
    result = subprocess.run(['/usr/sbin/ioreg', '-c', 'IOHIDSystem'], capture_output=True, text=True, timeout=10)
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', result.stdout)
    if result.returncode or not match:
        raise RuntimeError('Cannot determine user inactivity; deferring maintenance')
    return int(match.group(1)) / 1_000_000_000


def launch_agent(root=ROOT):
    root = Path(root)
    return {'Label': LABEL,
            'ProgramArguments': [str(root / 'venv/bin/python'), '-B', str(root / 'nightly.py')],
            'WorkingDirectory': str(root), 'RunAtLoad': True,
            'StartCalendarInterval': {'Hour': 2, 'Minute': 0}, 'StartInterval': 900,
            'ProcessType': 'Background', 'Nice': 10,
            'EnvironmentVariables': {'PYTHONUNBUFFERED': '1'},
            'StandardOutPath': str(root / 'cron/logs/nightly-launchd.log'),
            'StandardErrorPath': str(root / 'cron/logs/nightly-launchd.log')}


def run_stage(name, root=ROOT):
    from core import config
    config._root_override = str(root)
    from core.knowledge_maintenance import maintain_knowledge, learn_from_sources
    if name in ('knowledge', 'index'):
        return maintain_knowledge(root)
    if name == 'research':
        from core.autonomous_research import run_research
        result = run_research(root)
        if result.get('errors'):
            raise RuntimeError(json.dumps(result))
        return result
    if name == 'study':
        maintain_knowledge(root)
        result = learn_from_sources(root)
        if any(item.get('kind') == 'execution' for item in result['failures']):
            raise RuntimeError(json.dumps(result))
        return result
    import webagent
    if name == 'historian':
        return webagent.historian()
    if name == 'selfimprove':
        report = webagent.run_self_improve_cycle()[1]
        return {'outcome': 'skipped' if 'Skipped:' in report or 'No change made:' in report else 'completed',
                'report': report}
    if name == 'tools':
        report = webagent.run_tool_generation_cycle(
            webagent._selfimprove_coding_chat, str(root),
            [(tool.name, tool.description) for tool in webagent.tool_registry.list()], agent='self-improve')
        return {'outcome': 'skipped' if report.startswith('No recurring') else 'completed', 'report': report}
    raise ValueError(name)


def execute_stage(name, timeout, root):
    log = Path(root) / 'cron/logs' / f'nightly-{name}.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as stream:
        stream.write(f'\n--- {datetime.now().isoformat()} ---\n')
        stream.flush()
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'nightly.py'), '--stage', name,
                                    '--root', str(root)], cwd=root, stdout=stream, stderr=stream,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            details = read_json(Path(root) / 'knowledge_state/stage_results' / (name + '.json'), {}) if code == 0 else {}
            status = 'skipped' if details.get('outcome') == 'skipped' else 'success'
            return {'status': status if code == 0 else 'error', 'exit_code': code, 'log': str(log), 'details': details}
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return {'status': 'timeout', 'log': str(log)}


def run_due(root=ROOT, force=False, now=None, idle=None, execute=execute_stage):
    root, now = Path(root), now or datetime.now()
    state_path = root / 'knowledge_state/nightly.json'
    try:
        with cycle_lock(root):
            day = due_date(now)
            state = read_json(state_path, {})
            if not force:
                if state.get('cycle_date') == day:
                    if state.get('status') == 'success':
                        return 'Already completed this maintenance night.'
                    if state.get('attempts', 0) >= 3:
                        return 'Retry limit reached; see knowledge_state/nightly.json.'
                    last = state.get('started_at')
                    if last and (now - datetime.fromisoformat(last)).total_seconds() < 3600:
                        return 'Waiting for retry interval.'
                seconds = idle_seconds() if idle is None else idle
                if seconds < 900:
                    return 'Deferred: waiting for 15 minutes of user inactivity.'
            if force or state.get('cycle_date') != day:
                state = {'cycle_date': day, 'attempts': 0, 'stages': {}}
            state.update(status='running', started_at=now.isoformat(), attempts=state['attempts'] + 1)
            atomic_json(state_path, state)
            for name, timeout in STAGES:
                # Always refresh after study or historian retries change the sources.
                if name != 'index' and state['stages'].get(name, {}).get('status') in ('success', 'skipped'):
                    continue
                try:
                    state['stages'][name] = execute(name, timeout, root)
                except Exception as error:
                    state['stages'][name] = {'status': 'error', 'error': str(error)}
                atomic_json(state_path, state)
            state['status'] = ('success' if all(item['status'] in ('success', 'skipped') for item in state['stages'].values())
                               else 'partial_failure')
            state['finished_at'] = datetime.now().isoformat()
            atomic_json(state_path, state)
            tasks_path = root / 'cron/tasks.json'
            tasks = read_json(tasks_path, {})
            for task in tasks.values():
                if task.get('scheduler') == 'launchd' and task.get('launch_agent') == LABEL:
                    task.update(last_run=state['finished_at'], last_status=state['status'])
            if tasks:
                atomic_json(tasks_path, tasks)
            report = root / 'knowledge_base/overnight_reports' / f'nightly_{day}.md'
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text('# Nightly learning — ' + day + '\n\n' + state['status'] + '\n\n'
                              + '\n'.join(f"- {name}: {item['status']} — {item.get('log', item.get('error', ''))}"
                                          for name, item in state['stages'].items())
                              + '\n\nKnowledge details: knowledge_state/last_maintenance.json\n'
                                'Study details: knowledge_state/learning.json\n'
                                'Research details: knowledge_state/research_report.json\n', encoding='utf-8')
            return json.dumps(state, indent=2)
    except BlockingIOError:
        return 'Another overnight cycle is already running.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=[name for name, _ in STAGES])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--force', action='store_true', help='Run now, bypassing idle and daily gates')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--research-status', action='store_true')
    parser.add_argument('--research-preview', action='store_true')
    parser.add_argument('--write-plist', type=Path)
    args = parser.parse_args()
    if args.write_plist:
        args.write_plist.write_bytes(plistlib.dumps(launch_agent(args.root)))
    elif args.research_preview:
        from core.autonomous_research import preview_research
        print(json.dumps(preview_research(args.root), indent=2))
    elif args.research_status:
        print(json.dumps(read_json(args.root / 'knowledge_state/research_queue.json', {'gaps': {}}), indent=2))
    elif args.status:
        print(json.dumps(read_json(args.root / 'knowledge_state/nightly.json', {}), indent=2))
    elif args.stage:
        result = run_stage(args.stage, args.root)
        atomic_json(args.root / 'knowledge_state/stage_results' / (args.stage + '.json'),
                    result if isinstance(result, dict) else {'report': result})
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(run_due(args.root, force=args.force))


if __name__ == '__main__':
    main()
