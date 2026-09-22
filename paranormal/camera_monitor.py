"""Image-difference measurements and unmodified PNG captures; no object classification."""
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage
from .evidence import EvidenceStore


def png(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError('Could not encode camera frame')
    return bytes(buffer.data())


def grayscale(image):
    small = image.scaled(64, 48).convertToFormat(QImage.Format.Format_Grayscale8)
    return bytes(small.constBits().asstring(small.sizeInBytes()))


def difference(before, after):
    if len(before) != 3072 or len(after) != 3072:
        raise ValueError('Frame analysis requires 64 × 48 grayscale samples')
    diffs = [abs(a - b) for a, b in zip(before, after)]
    regions = [0.0] * 4
    for i, value in enumerate(diffs):
        regions[(i // 64 >= 24) * 2 + (i % 64 >= 32)] += value
    return dict(difference_percent=sum(diffs) / (3072 * 255) * 100,
                region=('upper-left', 'upper-right', 'lower-left', 'lower-right')[regions.index(max(regions))],
                brightness_percent=sum(after) / (3072 * 255) * 100)


class CameraMonitor:
    def __init__(self, session, threshold=4, timelapse_seconds=0):
        self.session = session
        self.store = EvidenceStore(session.directory)
        self.threshold = threshold
        self.timelapse_seconds = timelapse_seconds
        self.previous = None
        self.pending = None
        self.last_timelapse = None
        self.last_event = -10
        self.latest = None

    def save(self, image, timestamp, purpose):
        return self.store.write_bytes('.png', png(image), parameters={'frame_timestamp': timestamp, 'purpose': purpose, 'width': image.width(), 'height': image.height(), 'encoding': 'Unedited Qt-decoded frame saved losslessly as PNG'})

    def feed(self, image, timestamp, monotonic):
        current = grayscale(image)
        if self.pending:
            pending, self.pending = self.pending, None
            after = self.save(image, timestamp, 'post-event frame')
            self.session.event('Visual', 'Visual change detected.', timestamp=pending['timestamp'],
                               evidence=pending['frames'] + [after], **pending['metrics'])
        if self.previous:
            previous_image, previous_gray, previous_stamp = self.previous
            self.latest = difference(previous_gray, current)
            if self.latest['difference_percent'] >= self.threshold and monotonic - self.last_event >= 2:
                before = self.save(previous_image, previous_stamp, 'pre-event frame')
                at = self.save(image, timestamp, 'event frame')
                self.pending = dict(timestamp=timestamp, frames=[before, at], metrics=self.latest)
                self.last_event = monotonic
        else:
            self.latest = dict(brightness_percent=sum(current) / (3072 * 255) * 100)
        if self.timelapse_seconds and (self.last_timelapse is None or monotonic - self.last_timelapse >= self.timelapse_seconds):
            frame = self.save(image, timestamp, 'time-lapse frame')
            self.session.event('Visual', 'Time-lapse frame captured.', timestamp=timestamp, evidence=[frame], timelapse=True)
            self.last_timelapse = monotonic
        self.previous = (image, current, timestamp)
        return self.latest

    def finish(self):
        if self.pending:
            p, self.pending = self.pending, None
            self.session.event('Visual', 'Visual change detected.', timestamp=p['timestamp'],
                               evidence=p['frames'], truncated=True, **p['metrics'])
