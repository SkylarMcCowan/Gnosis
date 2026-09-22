"""Self-contained local HTML report with explicit epistemic categories."""
from html import escape
import json
from uuid import uuid4
from .evidence import EvidenceStore, records, canonical
import hashlib
from .experiments import compare_intervals
from .session import now


def generate_report(directory):
    store = EvidenceStore(directory)
    metadata = json.loads((store.directory / 'session.json').read_text())
    events = sorted(records(store.directory / 'events.jsonl'), key=lambda e: e['timestamp'])
    annotations = store.annotations()
    def pre(value):
        return '<pre>' + escape(json.dumps(value, indent=2, ensure_ascii=False)) + '</pre>'
    parts = ['<!doctype html><meta charset="utf-8"><title>Investigation report</title>',
             '<style>body{font:15px system-ui;margin:3em;max-width:1100px}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #aaa;padding:1em 0}</style>',
             '<h1>Gnosis Investigation Report</h1><p>Measure first. Interpret later.</p>',
             '<p>Temporal proximity does not establish causation. Hashes detect changes against the stored manifest; they are not independent proof of authenticity.</p>',
             '<h2>Session, equipment, sensor availability and baselines</h2>', pre(metadata),
             '<h2>Chronological event timeline</h2>']
    for event in events:
        note = annotations.get(event['id'], {})
        original = {k: v for k, v in event.items() if k not in ('interpretation', 'hypothesis', 'notes', 'tags', 'confidence')}
        parts += ['<section><h3>' + escape(event['id'] + ' — ' + event['type']) + '</h3>',
                  '<h4>OBSERVATION</h4>', pre(original),
                  '<h4>INTERPRETATION — investigator supplied</h4>', pre({k: note.get(k) for k in ('interpretation', 'confidence', 'notes', 'tags', 'bookmarks')}),
                  '<h4>HYPOTHESIS — investigator supplied</h4>', pre(note.get('hypothesis', '')), '</section>']
    event_checks = []
    for event in events:
        payload = dict(event)
        recorded = payload.pop('sha256', None)
        event_checks.append(dict(id=event['id'], status=('UNHASHED LEGACY EVENT' if not recorded else
                                 'OK' if hashlib.sha256(canonical(payload)).hexdigest() == recorded else 'MISMATCH')))
    parts += ['<h2>Controlled intervals — descriptive rates only</h2>', pre(compare_intervals(events, metadata.get('end_time') or now())),
              '<h2>Evidence hashes and processing history</h2>', pre(store.manifest()),
              '<h2>Integrity verification at report generation</h2>', pre(store.verify()), pre(event_checks),
              '<h2>Annotation history</h2>', pre(records(store.directory / 'annotations.jsonl'))]
    filename = f'report-{uuid4().hex}.html'
    with (store.directory / filename).open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(parts))
    store.register(filename, 'report', 'Generate session report', {'generated_at': now()})
    return str(store.directory / filename)
