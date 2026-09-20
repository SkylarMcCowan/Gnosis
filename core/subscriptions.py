"""A user-curated list of "things to follow" - teams, topics, websites - that
query-time code (webagent.py's model_directed_web_research) checks before
falling back to regex/model-driven detection of what a message is about.

The point: inferring both "does this need a live lookup" and "which subject"
from raw prompt text every single message is exactly where a small local
model goes wrong (misparses its own JSON, wrongly refuses an in-scope
query). A subscription lets the user declare the subject once; from then on
it's a known, pre-resolved entry instead of a guess.

Same discipline as core/activity_log.py: only the write path
(add_subscription/remove_subscription) ever creates the subscriptions/
directory - a read (list_subscriptions/get_subscription) must never have
that side effect.

Pure CRUD/storage only - deliberately does not import webagent.py (would
create a circular import, and core/ modules stay usable standalone).
Resolving a subscription against a real source (e.g. looking up a soccer
team's ESPN id) is webagent.py's job, since that's where the resolver
functions already live; this module just persists whatever metadata that
resolution produced.
"""
import json
import os
import uuid
import threading
import tempfile
from datetime import datetime

from core import config as core_config

_write_lock = threading.RLock()

SUBSCRIPTION_TYPES = ("team", "topic", "website", "weather")


def _subscriptions_path():
    return os.path.join(core_config.path("subscriptions"), "subscriptions.json")


def list_subscriptions(sub_type=None):
    path = _subscriptions_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(records, list):
        return []
    if sub_type is not None:
        records = [r for r in records if r.get("type") == sub_type]
    return records


def get_subscription(subscription_id):
    for record in list_subscriptions():
        if record.get("id") == subscription_id:
            return record
    return None


def _save_subscriptions(records):
    path = _subscriptions_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".subscriptions-", delete=False) as handle:
            temporary = handle.name
            json.dump(records, handle, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def add_subscription(sub_type, name, metadata=None):
    with _write_lock:
        return _add_subscription(sub_type, name, metadata)


def _add_subscription(sub_type, name, metadata=None):
    if sub_type not in SUBSCRIPTION_TYPES:
        raise ValueError(f"Unknown subscription type {sub_type!r} - must be one of {SUBSCRIPTION_TYPES}")
    name = (name or "").strip()
    if not name:
        raise ValueError("A subscription needs a non-empty name.")

    records = list_subscriptions()
    for record in records:
        if record.get("type") == sub_type and record.get("name", "").casefold() == name.casefold():
            raise ValueError(f"Already subscribed to {sub_type} \"{name}\".")

    record = {
        "id": uuid.uuid4().hex[:8],
        "type": sub_type,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "metadata": metadata or {},
    }
    records.append(record)
    _save_subscriptions(records)
    return record


def remove_subscription(subscription_id):
    with _write_lock:
        return _remove_subscription(subscription_id)


def _remove_subscription(subscription_id):
    records = list_subscriptions()
    remaining = [r for r in records if r.get("id") != subscription_id]
    if len(remaining) == len(records):
        return False
    _save_subscriptions(remaining)
    return True
