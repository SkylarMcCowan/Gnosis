"""Synthetic PCM only: tests never open a microphone or request permission."""
import json
import math
import struct
import time
import wave

import pytest

from paranormal.spectrum import measure
from paranormal.session import Session, now
from paranormal.event_detector import Detector
from paranormal.audio_monitor import InvestigationWorker


def pcm(amplitude, n=4096, hz=1500, rate=48000):
    return struct.pack('<' + 'h' * n, *(int(amplitude * 32767 * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)))


def config(**changes):
    return dict(rate=48000, band=(20, 200), continuous=False, threshold_db=10,
                pre_seconds=0.1, post_seconds=0.1, **changes)


def test_measurement_units_and_frequency():
    m = measure(pcm(0.5), 48000)
    assert m['rms_dbfs'] == pytest.approx(-9.03, abs=0.05)
    assert m['peak_dbfs'] == pytest.approx(-6.02, abs=0.05)
    assert m['dominant_hz'] == pytest.approx(1500)
    assert m['band_dbfs'] < -80
    assert measure(bytes(8192), 48000)['rms_dbfs'] == -120


def test_baseline_event_buffers_and_original(tmp_path):
    c = config()
    session = Session(tmp_path, {'name': 'test'}, c)
    d = Detector(session, c)
    d.origin = now()
    quiet, loud = pcm(.001), pcm(.2)
    d.calibrate(.1)
    for _ in range(3):
        d.feed(quiet, measure(quiet, c['rate']))
    assert d.baseline['duration'] >= .1
    d.feed(loud, measure(loud, c['rate']))
    for _ in range(2):
        d.feed(quiet, measure(quiet, c['rate']))
    events = [json.loads(line) for line in (session.directory / 'events.jsonl').read_text().splitlines()]
    assert len(events) == 1
    event = events[0]
    assert event['type'] == 'Audio'
    assert event['interpretation'] == event['hypothesis'] == ''
    assert event['deviation_db'] > 40
    with wave.open(str(session.directory / event['evidence']), 'rb') as f:
        data = f.readframes(f.getnframes())
    assert data == (quiet + quiet)[-9600:] + loud + quiet + quiet
    assert event['duration_seconds'] == pytest.approx(4096 / 48000)
    assert not event['truncated']


def test_no_detection_before_calibration_and_interrupted_event(tmp_path):
    c = config()
    s = Session(tmp_path, {}, c)
    d = Detector(s, c)
    d.origin = now()
    loud = pcm(.5)
    d.feed(loud, measure(loud, c['rate']))
    assert d.pending is None
    d.calibrate(.01)
    quiet = pcm(.001)
    d.feed(quiet, measure(quiet, c['rate']))
    d.feed(loud, measure(loud, c['rate']))
    d.finish(truncated=True)
    e = json.loads((s.directory / 'events.jsonl').read_text())
    assert e['truncated']
    assert (s.directory / e['evidence']).stat().st_size > 44


def test_worker_partial_buffers_recording_and_metadata(tmp_path):
    c = config()
    c['continuous'] = True
    worker = InvestigationWorker(tmp_path, {'location': 'Entered manually'}, c)
    worker.start()
    raw = pcm(.01) + b'\x01\x00'
    worker.submit('audio', (raw[:33], now()))
    worker.submit('audio', (raw[33:], now()))
    worker.submit('marker', {'timestamp': now(), 'observation': 'Door closed', 'notes': 'control'})
    worker.stopping.set()
    worker.join(5)
    assert not worker.is_alive()
    assert worker.failure is None
    metadata = json.loads((worker.session.directory / 'session.json').read_text())
    assert metadata['end_time']
    assert metadata['metadata']['location'] == 'Entered manually'
    with wave.open(str(worker.session.directory / metadata['continuous_recordings'][0]), 'rb') as f:
        assert f.readframes(f.getnframes()) == raw
    assert json.loads((worker.session.directory / 'events.jsonl').read_text())['type'] == 'Manual'


def test_queue_overflow_is_explicit(tmp_path):
    w = InvestigationWorker(tmp_path, {}, config())
    for _ in range(128):
        assert w.submit('audio', (b'', now()))
    assert not w.submit('audio', (b'', now()))
    assert w.stopping.is_set()
    assert 'overflow' in w.failure


def test_exclusive_evidence_creation(tmp_path):
    from paranormal.audio_recorder import Recorder
    path = tmp_path / 'original.wav'
    r = Recorder(path, 48000)
    r.write(pcm(.1))
    r.close()
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        Recorder(path, 48000)
    assert path.read_bytes() == original


def test_pane_is_idle_and_manual_session_works(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    from paranormal.ui.widget import ParanormalLabWidget
    app = QApplication.instance() or QApplication([])
    pane = ParanormalLabWidget(tmp_path)
    assert pane.source is None and pane.worker is None
    assert not pane.mark.isEnabled()
    pane.start_session()
    monkeypatch.setattr("paranormal.ui.widget.microphone_usage_declared", lambda: False)
    pane.start_microphone()
    assert "PERMISSION REQUIRED" in pane.capture_status
    assert pane.source is None
    pane.observation.setText('Observed a sound')
    pane.mark_event()
    pane.end_session()
    pane.worker.join(5)
    pane.refresh()
    assert len(pane.events) == 1
    assert pane.events[0]['observation'] == 'Observed a sound'
    assert pane.shutdown()
    pane.close()


def test_short_continuous_capture_is_not_lost(tmp_path):
    c = config()
    c['continuous'] = True
    worker = InvestigationWorker(tmp_path, {}, c)
    worker.start()
    raw = pcm(.01, n=64)
    worker.submit('audio', (raw, now()))
    worker.stopping.set()
    worker.join(5)
    assert worker.failure is None
    with wave.open(str(worker.session.directory / 'continuous-0001.wav'), 'rb') as f:
        assert f.readframes(f.getnframes()) == raw


def test_write_failure_is_visible(tmp_path, monkeypatch):
    import paranormal.audio_monitor as monitor
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(monitor, 'Recorder', fail)
    c = config()
    c['continuous'] = True
    worker = InvestigationWorker(tmp_path, {}, c)
    worker.start()
    worker.submit('audio', (pcm(.1), now()))
    worker.stopping.set()
    worker.join(5)
    assert worker.snapshot['state'] == 'ERROR'
    assert 'disk full' in worker.snapshot['detail']
    assert json.loads((worker.session.directory / 'session.json').read_text())['end_time']


def test_macos_bundle_generation_preserves_original(tmp_path, monkeypatch):
    from scripts.macos_gui import prepare_bundle, USAGE
    import plistlib
    import subprocess
    prefix = tmp_path / 'framework'
    contents = prefix / 'Resources/Python.app/Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'MacOS/Python').write_bytes(b'fake-test-binary')
    original = plistlib.dumps({'CFBundleExecutable': 'Python', 'CFBundleIdentifier': 'org.python.python'})
    (contents / 'Info.plist').write_bytes(original)
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: calls.append(a))
    launcher = prepare_bundle(prefix, tmp_path / 'cache')
    info = plistlib.loads((launcher.parents[1] / 'Info.plist').read_bytes())
    assert info['NSMicrophoneUsageDescription'] == USAGE
    assert info['CFBundleIdentifier'] == 'local.gnosis.desktop'
    assert (contents / 'Info.plist').read_bytes() == original
    assert prepare_bundle(prefix, tmp_path / 'cache') == launcher
    assert len(calls) == 1
