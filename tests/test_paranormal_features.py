"""Deterministic local fixtures only: never request privacy consent or open real sensors."""
import hashlib
import json
import math
from pathlib import Path
import struct
import wave

import pytest

from paranormal.session import Session, now
from paranormal.evidence import EvidenceStore, records, safe_path, canonical, digest
from paranormal.audio_recorder import Recorder
from paranormal.audio_review import derive, info, visualization, simulated_sweep
from paranormal.camera_monitor import CameraMonitor, difference
from paranormal.network_monitor import NetworkMonitor
from paranormal.blind_review import neutral_event
from paranormal.experiments import compare_intervals
from paranormal.timeline import correlations
from paranormal.reports import generate_report


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path, {'name': '<script>test</script>', 'location': 'Manual location'}, {})


def audio(session, seconds=.5):
    rate = 48000
    name = 'test-original.wav'
    raw = struct.pack('<' + 'h' * int(rate * seconds), *(int(5000 * math.sin(2 * math.pi * 1000 * i / rate)) for i in range(int(rate * seconds))))
    writer = Recorder(session.directory / name, rate)
    writer.write(raw)
    writer.close()
    EvidenceStore(session.directory).register(name)
    return name, raw


def test_hashes_tampering_and_path_boundaries(session, tmp_path):
    name, raw = audio(session)
    store = EvidenceStore(session.directory)
    assert store.verify() == [{'file': name, 'status': 'OK'}]
    (session.directory / name).write_bytes(b'tampered')
    assert store.verify()[0]['status'] == 'MISMATCH'
    with pytest.raises(ValueError, match='mismatch'):
        store.register(name)
    with pytest.raises(ValueError, match='inside'):
        safe_path(session.directory, '../escape.wav')
    outside = tmp_path / 'outside'
    outside.write_text('private')
    (session.directory / 'link').symlink_to(outside)
    with pytest.raises(ValueError):
        safe_path(session.directory, 'link')


def test_derived_reverse_and_provenance_preserve_original(session):
    name, raw = audio(session)
    original_hash = digest(session.directory / name)
    result = derive(session.directory, name, 0, .5, reverse=True)
    with wave.open(str(session.directory / result), 'rb') as stream:
        actual = stream.readframes(stream.getnframes())
    samples = list(struct.unpack('<' + 'h' * (len(raw)//2), raw))
    assert list(struct.unpack('<' + 'h' * len(samples), actual)) == list(reversed(samples))
    assert digest(session.directory / name) == original_hash
    record = EvidenceStore(session.directory).manifest()[-1]
    assert record['role'] == 'derived'
    assert record['sources'][0]['sha256'] == original_hash
    assert record['parameters']['reverse']


def test_gain_filter_bounds_and_visualization(session):
    name, _ = audio(session)
    with pytest.raises(ValueError):
        derive(session.directory, name, 0, .5, lowpass=100, highpass=1000)
    with pytest.raises(ValueError):
        derive(session.directory, name, .4, .2)
    result = derive(session.directory, name, 0, .5, gain_db=6, lowpass=100)
    assert info(session.directory / result)['duration'] == .5
    data = visualization(session.directory / name, 0, .5)
    assert data['waveform'] and data['spectrogram']
    assert len(data['spectrogram']) <= 161


def test_camera_pre_event_post_and_region(session):
    from PyQt6.QtGui import QImage, QColor
    before = QImage(64, 48, QImage.Format.Format_RGB32)
    before.fill(QColor('black'))
    after = before.copy()
    for y in range(24):
        for x in range(32, 64):
            after.setPixelColor(x, y, QColor('white'))
    monitor = CameraMonitor(session, threshold=4)
    monitor.feed(before, '2026-09-20T00:00:00+00:00', 0)
    metrics = monitor.feed(after, '2026-09-20T00:00:01+00:00', 1)
    assert metrics['region'] == 'upper-right'
    assert metrics['difference_percent'] == pytest.approx(25)
    monitor.feed(after, '2026-09-20T00:00:01.500+00:00', 1.5)
    event = records(session.directory / 'events.jsonl')[0]
    assert len(event['evidence']) == 3
    assert event['type'] == 'Visual'
    assert all(e['status'] == 'OK' for e in EvidenceStore(session.directory).verify())
    payload = dict(event)
    hashed = payload.pop('sha256')
    assert hashlib.sha256(canonical(payload)).hexdigest() == hashed


def test_camera_stop_retains_pending_evidence_and_timelapse(session):
    from PyQt6.QtGui import QImage, QColor
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(QColor('black'))
    monitor = CameraMonitor(session, timelapse_seconds=10)
    monitor.feed(image, now(), 0)
    white = image.copy()
    white.fill(QColor('white'))
    monitor.feed(white, now(), 1)
    monitor.finish()
    events = records(session.directory / 'events.jsonl')
    assert events[0]['timelapse']
    assert events[1]['truncated']
    assert len(events[1]['evidence']) == 2


class Network:
    def ssid(self): return None
    def bssid(self): return 'aa:bb'
    def rssiValue(self): return -50
    def wlanChannel(self): return self
    def channelNumber(self): return 6


class Interface:
    values = [Network()]
    def cachedScanResults(self): return self.values
    def scanForNetworksWithSSID_error_(self, *args): raise AssertionError('Must never scan')


def test_wifi_observes_cache_only_with_redactions():
    interface = Interface()
    monitor = NetworkMonitor(interface)
    first = monitor.observe()
    assert first['cached_network_count'] == 1
    assert first['networks'][0]['ssid'] is None
    interface.values = []
    second = monitor.observe()
    assert second['count_change'] == -1 and second['disappeared'] == ['aa:bb']
    interface.values = None
    assert monitor.observe()['state'] == 'UNAVAILABLE'


def test_annotations_are_separate_and_blind_projection_is_neutral(session):
    event = session.event('Audio', 'Audio event detected.')
    original = (session.directory / 'events.jsonl').read_bytes()
    store = EvidenceStore(session.directory)
    store.annotate(event['id'], interpretation='Possible human voice', hypothesis='Neighbor', confidence=2,
                   tags=['POSSIBLE_HUMAN'], bookmarks=[{'seconds': .2}], blind=True)
    assert (session.directory / 'events.jsonl').read_bytes() == original
    assert store.annotations()[event['id']]['interpretation'] == 'Possible human voice'
    assert set(neutral_event(event)) == {'id', 'observation'}
    with pytest.raises(ValueError):
        store.annotate(event['id'], confidence=6)


def test_correlation_and_controlled_intervals():
    events = [dict(id='E1', type='Experiment', timestamp='2026-09-20T00:00:00+00:00', label='Control'),
              dict(id='E2', type='Audio', timestamp='2026-09-20T00:00:10+00:00'),
              dict(id='E3', type='Visual', timestamp='2026-09-20T00:00:11+00:00'),
              dict(id='E4', type='Experiment', timestamp='2026-09-20T00:01:00+00:00', label='Stimulus')]
    assert correlations(events, events[1])[0]['delta_seconds'] == 1
    result = compare_intervals(events, '2026-09-20T00:02:00+00:00')
    assert result[0]['events_per_minute'] == 2
    assert result[1]['events_per_minute'] == 0


def test_report_escapes_text_and_separates_categories(session):
    name, _ = audio(session)
    event = session.event('Audio', 'Audio event detected.', evidence=name)
    EvidenceStore(session.directory).annotate(event['id'], interpretation='Possible voice', hypothesis='Traffic', confidence=2)
    session.close()
    report = Path(generate_report(session.directory)).read_text()
    assert '<script>test</script>' not in report
    assert '&lt;script&gt;test&lt;/script&gt;' in report
    assert 'OBSERVATION' in report and 'INTERPRETATION' in report and 'HYPOTHESIS' in report
    assert 'Possible voice' in report and 'Traffic' in report
    assert 'sha256' in report and 'OK' in report


def test_simulated_sweep_is_reproducible_and_self_contained(session):
    name, raw = audio(session)
    options = dict(fragment_ms=100, duration_seconds=1, seed=17, noise_db=-60, crossfade_ms=5)
    a = simulated_sweep(session.directory, [session.directory / name], **options)
    b = simulated_sweep(session.directory, [session.directory / name], **options)
    assert (session.directory / a).read_bytes() == (session.directory / b).read_bytes()
    assert info(session.directory / a)['duration'] == 1
    record = EvidenceStore(session.directory).manifest()[-1]
    assert record['role'] == 'synthetic'
    assert record['operation'] == 'SIMULATED RADIO SWEEP — NOT RF RECEPTION'
    assert (session.directory / record['sources'][0]['file']).exists()
    assert record['parameters']['seed'] == 17


def test_worker_mixed_capture_and_report(session, tmp_path):
    from paranormal.audio_monitor import InvestigationWorker
    from PyQt6.QtGui import QImage, QColor
    config = dict(rate=48000, band=(20,200), threshold_db=12, pre_seconds=0, post_seconds=0, continuous=False)
    worker = InvestigationWorker(tmp_path / 'workers', {}, config)
    worker.start()
    worker.submit('experiment', dict(timestamp=now(), label='Control', trial='First'))
    image = QImage(64,48,QImage.Format.Format_RGB32)
    image.fill(QColor('black'))
    worker.submit('camera', (image, now(), 0))
    image2 = image.copy()
    image2.fill(QColor('white'))
    worker.submit('camera', (image2, now(), 1))
    worker.stopping.set()
    worker.join(5)
    assert worker.failure is None
    assert list(worker.session.directory.glob('report-*.html'))
    events = records(worker.session.directory / 'events.jsonl')
    assert [e['type'] for e in events] == ['Experiment', 'Visual']
    assert all(v['status'] == 'OK' for v in EvidenceStore(worker.session.directory).verify())


def test_redacted_wifi_does_not_invent_disappearance():
    interface = Interface()
    monitor = NetworkMonitor(interface)
    monitor.observe()
    class Redacted(Network):
        def bssid(self): return None
    interface.values = [Redacted()]
    result = monitor.observe()
    assert result['identifiers_redacted']
    assert result['appeared'] == result['disappeared'] == []


def test_blind_ui_hides_saved_interpretations_and_lists_derivatives(session, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    from paranormal.ui.review import ReviewPanel
    import time
    app = QApplication.instance() or QApplication([])
    name, _ = audio(session)
    event = session.event('Audio', 'A user supplied suggestive description', evidence=name)
    store = EvidenceStore(session.directory)
    store.annotate(event['id'], interpretation='SECRET INTERPRETATION', hypothesis='SECRET HYPOTHESIS',
                   tags=['SECRET TAG'], bookmarks=[dict(file=name, seconds=.1)])
    derive(session.directory, name, 0, .2)
    panel = ReviewPanel()
    assert panel.set_session(session.directory)
    assert 'suggestive' not in panel.observed.text()
    assert panel.interpretation.text() == panel.hypothesis.text() == panel.tags.text() == ''
    assert panel.derived_files.count() == 1
    panel.blind.setChecked(False)
    assert panel.interpretation.text() == 'SECRET INTERPRETATION'
    assert panel.bookmark_list.count() == 1
    panel.blind.setChecked(True)
    assert panel.interpretation.text() == ''
    for _ in range(100):
        app.processEvents()
        if panel.job is None:
            break
        time.sleep(.01)
    assert panel.graph.data
    assert panel.shutdown()
    panel.poll.stop()
    panel.close()
