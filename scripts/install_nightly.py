#!/usr/bin/env python3
"""Install the Gnosis LaunchAgent and migrate only its old overnight cron job."""
from datetime import datetime
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nightly import LABEL, launch_agent
from core.knowledge_maintenance import atomic_json, read_json


def remove_overnight_entries(text, task_ids):
    lines, kept, i = text.splitlines(keepends=True), [], 0
    while i < len(lines):
        line = lines[i]
        if any(line.startswith('# gnosis:' + task_id + ' ') for task_id in task_ids):
            if i + 1 < len(lines) and any('--cron-task ' + task_id in lines[i + 1] for task_id in task_ids):
                i += 2
                continue
        kept.append(line)
        i += 1
    return ''.join(kept)


def main():
    tasks_path = ROOT / 'cron/tasks.json'
    tasks = read_json(tasks_path, {})
    task_ids = {key for key, task in tasks.items() if task.get('action_type') == 'feature'
                and task.get('action_payload') == 'overnight'}
    current = subprocess.run(['/usr/bin/crontab', '-l'], capture_output=True, text=True)
    if current.returncode and 'no crontab' not in current.stderr.lower():
        raise RuntimeError('Cannot read existing crontab: ' + current.stderr)
    original = current.stdout
    updated = remove_overnight_entries(original, task_ids)
    backup = ROOT / 'cron/backups' / ('nightly_migration_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(parents=True)
    (backup / 'crontab').write_text(original)
    (backup / 'tasks.json').write_bytes(tasks_path.read_bytes())
    target = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        (backup / target.name).write_bytes(target.read_bytes())
    (ROOT / 'cron/logs').mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(launch_agent(ROOT)))
    domain = f'gui/{os.getuid()}'
    loaded = subprocess.run(['/bin/launchctl', 'print', domain + '/' + LABEL], capture_output=True)
    if loaded.returncode == 0:
        subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(target)], check=True)
    subprocess.run(['/bin/launchctl', 'enable', domain + '/' + LABEL], check=True)
    # Do not remove the old job until launchd confirms the replacement is loaded.
    subprocess.run(['/bin/launchctl', 'print', domain + '/' + LABEL], check=True, stdout=subprocess.DEVNULL)
    if original != updated:
        subprocess.run(['/usr/bin/crontab', '-'], input=updated, text=True, check=True)
    for task_id in task_ids:
        tasks[task_id].update(scheduler='launchd', launch_agent=LABEL,
                              description='Nightly knowledge learning; 2 AM with idle catch-up')
    atomic_json(tasks_path, tasks)
    print(f'Installed {target}\nBackups: {backup}\n2 AM, 15-minute idle retries; virtualenv Python.')


if __name__ == '__main__':
    main()
