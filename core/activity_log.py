"""A flat, append-only log of every event published on core.events.events -
JSON Lines, same pattern as memory/experience.py (including the same fix
applied there from the start this time: only `record_activity`, the write
path, ever creates the `activity/` directory - a read must never have that
side effect).

Not Phase 13 (Observability) itself - this is just the raw material a
future Phase 13 metric would read from. Phase 12's own job is making sure
every published event lands somewhere real, not computing anything from
them yet.
"""
import json
import os
from datetime import datetime

from core import config as core_config


def _activity_log_path():
    return os.path.join(core_config.path("activity"), "log.jsonl")


def record_activity(event_name, **payload):
    """Subscribe this directly to any event name via
    core.events.events.subscribe(name, lambda **p: record_activity(name, **p))
    - see webagent.py's _register_event_subscribers()."""
    path = _activity_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"event": event_name, "timestamp": datetime.now().isoformat(), **payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_activity(limit=None, event_name=None):
    path = _activity_log_path()
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if event_name is not None:
        entries = [e for e in entries if e.get("event") == event_name]
    if limit is not None:
        entries = entries[-limit:]
    return entries
