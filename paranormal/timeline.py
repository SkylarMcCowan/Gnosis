"""Temporal proximity is descriptive, never evidence of causation."""
from datetime import datetime


def correlations(events, anchor, window_seconds=2):
    stamp = datetime.fromisoformat(anchor['timestamp']).timestamp()
    result = []
    for event in events:
        delta = datetime.fromisoformat(event['timestamp']).timestamp() - stamp
        if event['id'] != anchor['id'] and abs(delta) <= window_seconds:
            result.append(dict(event=event, delta_seconds=delta))
    return sorted(result, key=lambda x: x['delta_seconds'])
