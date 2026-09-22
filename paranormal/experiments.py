"""Investigator-labeled intervals and descriptive event rates."""
from collections import Counter
from datetime import datetime

LABELS = ('Control', 'Stimulus', 'Response', 'Repeat', 'Unknown')


def compare_intervals(events, end_time):
    ordered = sorted(events, key=lambda e: e['timestamp'])
    markers = [e for e in ordered if e['type'] == 'Experiment']
    result = []
    for i, marker in enumerate(markers):
        start = datetime.fromisoformat(marker['timestamp'])
        end = datetime.fromisoformat(markers[i + 1]['timestamp'] if i + 1 < len(markers) else end_time)
        duration = max(0, (end - start).total_seconds())
        counts = Counter(e['type'] for e in ordered if e['type'] in ('Audio', 'Visual', 'Network', 'Bluetooth')
                         and start <= datetime.fromisoformat(e['timestamp']) < end)
        result.append(dict(label=marker.get('label', 'Unknown'), trial=marker.get('trial', ''),
                           start=marker['timestamp'], duration_seconds=duration, counts=dict(counts),
                           events_per_minute=sum(counts.values()) * 60 / duration if duration else None))
    return result
