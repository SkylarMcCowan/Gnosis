"""A compact voice session panel that leaves the chat transcript visible."""
import math

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout


class VoiceOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.phase = 'Listening'
        self.level = 0.0
        self.tick = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._animate)

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _animate(self):
        self.tick += 0.12
        self.level *= 0.93
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        listening = self.phase in {'Listening', 'Calibrating microphone'}
        color = QColor('#3ecf8e' if listening else '#9d85ff')
        if self.phase in {'Microphone muted', 'Voice conversation ended'}:
            color = QColor('#797986')
        pulse = self.level if listening else 0.15 + 0.12 * math.sin(self.tick)
        painter.setPen(Qt.PenStyle.NoPen)
        glow = QColor(color)
        glow.setAlpha(35)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(4 - pulse * 3, 4 - pulse * 3, 56 + pulse * 6, 56 + pulse * 6))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(12, 12, 40, 40))
        painter.setPen(QPen(QColor('#ffffff'), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(5):
            height = 5 + (7 + pulse * 18) * abs(math.sin(self.tick + i * 0.8))
            x = 20 + i * 6
            painter.drawLine(int(x), int(32 - height / 2), int(x), int(32 + height / 2))


class VoicePanel(QFrame):
    mute_requested = pyqtSignal(bool)
    interrupt_requested = pyqtSignal()
    end_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('toolbar')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        top = QHBoxLayout()
        self.orb = VoiceOrb(self)
        top.addWidget(self.orb)
        labels = QVBoxLayout()
        title = QLabel('Voice conversation')
        title.setStyleSheet('font-weight: bold; font-size: 14px;')
        labels.addWidget(title)
        self.status = QLabel('Listening')
        self.status.setWordWrap(True)
        labels.addWidget(self.status)
        self.detail = QLabel('Local recognition · System voice · Transcript stays below')
        self.detail.setObjectName('mutedLabel')
        self.detail.setWordWrap(True)
        labels.addWidget(self.detail)
        top.addLayout(labels, 1)
        layout.addLayout(top)
        controls = QHBoxLayout()
        self.mute_button = QPushButton('Mute mic')
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self._mute)
        controls.addWidget(self.mute_button)
        self.interrupt_button = QPushButton('Interrupt && listen')
        self.interrupt_button.setToolTip('Stop the reply, then listen for your next turn')
        self.interrupt_button.clicked.connect(self.interrupt_requested)
        controls.addWidget(self.interrupt_button)
        self.settings_button = QPushButton('Voice settings…')
        self.settings_button.clicked.connect(self.settings_requested)
        controls.addWidget(self.settings_button)
        controls.addStretch()
        self.end_button = QPushButton('End voice')
        self.end_button.clicked.connect(self.end_requested)
        controls.addWidget(self.end_button)
        layout.addLayout(controls)
        self.hide()

    def _mute(self, muted):
        self.mute_button.setText('Unmute mic' if muted else 'Mute mic')
        self.mute_requested.emit(muted)

    def set_phase(self, phase):
        self.status.setText(phase)
        self.orb.phase = phase
        self.orb.update()
        self.interrupt_button.setEnabled(phase not in {'Listening', 'Microphone muted', 'Voice conversation ended', 'Calibrating microphone', 'Transcribing'})

    def set_level(self, level):
        self.orb.level = level

    def reset(self):
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(False)
        self.mute_button.setText('Mute mic')
        self.mute_button.blockSignals(False)
        self.mute_button.setEnabled(True)
        self.end_button.setEnabled(True)
