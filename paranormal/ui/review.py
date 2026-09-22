"""Evidence review, bounded background rendering, and independent blind annotation."""
import json
from pathlib import Path
import queue
import shutil
import threading
from PyQt6.QtCore import Qt, QTimer, QUrl, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton,
                            QComboBox, QCheckBox, QDoubleSpinBox, QLineEdit, QTextEdit,
                            QLabel, QFileDialog, QSplitter)
from ..evidence import EvidenceStore, records, safe_path
from ..audio_review import info, visualization, derive
from ..reports import generate_report
from ..blind_review import neutral_event


class BackgroundPanel(QWidget):
    """One bounded background job with GUI-thread delivery; no nested Qt event loops."""
    def __init__(self):
        super().__init__()
        self.job = None
        self.results = queue.Queue()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.poll = QTimer(self)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self.deliver)
        self.poll.start()

    def run_job(self, fn, done):
        if self.job is not None:
            self.message.setText('A background operation is still running.')
            return False
        self.message.setText('Working…')
        def run():
            try:
                self.results.put((done, fn(), None))
            except Exception as exc:
                self.results.put((done, None, str(exc)))
        self.job = threading.Thread(target=run, daemon=True, name='investigation-review')
        self.job.start()
        return True

    def deliver(self):
        try:
            callback, result, error = self.results.get_nowait()
        except queue.Empty:
            return
        self.job = None
        if error:
            self.message.setText('ERROR — ' + error)
        else:
            self.message.setText('Ready.')
            try:
                callback(result)
            except Exception as exc:
                self.message.setText('ERROR — ' + str(exc))

    def shutdown(self):
        return self.job is None or not self.job.is_alive()


def number(low, high, value, decimals=2):
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setValue(value)
    return spin


class ReviewGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.data = None
        self.setMinimumHeight(190)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#10141e'))
        p.setPen(QColor('#b8c3d6'))
        if not self.data:
            p.drawText(10, 20, 'Select an audio section to view its waveform and spectrogram.')
            return
        d = self.data
        p.drawText(10, 18, f'ORIGINAL • {d["start"]:.2f}–{d["end"]:.2f} s • frequency 0–{d["rate"]/2000:g} kHz ↑')
        values = d['waveform']
        p.setPen(QPen(QColor('#8b79f6'), 1))
        w = self.width()
        for i, v in enumerate(values):
            x = int(i * w / max(1, len(values)))
            p.drawLine(x, int(65 - v * 35), x, int(65 + v * 35))
        columns = d['spectrogram']
        height = max(1, self.height() - 110)
        for x, column in enumerate(columns):
            for y, value in enumerate(column):
                strength = max(0, min(1, (value + 100) / 100))
                color = QColor.fromHsvF(.7 - strength * .5, .7, .12 + strength * .88)
                p.fillRect(int(x * w / len(columns)), int(110 + height * (1 - (y + 1) / len(column))),
                           int(w / len(columns)) + 1, int(height / len(column)) + 1, color)


class ReviewPanel(BackgroundPanel):
    def __init__(self, on_playback=None):
        super().__init__()
        self.directory = None
        self.event = None
        self.sources = []
        self.derived = None
        self.selection_generation = 0
        self.player = None
        self.audio_output = None
        self.on_playback = on_playback
        self.bookmarks = []
        self.active_session = False
        self.on_session_open = None
        self.reload_pending = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.blind = QCheckBox('BLIND REVIEW — neutral event identifiers; prior interpretations hidden')
        self.blind.setChecked(True)
        self.blind.toggled.connect(self.select_event)
        top.addWidget(self.blind)
        self.open_button = QPushButton('Open saved session')
        self.open_button.clicked.connect(self.open_session)
        top.addWidget(self.open_button)
        reload_button = QPushButton('Refresh evidence list')
        reload_button.clicked.connect(lambda: self.set_session(self.directory, self.active_session) if self.directory else None)
        top.addWidget(reload_button)
        layout.addLayout(top)
        self.events = QComboBox()
        self.events.currentIndexChanged.connect(self.select_event)
        layout.addWidget(self.events)
        self.observed = QLabel('No session selected.')
        self.observed.setWordWrap(True)
        layout.addWidget(self.observed)
        self.files = QComboBox()
        self.files.currentIndexChanged.connect(self.select_file)
        layout.addWidget(self.files)
        self.evidence_info = QLabel('Original evidence hash: —')
        self.evidence_info.setWordWrap(True)
        layout.addWidget(self.evidence_info)
        derived_row = QHBoxLayout()
        self.derived_files = QComboBox()
        derived_row.addWidget(QLabel('Saved derived copies:'))
        derived_row.addWidget(self.derived_files, 1)
        play_derived = QPushButton('Play saved DERIVED')
        play_derived.clicked.connect(self.play_saved_derived)
        derived_row.addWidget(play_derived)
        layout.addLayout(derived_row)
        self.graph = ReviewGraph()
        layout.addWidget(self.graph)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMaximumHeight(220)
        layout.addWidget(self.image)
        range_row = QHBoxLayout()
        self.begin = number(0, 1e8, 0, 3)
        self.end = number(0, 1e8, 1, 3)
        range_row.addWidget(QLabel('Section start / end (seconds; up to 120 s):'))
        range_row.addWidget(self.begin)
        range_row.addWidget(self.end)
        zoom = QPushButton('View / zoom section')
        zoom.clicked.connect(self.load_graph)
        range_row.addWidget(zoom)
        layout.addLayout(range_row)
        controls = QHBoxLayout()
        self.speed = number(.25, 4, 1)
        self.gain = number(-36, 24, 0)
        self.lowpass = number(0, 22000, 0, 0)
        self.highpass = number(0, 22000, 0, 0)
        self.reverse = QCheckBox('Reverse')
        self.loop = QCheckBox('Loop section')
        for label, control in [('Speed ×', self.speed), ('Gain dB', self.gain), ('Low-pass Hz (0=off)', self.lowpass), ('High-pass Hz', self.highpass)]:
            controls.addWidget(QLabel(label))
            controls.addWidget(control)
        controls.addWidget(self.reverse)
        controls.addWidget(self.loop)
        layout.addLayout(controls)
        buttons = QHBoxLayout()
        for label, fn in [('Play ORIGINAL', self.play_original), ('Render & play DERIVED', self.render_derived),
                          ('Stop', self.stop_playback), ('Export selected clip', self.export_clip)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        notes = QHBoxLayout()
        form = QFormLayout()
        self.interpretation = QLineEdit()
        self.hypothesis = QLineEdit()
        self.confidence = QComboBox()
        self.confidence.addItems(['Unset', '1', '2', '3', '4', '5'])
        self.tags = QLineEdit()
        self.tags.setPlaceholderText('VOICE, MECHANICAL, ENVIRONMENTAL, UNKNOWN, or custom tags')
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(75)
        form.addRow('Investigator interpretation', self.interpretation)
        form.addRow('Hypothesis (separate)', self.hypothesis)
        form.addRow('Confidence 1–5', self.confidence)
        form.addRow('Tags (comma separated)', self.tags)
        form.addRow('Notes', self.notes)
        notes.addLayout(form)
        layout.addLayout(notes)
        footer = QHBoxLayout()
        self.bookmark_time = number(0, 1e8, 0, 3)
        footer.addWidget(QLabel('Bookmark (seconds):'))
        footer.addWidget(self.bookmark_time)
        self.bookmark_list = QComboBox()
        self.bookmark_list.currentIndexChanged.connect(self.jump_bookmark)
        footer.addWidget(self.bookmark_list)
        for label, fn in [('Add bookmark', self.add_bookmark), ('Save annotation', self.save_annotation),
                          ('Verify hashes', self.verify), ('Generate report', self.report)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            footer.addWidget(b)
        layout.addLayout(footer)
        layout.addWidget(self.message)

    def open_session(self):
        if self.active_session:
            self.message.setText('End the active investigation before opening another session.')
            return
        directory = QFileDialog.getExistingDirectory(self, 'Open investigation session')
        if directory:
            try:
                if self.set_session(directory) and self.on_session_open:
                    self.on_session_open(directory)
            except Exception as exc:
                self.message.setText('ERROR — ' + str(exc))

    def set_session(self, directory, active=False):
        if self.job is not None:
            return False
        metadata = json.loads((Path(directory) / 'session.json').read_text())
        self.directory = Path(directory)
        self.active_session = active
        self.stop_playback()
        events = records(self.directory / 'events.jsonl')
        known = {evidence for e in events for evidence in ([e['evidence']] if isinstance(e.get('evidence'), str) else e.get('evidence', []))}
        for record in EvidenceStore(directory).manifest():
            if record['file'] not in known and record['file'].endswith(('.wav', '.png')) and record['role'] in ('original', 'legacy', 'synthetic'):
                events.append(dict(id=f'RECORDING {len(events) + 1:03d}', observation='Saved recording.', evidence=record['file'], synthetic=record['role'] == 'synthetic'))
        # Legacy continuous recordings may not have a manifest yet.
        all_files = {evidence for e in events for evidence in ([e['evidence']] if isinstance(e.get('evidence'), str) else e.get('evidence', []))}
        for filename in metadata.get('continuous_recordings', []):
            if filename not in all_files and not active:
                events.append(dict(id=f'RECORDING {len(events) + 1:03d}', observation='Continuous recording.', evidence=filename))
        current = self.events.currentData()
        current_id = current.get('id') if current else None
        self.events.blockSignals(True)
        self.events.clear()
        for event in events:
            self.events.addItem(event['id'], event)
        index = next((i for i, e in enumerate(events) if e['id'] == current_id), 0)
        self.events.setCurrentIndex(index)
        self.events.blockSignals(False)
        self.select_event()
        return True

    def select_event(self, *_):
        self.stop_playback()
        self.selection_generation += 1
        self.event = self.events.currentData()
        self.files.clear()
        self.image.clear()
        self.graph.data = None
        self.graph.update()
        self.bookmarks = []
        self.bookmark_list.clear()
        self.derived_files.clear()
        for field in (self.interpretation, self.hypothesis, self.tags):
            field.clear()
        self.notes.clear()
        self.confidence.setCurrentIndex(0)
        if not self.event:
            return
        event = neutral_event(self.event) if self.blind.isChecked() else self.event
        self.observed.setText('SIMULATED RADIO SWEEP — NOT RF RECEPTION • synthetic local audio' if self.event.get('synthetic') else str(event.get('observation', 'Recorded event.')))
        evidence = self.event.get('evidence', [])
        if isinstance(evidence, str):
            evidence = [evidence]
        for i, filename in enumerate(evidence):
            self.files.addItem(f'Original evidence {i + 1}' if self.blind.isChecked() else filename, filename)
        for record in EvidenceStore(self.directory).manifest():
            if record['role'] == 'derived' and any(src.get('file') in evidence for src in record.get('sources', [])):
                self.derived_files.addItem('Derived copy ' + str(self.derived_files.count() + 1) if self.blind.isChecked() else record['file'], record['file'])
        if not self.blind.isChecked():
            a = EvidenceStore(self.directory).annotations().get(self.event['id'], {})
            self.interpretation.setText(a.get('interpretation', ''))
            self.hypothesis.setText(a.get('hypothesis', ''))
            self.confidence.setCurrentIndex(a.get('confidence') or 0)
            self.tags.setText(', '.join(a.get('tags', [])))
            self.notes.setPlainText(a.get('notes', ''))
            self.bookmarks = a.get('bookmarks', [])
            self.update_bookmarks()

    def selected_path(self):
        filename = self.files.currentData()
        return safe_path(self.directory, filename) if self.directory and filename else None

    def deliver(self):
        super().deliver()
        if self.reload_pending and self.job is None:
            self.reload_pending = False
            self.select_file()

    def select_file(self, *_):
        if self.job is not None:
            self.selection_generation += 1
            self.reload_pending = True
            return
        self.stop_playback()
        self.selection_generation += 1
        self.derived = None
        path = self.selected_path()
        if path is None:
            return
        try:
            record = next((r for r in EvidenceStore(self.directory).manifest() if r['file'] == self.files.currentData()), None)
            self.evidence_info.setText(('SHA-256: ' + record['sha256'] + ' • registered: ' + record['registered_at']) if record else 'UNHASHED LEGACY EVIDENCE — capture-time integrity unavailable')
            if path.suffix.lower() == '.wav':
                metadata = info(path)
                self.begin.setValue(0)
                self.end.setValue(min(30, metadata['duration']))
                self.image.clear()
                self.load_graph()
            elif path.suffix.lower() == '.png':
                generation = self.selection_generation
                self.run_job(lambda: QImage(str(path)), lambda image: self.show_image(image, generation))
        except Exception as exc:
            self.message.setText('ERROR — ' + str(exc))

    def show_image(self, image, generation):
        if generation != self.selection_generation:
            return
        if image.isNull():
            raise ValueError('Image could not be decoded')
        self.image.setPixmap(QPixmap.fromImage(image).scaled(640, 220, Qt.AspectRatioMode.KeepAspectRatio))

    def load_graph(self):
        path = self.selected_path()
        if path is None or path.suffix.lower() != '.wav':
            return
        start, end = self.begin.value(), self.end.value()
        generation = self.selection_generation
        def done(data):
            if generation == self.selection_generation:
                self.graph.data = data
                self.graph.update()
        self.run_job(lambda: visualization(path, start, end), done)

    def ensure_player(self):
        if self.player:
            return
        from PyQt6.QtMultimedia import QMediaDevices, QAudioOutput, QMediaPlayer
        devices = [d for d in QMediaDevices.audioOutputs() if any(x in d.description().lower() for x in ('macbook', 'built-in', 'internal speaker'))]
        if not devices:
            raise RuntimeError('UNAVAILABLE — no identifiable built-in audio output')
        self.audio_output = QAudioOutput(devices[0], self)
        self.audio_output.setVolume(.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self.playback_position)
        self.player.mediaStatusChanged.connect(self.media_status)
        self.player.errorOccurred.connect(lambda *_: self.message.setText('ERROR — ' + self.player.errorString()))

    def play(self, path, begin=0, end=None):
        try:
            self.ensure_player()
            metadata = info(path)
            self.play_start = int(begin * 1000)
            self.play_end = int((metadata['duration'] if end is None else end) * 1000)
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.setPlaybackRate(self.speed.value())
            self.player.setPosition(self.play_start)
            self.player.play()
            if self.on_playback:
                self.on_playback({'operation': 'Evidence review playback'})
        except Exception as exc:
            self.message.setText('ERROR — ' + str(exc))

    def media_status(self, status):
        if status.name == 'LoadedMedia':
            self.player.setPosition(self.play_start)
        elif status.name == 'EndOfMedia' and self.loop.isChecked():
            self.player.setPosition(self.play_start)
            self.player.play()

    def playback_position(self, position):
        if position >= self.play_end:
            if self.loop.isChecked():
                self.player.setPosition(self.play_start)
            else:
                self.player.pause()

    def play_original(self):
        path = self.selected_path()
        if path and path.suffix.lower() == '.wav':
            if self.end.value() <= self.begin.value():
                self.message.setText('Select a valid playback section.')
                return
            self.play(path, self.begin.value(), self.end.value())

    def stop_playback(self):
        if self.player:
            self.player.stop()

    def render_derived(self, export=None):
        source = self.files.currentData()
        if not source or not source.lower().endswith('.wav'):
            return
        directory = self.directory
        generation = self.selection_generation
        options = dict(start=self.begin.value(), end=self.end.value(), gain_db=self.gain.value(),
                       reverse=self.reverse.isChecked(), lowpass=self.lowpass.value(), highpass=self.highpass.value())
        def work():
            filename = derive(directory, source, **options)
            if export:
                with safe_path(directory, filename).open('rb') as src, Path(export).open('xb') as dst:
                    shutil.copyfileobj(src, dst)
            return filename
        def done(filename):
            if generation == self.selection_generation and self.directory == directory:
                self.derived = filename
                self.derived_files.addItem('Derived copy ' + str(self.derived_files.count() + 1), filename)
                if export:
                    self.message.setText('Export saved; original preserved and processing logged in the session.')
                else:
                    self.play(safe_path(directory, filename))
                    self.message.setText('Playing DERIVED copy. Play ORIGINAL provides an immediate unprocessed comparison.')
        self.run_job(work, done)

    def play_saved_derived(self):
        filename = self.derived_files.currentData()
        if filename and self.directory:
            self.play(safe_path(self.directory, filename))

    def update_bookmarks(self):
        self.bookmark_list.blockSignals(True)
        self.bookmark_list.clear()
        for bookmark in self.bookmarks:
            self.bookmark_list.addItem(f'{bookmark["seconds"]:.3f} s', bookmark)
        self.bookmark_list.blockSignals(False)

    def jump_bookmark(self, *_):
        bookmark = self.bookmark_list.currentData()
        if not bookmark:
            return
        for i in range(self.files.count()):
            if self.files.itemData(i) == bookmark.get('file'):
                self.files.setCurrentIndex(i)
                break
        self.begin.setValue(bookmark['seconds'])
        path = self.selected_path()
        if path:
            try:
                self.end.setValue(min(info(path)['duration'], bookmark['seconds'] + 10))
            except Exception as exc:
                self.message.setText('ERROR — ' + str(exc))

    def export_clip(self):
        if self.selected_path() is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export selected clip (new file)', '', 'WAV (*.wav)')
        if path:
            self.render_derived(export=path)

    def add_bookmark(self):
        path = self.selected_path()
        if path is None or path.suffix.lower() != '.wav':
            return
        try:
            stamp = self.bookmark_time.value()
            if stamp > info(path)['duration']:
                raise ValueError('Bookmark is beyond the recording')
            self.bookmarks.append(dict(file=self.files.currentData(), seconds=stamp))
            self.update_bookmarks()
            self.message.setText(f'{len(self.bookmarks)} bookmark(s); Save annotation to persist them.')
        except Exception as exc:
            self.message.setText('ERROR — ' + str(exc))

    def save_annotation(self):
        if not self.directory or not self.event:
            return
        directory, event_id = self.directory, self.event['id']
        values = dict(interpretation=self.interpretation.text(), hypothesis=self.hypothesis.text(),
                      confidence=self.confidence.currentIndex() or None, notes=self.notes.toPlainText(),
                      tags=[t.strip() for t in self.tags.text().split(',') if t.strip()],
                      bookmarks=list(self.bookmarks), blind=self.blind.isChecked())
        self.run_job(lambda: EvidenceStore(directory).annotate(event_id, **values),
                     lambda _: self.message.setText('Independent investigator annotation saved. Observation unchanged.'))

    def verify(self):
        if self.directory:
            store = EvidenceStore(self.directory)
            blind = self.blind.isChecked()
            self.run_job(store.verify, lambda result: self.message.setText(
                ('Integrity results: ' + ', '.join(v['status'] for v in result)) if blind else json.dumps(result)))

    def report(self):
        if not self.directory:
            return
        if self.active_session:
            self.message.setText('End the investigation to generate a finalized report.')
            return
        directory = self.directory
        self.run_job(lambda: generate_report(directory), lambda path: self.message.setText('Report saved: ' + path))

    def shutdown(self):
        self.stop_playback()
        return super().shutdown()
