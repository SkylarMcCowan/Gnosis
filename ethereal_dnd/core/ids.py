"""Shared ID generation - matches the uuid4-hex-prefix pattern already
used elsewhere in this repo (e.g. worklog.py's task/project ids)."""
import uuid


def new_id() -> str:
    return uuid.uuid4().hex[:8]
