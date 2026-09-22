"""Sample-clock baseline and threshold detection. No semantic classification."""
import math
from collections import deque
from .audio_recorder import Recorder
from .spectrum import db


class Detector:
    def __init__(self, session, config):
        self.session, self.config = session, config
        self.rate = config['rate']
        self.position = 0
        self.origin = None
        self.baseline = None
        self.calibration = None
        self.ring = deque()
        self.ring_size = 0
        self.pending = None
        self.serial = 0

    def calibrate(self, seconds):
        if self.pending:
            self.finish(truncated=True)
        self.baseline = None
        self.calibration = dict(target=int(seconds * self.rate), start=self.position, frames=0, power=0,
                                peak=-120, spectrum=None)

    def feed(self, pcm, metrics):
        frames = len(pcm) // 2
        start = self.position
        self.position += frames
        if self.calibration is not None:
            c = self.calibration
            c['frames'] += frames
            c['power'] += metrics['power'] * frames
            c['peak'] = max(c['peak'], metrics['peak_dbfs'])
            powers = [10 ** (v / 10) for v in metrics['spectrum']]
            c['spectrum'] = powers if c['spectrum'] is None else [a + b for a, b in zip(c['spectrum'], powers)]
            if c['frames'] >= c['target']:
                self.baseline = dict(timestamp=self.session.timestamp(c["start"] / self.rate, self.origin),
                                     duration=c['frames'] / self.rate,
                                     rms_dbfs=db(math.sqrt(c['power'] / c['frames'])), peak_dbfs=c['peak'],
                                     spectrum_dbfs=[10 * math.log10(max(p / (c['frames'] / frames), 1e-12)) for p in c['spectrum']],
                                     bin_hz=self.rate / frames)
                self.session.data['baseline'] = self.baseline
                self.session.save()
                self.calibration = None
        elif self.baseline:
            deviation = metrics['rms_dbfs'] - self.baseline['rms_dbfs']
            above = deviation >= self.config['threshold_db']
            if above and self.pending is None:
                self.serial += 1
                filename = f'audio-event-{self.serial:06d}.wav'
                writer = Recorder(self.session.directory / filename, self.rate)
                for previous in self.ring:
                    writer.write(previous)
                self.pending = dict(writer=writer, file=filename, start=start, last=self.position,
                                    clip_start=start - self.ring_size // 2, peak=-120,
                                    dominant_hz=metrics['dominant_hz'], deviation_db=deviation)
            if self.pending:
                p = self.pending
                p['writer'].write(pcm)
                if above:
                    p['last'] = self.position
                if metrics['peak_dbfs'] > p['peak']:
                    p['peak'], p['dominant_hz'] = metrics['peak_dbfs'], metrics['dominant_hz']
                p['deviation_db'] = max(p['deviation_db'], deviation)
                if self.position - p['last'] >= self.config['post_seconds'] * self.rate:
                    self.finish()
                elif self.position - p['start'] >= 60 * self.rate:
                    self.finish(truncated=True)  # Bound sustained events; next block starts another clip.
        self.ring.append(pcm)
        self.ring_size += len(pcm)
        limit = int(self.config['pre_seconds'] * self.rate) * 2
        while self.ring_size > limit:
            excess = self.ring_size - limit
            first = self.ring.popleft()
            if len(first) > excess:
                self.ring.appendleft(first[excess:])
                self.ring_size -= excess
            else:
                self.ring_size -= len(first)

    def finish(self, truncated=False):
        if not self.pending:
            return
        p, self.pending = self.pending, None
        p['writer'].close()
        from .evidence import EvidenceStore
        EvidenceStore(self.session.directory).register(p['file'], parameters={'capture': 'Audio event', 'clip_start': self.session.timestamp(p['clip_start'] / self.rate, self.origin)})
        self.session.event('Audio', 'Audio event detected.',
                           timestamp=self.session.timestamp(p['start'] / self.rate, self.origin),
                           duration_seconds=(p['last'] - p['start']) / self.rate,
                           peak_dbfs=p['peak'], dominant_hz=p['dominant_hz'], deviation_db=p['deviation_db'],
                           evidence=p['file'], clip_start=self.session.timestamp(p['clip_start'] / self.rate, self.origin),
                           clip_duration_seconds=p['writer'].frames / self.rate, truncated=truncated)
