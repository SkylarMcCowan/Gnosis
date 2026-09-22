"""Neutral investigation dashboard and modular capture/review panels."""
import json
from pathlib import Path
import time
from PyQt6.QtCore import Qt, QTimer, QMicrophonePermission, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QSpinBox, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QScrollArea,
)
from ..audio_monitor import InvestigationWorker
from ..session import now
from ..evidence import records
from ..timeline import correlations
from .review import ReviewPanel
from .sensors import SensorPanel
from .experiments import ExperimentPanel


def microphone_usage_declared():
    from ..permissions import usage_declared
    return usage_declared('NSMicrophoneUsageDescription')


class AudioGraphs(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(290)
        self.metrics = None
        self.rate = 48000
        self.history = []

    def push(self, metrics, rate):
        self.metrics, self.rate = metrics, rate
        bins = metrics['spectrum']
        self.history.append([max(bins[i:i + 16]) for i in range(0, len(bins), 16)])
        self.history = self.history[-100:]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#10141e'))
        p.setPen(QColor('#b8c3d6'))
        w = self.width()
        p.drawText(10, 18, 'WAVEFORM  •  normalized PCM amplitude −1 … +1')
        p.drawText(10, 110, f'FFT  •  Hann 4096 samples  •  0 … {self.rate / 2000:g} kHz  •  −120 … 0 dBFS')
        p.drawText(10, 210, 'SPECTROGRAM  •  recent display frames →  •  low to high frequency ↑')
        if not self.metrics:
            p.drawText(10, 55, 'INACTIVE — no audio measurements')
            return
        for values, top, height, mode in [(self.metrics['waveform'], 26, 64, 'wave'),
                                          (self.metrics['spectrum'], 120, 70, 'fft')]:
            stride = max(1, len(values) // max(1, w))
            values = values[::stride]
            points = []
            for i, value in enumerate(values):
                normalized = (value + 1) / 2 if mode == 'wave' else max(0, min(1, (value + 120) / 120))
                points.append(QPointF(i * (w - 1) / max(1, len(values) - 1), top + height * (1 - normalized)))
            p.setPen(QPen(QColor('#8b79f6'), 1))
            p.drawPolyline(QPolygonF(points))
        h = max(1, self.height() - 225)
        for x, column in enumerate(self.history):
            for y, value in enumerate(column):
                strength = max(0, min(1, (value + 100) / 100))
                color = QColor.fromHsvF(0.7 - strength * 0.5, 0.7, 0.12 + strength * 0.88)
                p.fillRect(int(x * w / 100), int(220 + h * (1 - (y + 1) / len(column))),
                           max(1, w // 100 + 1), max(1, h // len(column) + 1), color)


class TimelinePlot(QWidget):
    def __init__(self):
        super().__init__()
        self.events = []
        self.setMinimumHeight(150)

    def paintEvent(self, event):
        from datetime import datetime
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#10141e'))
        p.setPen(QColor('#b8c3d6'))
        p.drawText(8, 16, 'SESSION TIMELINE  •  Audio / Visual / Network / Bluetooth / Manual / Experiment  •  UTC')
        if not self.events:
            return
        stamps = [datetime.fromisoformat(e['timestamp']).timestamp() for e in self.events]
        first, last = min(stamps), max(stamps)
        for e, stamp in zip(self.events, stamps):
            x = 10 + (stamp - first) / max(last - first, 1) * (self.width() - 20)
            p.setPen(QColor('#8b79f6' if e['type'] == 'Audio' else '#3ecf8e'))
            y = {'Audio': 32, 'Visual': 48, 'Network': 64, 'Bluetooth': 80, 'Manual': 96, 'Experiment': 112, 'System': 128}.get(e['type'], 62)
            p.drawLine(int(x), y - 5, int(x), y + 5)


class ParanormalLabWidget(QWidget):
    def __init__(self, root=None):
        super().__init__()
        if root is None:
            from core.config import path
            root = path('investigations')
        self.setObjectName('investigationLab')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#investigationLab { background: #10141e; color: #edf1f8; }
            QLineEdit, QSpinBox, QTextEdit, QTableWidget {
                background: #1a2232; color: #edf1f8; border: 1px solid #2a3446;
                border-radius: 6px; padding: 5px; selection-background-color: #7766de;
            }
            QHeaderView::section { background: #222b3b; color: #b8c3d6; padding: 5px; }
            QPushButton:disabled { color: #68758c; background: #171d2a; }
            QCheckBox { color: #b8c3d6; }
        """)
        self.root = root
        self.worker = None
        self.source = None
        self.io = None
        self.events = []
        self.event_offset = 0
        self.last_metrics = None
        self.permission_pending = False
        self.capture_status = 'INACTIVE'
        self.closing = False
        outer = QVBoxLayout(self)
        title = QLabel('Paranormal Investigation Lab')
        title.setStyleSheet('font-size: 23px; font-weight: bold; color: #b4a8ff;')
        outer.addWidget(title)
        outer.addWidget(QLabel('Measure first. Interpret later.  •  Observations, independent review, and controlled experiments'))
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        setup = QWidget()
        form = QFormLayout(setup)
        self.fields = {}
        for key, label in [('name', 'Investigation name'), ('location', 'Location (manual)'),
                           ('investigator', 'Investigator'), ('weather', 'Weather notes (manual)'),
                           ('environment', 'Environmental notes')]:
            self.fields[key] = QLineEdit()
            form.addRow(label, self.fields[key])
        self.rate = QComboBox()
        self.rate.addItems(['48000', '44100'])
        form.addRow('Format: WAV / mono / PCM 16-bit; sample rate', self.rate)
        self.continuous = QCheckBox('Save continuous audio (events are always saved after calibration)')
        form.addRow(self.continuous)
        self.settings = {}
        for key, label, value, low, high in [
            ('baseline_seconds', 'Baseline duration (seconds)', 60, 1, 600),
            ('threshold_db', 'Event threshold above baseline RMS (dB)', 12, 1, 80),
            ('pre_seconds', 'Pre-event buffer (seconds)', 3, 0, 30),
            ('post_seconds', 'Post-event buffer (seconds)', 3, 0, 30),
            ('band_low', 'Monitored band: lower frequency (Hz)', 20, 1, 20000),
            ('band_high', 'Monitored band: upper frequency (Hz)', 200, 2, 22000),
            ('frame_interval_ms', 'Camera analysis interval (milliseconds)', 500, 200, 10000),
            ('camera_threshold', 'Camera change threshold (mean difference %)', 4, 1, 100),
            ('timelapse_seconds', 'Time-lapse interval (seconds; 0 = off)', 0, 0, 3600)]:
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(value)
            self.settings[key] = spin
            form.addRow(label, spin)
        explanation = QLabel('Microphone access is requested only when you press Start microphone.\n'
                             'It measures audio levels and saves local evidence; no transcription or interpretation is generated.\n'
                             'Use the built-in microphone. Absolute sound pressure and infrasound are not calibrated.\n'
                             'Other Gnosis voice input, TTS, music and system sounds can affect measurements.\n'
                             f'Session storage: {self.root}')
        explanation.setWordWrap(True)
        form.addRow(explanation)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(setup)
        self.setup = setup
        self.tabs.addTab(scroll, 'Session & configuration')
        dashboard = QWidget()
        layout = QVBoxLayout(dashboard)
        self.status = QLabel('Microphone: INACTIVE  •  Recording: INACTIVE')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.sensor_summary = QLabel('Camera: INACTIVE • Wi-Fi cache: INACTIVE • Bluetooth: UNAVAILABLE')
        self.sensor_summary.setWordWrap(True)
        layout.addWidget(self.sensor_summary)
        layout.addWidget(QLabel('Ambient temperature / EMF / calibrated light: UNAVAILABLE — no supported measurement'))
        self.clock = QLabel()
        layout.addWidget(self.clock)
        self.levels = QLabel('RMS: —  |  Peak: —  |  Monitored band: —')
        layout.addWidget(self.levels)
        self.baseline_label = QLabel('BASELINE: not established; automatic event detection is inactive.')
        layout.addWidget(self.baseline_label)
        self.graphs = AudioGraphs()
        layout.addWidget(self.graphs, 1)
        buttons = QHBoxLayout()
        self.microphone = QPushButton('Start microphone')
        self.microphone.clicked.connect(self.start_microphone)
        buttons.addWidget(self.microphone)
        self.calibrate = QPushButton('CALIBRATE BASELINE')
        self.calibrate.clicked.connect(self.calibrate_baseline)
        buttons.addWidget(self.calibrate)
        layout.addLayout(buttons)
        self.tabs.addTab(dashboard, 'Investigation dashboard')
        timeline = QWidget()
        tl = QVBoxLayout(timeline)
        self.plot = TimelinePlot()
        tl.addWidget(self.plot)
        self.filter = QComboBox()
        self.filter.addItems(['All events', 'Audio', 'Visual', 'Network', 'Bluetooth', 'Manual', 'Experiment', 'System'])
        self.filter.currentTextChanged.connect(self.render_events)
        tl.addWidget(self.filter)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Event ID', 'Timestamp (UTC)', 'Type', 'Observation'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self.show_event)
        self.table.horizontalHeader().setStretchLastSection(True)
        tl.addWidget(self.table)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        tl.addWidget(self.detail)
        compare = QPushButton('Compare selected events / nearby events (±2 seconds)')
        compare.clicked.connect(self.compare_events)
        tl.addWidget(compare)
        review_selected = QPushButton('Review selected event')
        review_selected.clicked.connect(self.review_selected)
        tl.addWidget(review_selected)
        self.tabs.addTab(timeline, 'Event timeline')
        self.review = ReviewPanel(self.log_playback)
        self.review.on_session_open = self.load_saved_session
        self.sensors = SensorPanel(self)
        self.experiments = ExperimentPanel(self)
        self.tabs.addTab(self.sensors, 'Camera & environment')
        for panel, label in ((self.review, 'Evidence / blind review'), (self.experiments, 'Experiments / simulated sweep')):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            self.tabs.addTab(scroll, label)
        self.review_directory = None
        self.ending = False
        self.review.blind.toggled.connect(self.render_events)
        marker = QHBoxLayout()
        self.observation = QLineEdit()
        self.observation.setPlaceholderText('Manual observation')
        marker.addWidget(self.observation)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText('Investigator notes (separate from observation)')
        marker.addWidget(self.notes)
        self.mark = QPushButton('MARK EVENT')
        self.mark.setMinimumHeight(44)
        self.mark.clicked.connect(self.mark_event)
        marker.addWidget(self.mark)
        outer.addLayout(marker)
        row = QHBoxLayout()
        self.start = QPushButton('Create investigation session')
        self.start.clicked.connect(self.start_session)
        row.addWidget(self.start)
        self.stop = QPushButton('End session & save')
        self.stop.clicked.connect(self.end_session)
        row.addWidget(self.stop)
        outer.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def start_session(self):
        if (self.worker and self.worker.is_alive()) or self.review.job or self.experiments.job:
            return
        self.review.stop_playback()
        self.review_directory = None
        self.ending = False
        low, high = self.settings['band_low'].value(), self.settings['band_high'].value()
        if low >= high or high > int(self.rate.currentText()) / 2:
            self.status.setText('ERROR — frequency band must be ordered and below Nyquist.')
            return
        config = {k: v.value() for k, v in self.settings.items()}
        config.update(rate=int(self.rate.currentText()), continuous=self.continuous.isChecked(), band=(low, high))
        self.worker = InvestigationWorker(self.root, {k: v.text() for k, v in self.fields.items()}, config)
        self.events, self.event_offset, self.last_metrics = [], 0, None
        self.graphs.history, self.graphs.metrics = [], None
        self.graphs.update()
        self.levels.setText('RMS: —  |  Peak: —  |  Monitored band: —')
        self.detail.clear()
        self.capture_status = 'INACTIVE'
        self.closing = False
        self.worker.start()
        self.experiments.rendered = None
        self.setup.setEnabled(False)
        self.render_events()
        self.tabs.setCurrentIndex(1)

    def start_microphone(self):
        if not self.worker or not self.worker.is_alive() or self.source or self.permission_pending or self.closing:
            return
        try:
            if not microphone_usage_declared():
                self.capture_status = ('PERMISSION REQUIRED — macOS launcher must declare NSMicrophoneUsageDescription. '
                                       'See docs/paranormal_lab.md; microphone has not been opened.')
                return
            app = QApplication.instance()
            permission = QMicrophonePermission()
            status = app.checkPermission(permission)
            if status == Qt.PermissionStatus.Undetermined:
                self.permission_pending = True
                self.capture_status = 'PERMISSION REQUIRED — awaiting microphone consent'
                app.requestPermission(permission, self.permission_result)
            elif status == Qt.PermissionStatus.Granted:
                self.open_microphone()
            else:
                self.capture_status = 'PERMISSION REQUIRED — allow microphone access in macOS System Settings → Privacy & Security.'
        except Exception as exc:
            self.capture_status = f'ERROR — {exc}'

    def permission_result(self, permission):
        self.permission_pending = False
        if self.closing or not self.worker or not self.worker.is_alive():
            return
        if permission.status() == Qt.PermissionStatus.Granted:
            self.open_microphone()
        else:
            self.capture_status = 'PERMISSION REQUIRED — microphone access was not granted.'

    def open_microphone(self):
        try:
            from PyQt6.QtMultimedia import QMediaDevices, QAudioFormat, QAudioSource
            devices = [d for d in QMediaDevices.audioInputs()
                       if any(name in d.description().lower() for name in ('macbook', 'built-in', 'internal microphone'))]
            if not devices:
                self.capture_status = 'UNAVAILABLE — no identifiable built-in microphone. External inputs are not selected.'
                return
            device = devices[0]
            fmt = QAudioFormat()
            fmt.setSampleRate(self.worker.config['rate'])
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                self.capture_status = 'UNAVAILABLE — selected PCM format unsupported; end session and choose another sample rate.'
                return
            self.source = QAudioSource(device, fmt, self)
            self.source.setBufferSize(self.worker.config['rate'] * 2)
            self.source.stateChanged.connect(self.audio_state)
            self.worker.submit('device', device.description())
            self.io = self.source.start()
            if self.io is None:
                raise RuntimeError('Audio input could not start')
            self.io.readyRead.connect(self.read_audio)
            self.capture_status = 'INACTIVE — awaiting audio from ' + device.description()
        except Exception as exc:
            self.capture_status = f'ERROR — {exc}'
            self.end_session()

    def audio_state(self, state):
        if self.source and self.source.error().value != 0:
            self.capture_status = f'ERROR — audio backend: {self.source.error().name}'
            self.worker.failure = self.capture_status
            QTimer.singleShot(0, self.end_session)
        elif self.source and state.name == 'IdleState' and self.last_metrics is not None:
            self.capture_status = 'ERROR — audio input stalled or overran; ending session to avoid an unreported gap.'
            self.worker.failure = self.capture_status
            QTimer.singleShot(0, self.end_session)

    def read_audio(self):
        if self.io and self.worker and not self.closing:
            data = bytes(self.io.readAll())
            if data:
                self.capture_status = 'ACTIVE — built-in microphone'
                if not self.worker.submit('audio', (data, now())):
                    self.end_session()

    def calibrate_baseline(self):
        if self.worker and self.worker.is_alive() and not self.closing:
            self.worker.submit('calibrate', self.worker.config['baseline_seconds'])

    def mark_event(self):
        if self.worker and self.worker.is_alive() and not self.closing:
            self.worker.submit('marker', dict(timestamp=now(), observation=self.observation.text(), notes=self.notes.text()))
            self.observation.clear()
            self.notes.clear()

    def end_session(self):
        if self.closing:
            return
        self.ending = True
        if self.source:
            self.read_audio()
        self.sensors.shutdown()
        self.review.stop_playback()
        self.closing = True
        source, self.source = self.source, None
        self.io = None
        if source:
            source.stop()
            source.deleteLater()
        self.finish_end_session()

    def finish_end_session(self):
        # Let in-flight derived/synthetic writers finish before the final integrity report.
        if not self.experiments.shutdown() or not self.review.shutdown():
            QTimer.singleShot(100, self.finish_end_session)
            return
        if self.worker:
            self.worker.stopping.set()

    def shutdown(self):
        self.end_session()
        return (not self.worker or not self.worker.is_alive()) and self.review.shutdown() and self.experiments.shutdown()

    def log_playback(self, value):
        if self.worker and self.worker.is_alive() and not self.closing:
            self.worker.submit('playback', value)

    def load_saved_session(self, directory):
        if self.worker and self.worker.is_alive():
            return
        self.worker = None
        self.events = sorted(records(Path(directory) / 'events.jsonl'), key=lambda e: e['timestamp'])
        self.review_directory = str(directory)
        self.render_events()
        self.status.setText('INACTIVE — reviewing saved session: ' + str(directory))

    def review_selected(self):
        selected = self.table.selectedItems()
        if not selected or not self.review_directory:
            return
        event = selected[0].data(Qt.ItemDataRole.UserRole)
        if self.review.set_session(self.review_directory, bool(self.worker and self.worker.is_alive())):
            for index in range(self.review.events.count()):
                if self.review.events.itemData(index)['id'] == event['id']:
                    self.review.events.setCurrentIndex(index)
                    break
            self.tabs.setCurrentIndex(4)

    def compare_events(self):
        rows = sorted({item.row() for item in self.table.selectedItems()})
        if not rows:
            return
        selected = [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in rows]
        data = []
        for event in selected:
            data.append({'selected': event['id'], 'nearby': [
                {'id': item['event']['id'], 'type': item['event']['type'], 'delta_seconds': item['delta_seconds']}
                for item in correlations(self.events, event)]})
        self.detail.setPlainText('Temporal proximity does not establish causation.\n' + json.dumps(data, indent=2))

    def refresh(self):
        live = bool(self.worker and self.worker.is_alive())
        active = live and not self.closing
        self.sensors.refresh()
        self.review.active_session = live
        self.sensor_summary.setText("Camera: " + self.sensors.camera_status + "\nWi-Fi cache: " + (self.worker.snapshot.get("network", {}).get("state", "INACTIVE") if self.worker else "INACTIVE") + " • Bluetooth: UNAVAILABLE — strictly passive API not verified")
        self.start.setEnabled(not live and not self.permission_pending and not self.sensors.permission_pending and self.review.job is None and self.experiments.job is None)
        self.stop.setEnabled(active)
        self.mark.setEnabled(active)
        self.microphone.setEnabled(active and self.source is None and not self.permission_pending)
        self.calibrate.setEnabled(active)
        elapsed = ((self.worker.ended_at or time.monotonic()) - self.worker.started_at) if self.worker else 0
        self.clock.setText(f'{now()}  |  Investigation duration: {elapsed:.1f} s  |  Events: {len(self.events)}')
        if not self.worker:
            return
        s = self.worker.snapshot
        if not live:
            self.setup.setEnabled(True)
            if self.source or self.sensors.camera:
                self.end_session()
        recording = 'ACTIVE' if s.get('recording') and live else 'INACTIVE'
        mic = self.capture_status if active else s['state']
        self.status.setText(f'Microphone: {mic}  |  Continuous recording: {recording}\n{s["detail"]}\n{s.get("directory", "")}')
        metrics = s.get('metrics')
        if metrics and metrics is not self.last_metrics:
            self.last_metrics = metrics
            self.graphs.push(metrics, self.worker.config['rate'])
            self.levels.setText(f'RMS: {metrics["rms_dbfs"]:.1f} dBFS  |  Peak: {metrics["peak_dbfs"]:.1f} dBFS  |  '
                                f'Band: {metrics["band_dbfs"]:.1f} dBFS  |  Dominant: {metrics["dominant_hz"]:.1f} Hz')
        if s.get('calibrating'):
            self.baseline_label.setText(f'BASELINE: calibrating — {s["calibration_seconds"]:.1f} s of captured audio')
        elif s.get('baseline'):
            b = s['baseline']
            self.baseline_label.setText(f'BASELINE: {b["duration"]:.1f} s  |  RMS {b["rms_dbfs"]:.1f} dBFS  |  Peak {b["peak_dbfs"]:.1f} dBFS')
        else:
            self.baseline_label.setText('BASELINE: not established; automatic event detection is inactive.')
        if s.get('directory'):
            if self.review_directory != s['directory'] and self.review.job is None:
                self.review_directory = s['directory']
                self.review.set_session(s['directory'], live)
            path = Path(s['directory']) / 'events.jsonl'
            try:
                with path.open(encoding='utf-8') as stream:
                    stream.seek(self.event_offset)
                    added = []
                    while True:
                        line = stream.readline()
                        if not line or not line.endswith('\n'):
                            break
                        added.append(json.loads(line))
                        self.event_offset = stream.tell()
                if added:
                    self.events.extend(added)
                    self.events.sort(key=lambda e: e['timestamp'])
                    self.render_events()
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as exc:
                self.status.setText(f'ERROR reading timeline: {exc}')

    def render_events(self, *_):
        self.detail.clear()
        self.table.setRowCount(0)
        self.plot.events = self.events
        self.plot.update()
        for event in self.events:
            if self.filter.currentText() not in ('All events', event['type']):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, key in enumerate(('id', 'timestamp', 'type', 'observation')):
                value = ('Recorded event.' if key == 'observation' and self.review.blind.isChecked() else event[key])
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, event)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    def show_event(self):
        selected = self.table.selectedItems()
        if selected:
            event = selected[0].data(Qt.ItemDataRole.UserRole)
            if self.review.blind.isChecked():
                from ..blind_review import neutral_event
                event = neutral_event(event)
            self.detail.setPlainText(json.dumps(event, indent=2))
