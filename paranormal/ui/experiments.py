"""Controlled intervals and explicitly synthetic local-source audio research."""
import json
from pathlib import Path
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QFileDialog, QCheckBox, QTextEdit
from .review import BackgroundPanel, number
from ..experiments import LABELS, compare_intervals
from ..audio_review import simulated_sweep
from ..session import now


class ExperimentPanel(BackgroundPanel):
    def __init__(self, lab):
        super().__init__()
        self.lab = lab
        self.sources = []
        self.rendered = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('CONTROLLED EXPERIMENT\n1. Establish baseline  2. Start recording  3. Label stimulus  4. Wait  5. Repeat  6. Compare rates\n'
                               'Labels describe investigator-defined intervals. Event proximity and frequency do not establish causation.'))
        row = QHBoxLayout()
        self.trial = QLineEdit()
        self.trial.setPlaceholderText('Experiment / trial name')
        self.label = QComboBox()
        self.label.addItems(LABELS)
        row.addWidget(self.trial)
        row.addWidget(self.label)
        mark = QPushButton('Start labeled interval')
        mark.clicked.connect(self.mark)
        row.addWidget(mark)
        compare = QPushButton('Compare interval rates')
        compare.clicked.connect(self.compare)
        row.addWidget(compare)
        layout.addLayout(row)
        self.results_view = QTextEdit()
        self.results_view.setReadOnly(True)
        self.results_view.setMaximumHeight(150)
        layout.addWidget(self.results_view)
        layout.addWidget(QLabel('SIMULATED RADIO SWEEP — NOT RF RECEPTION\n'
                               'Local WAV fragments only. The Mac has no AM/FM tuner. Every rendered sweep is saved as synthetic audio.\n'
                               'Playback through the built-in speakers can contaminate microphone measurements and is logged.'))
        choose = QPushButton('Choose local PCM 16-bit WAV sources')
        choose.clicked.connect(self.choose)
        layout.addWidget(choose)
        self.source_label = QLabel('No sources selected.')
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        row = QHBoxLayout()
        self.fragment = number(20, 2000, 150, 0)
        self.duration = number(1, 60, 10, 0)
        self.noise = number(-120, -12, -60, 0)
        self.fade = number(0, 1000, 10, 0)
        self.speed = number(.25, 4, 1)
        for label, widget in [('Fragment ms', self.fragment), ('Duration s', self.duration), ('Noise dBFS', self.noise), ('Crossfade ms', self.fade), ('Speed ×', self.speed)]:
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.random = QCheckBox('Random (unchecked: sequential)')
        self.random.setChecked(True)
        self.reverse = QCheckBox('Reverse fragments')
        row.addWidget(self.random)
        row.addWidget(self.reverse)
        for label, fn in [('Render & record synthetic sweep', self.render), ('Play saved sweep', self.play), ('Stop playback', self.lab.review.stop_playback)]:
            button = QPushButton(label)
            button.clicked.connect(fn)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(self.message)
        layout.addStretch()

    def active(self):
        return self.lab.worker and self.lab.worker.is_alive() and not self.lab.closing and self.lab.worker.session

    def mark(self):
        if not self.active():
            self.message.setText('Create an investigation session first.')
            return
        self.lab.worker.submit('experiment', dict(timestamp=now(), trial=self.trial.text(), label=self.label.currentText()))

    def compare(self):
        end = self.lab.worker.session.data.get('end_time') if self.lab.worker and self.lab.worker.session else None
        self.results_view.setPlainText(json.dumps(compare_intervals(self.lab.events, end or now()), indent=2))

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Choose local audio sources', '', 'WAV (*.wav)')
        if paths:
            self.sources = [Path(p) for p in paths]
            self.source_label.setText('\n'.join(p.name for p in self.sources))

    def render(self):
        if not self.active():
            self.message.setText('Create an investigation session first.')
            return
        directory = self.lab.worker.session.directory
        sources = list(self.sources)
        options = dict(fragment_ms=self.fragment.value(), duration_seconds=self.duration.value(), random_order=self.random.isChecked(),
                       reverse=self.reverse.isChecked(), noise_db=self.noise.value(), crossfade_ms=self.fade.value(), speed=self.speed.value())
        def done(filename):
            self.rendered = directory / filename
            self.message.setText('Synthetic recording saved: ' + str(self.rendered))
        self.run_job(lambda: simulated_sweep(directory, sources, **options), done)

    def play(self):
        if self.rendered:
            self.lab.review.play(self.rendered)
            self.message.setText('SIMULATED RADIO SWEEP — NOT RF RECEPTION • playing saved synthetic montage')
