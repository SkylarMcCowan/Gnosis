"""Append-only provenance and annotations. Originals are never replaced."""
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4
from .session import now

_LOCK = threading.RLock()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_path(directory, relative):
    root = Path(directory).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Evidence must remain inside the session directory')
    return path


def records(path):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            result = []
            for line in stream:
                if not line.endswith('\n'):
                    break  # A live writer may not have completed its last record yet.
                result.append(json.loads(line))
            return result
    except FileNotFoundError:
        return []


def append_record(path, value):
    with _LOCK, Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, allow_nan=False) + '\n')


class EvidenceStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def register(self, relative, role='original', operation=None, parameters=None, sources=None):
        path = safe_path(self.directory, relative)
        with _LOCK:
            for record in self.manifest():
                if record['file'] == relative:
                    if digest(path) != record['sha256']:
                        raise ValueError(f'Integrity mismatch: {relative}')
                    return record
            record = dict(file=relative, role=role, registered_at=now(), sha256=digest(path),
                          size=path.stat().st_size, operation=operation,
                          parameters=parameters or {}, sources=sources or [])
            append_record(self.directory / 'evidence.jsonl', record)
            return record

    def manifest(self):
        return records(self.directory / 'evidence.jsonl')

    def verify(self):
        result = []
        for record in self.manifest():
            try:
                status = 'OK' if digest(safe_path(self.directory, record['file'])) == record['sha256'] else 'MISMATCH'
            except (OSError, ValueError):
                status = 'MISSING / INACCESSIBLE'
            result.append(dict(file=record['file'], status=status))
        return result

    def write_bytes(self, suffix, data, role='original', operation=None, parameters=None, sources=None):
        relative = f'{role}-{uuid4().hex}{suffix}'
        with safe_path(self.directory, relative).open('xb') as stream:
            stream.write(data)
        self.register(relative, role, operation, parameters, sources)
        return relative

    def annotate(self, event_id, interpretation='', hypothesis='', confidence=None, notes='', tags=None, bookmarks=None, blind=False):
        if confidence is not None and confidence not in range(1, 6):
            raise ValueError('Confidence must be 1–5 or unset')
        value = dict(event_id=event_id, timestamp=now(), interpretation=interpretation,
                     hypothesis=hypothesis, confidence=confidence, notes=notes,
                     tags=tags or [], bookmarks=bookmarks or [], blind=blind)
        append_record(self.directory / 'annotations.jsonl', value)
        return value

    def annotations(self):
        return {a['event_id']: a for a in records(self.directory / 'annotations.jsonl')}
