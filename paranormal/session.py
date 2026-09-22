"""Local session metadata and append-only objective event records."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Session:
    def __init__(self, root, metadata, config):
        self.directory = Path(root) / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.data = dict(metadata=metadata, configuration=config, start_time=now(), end_time=None,
                         baseline=None, equipment='Built-in Mac microphone (user-selected)',
                         sensors={'microphone': 'INACTIVE', 'camera': 'INACTIVE',
                                  'wifi': 'INACTIVE — cache observation not started',
                                  'bluetooth': 'UNAVAILABLE — strictly passive API not verified'},
                         measurements='PCM samples: direct digital input. RMS, peak, FFT and baseline: derived; dBFS, not dB SPL.',
                         continuous_recordings=[])
        self.count = 0
        self.save()

    def save(self):
        target = self.directory / 'session.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(target)

    def event(self, kind, observation, timestamp=None, **fields):
        self.count += 1
        event = dict(id=f'EVENT {self.count:03d}', timestamp=timestamp or now(), type=kind,
                     observation=observation, interpretation='', hypothesis='', confidence=None,
                     notes='', tags=[], **fields)
        import hashlib
        from .evidence import canonical
        event['sha256'] = hashlib.sha256(canonical(event)).hexdigest()
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, allow_nan=False) + '\n')
        return event

    def timestamp(self, seconds, origin):
        return (datetime.fromisoformat(origin) + timedelta(seconds=seconds)).isoformat(timespec='milliseconds')

    def close(self):
        self.data['end_time'] = now()
        self.data['sensor_states_at_end'] = dict(self.data['sensors'])
        self.data['sensors']['microphone'] = 'INACTIVE'
        self.data['sensors']['camera'] = 'INACTIVE'
        self.save()
