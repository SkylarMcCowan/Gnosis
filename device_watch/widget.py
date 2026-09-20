"""Gnosis enrollment and receiver controls."""
import json
import os
from pathlib import Path
from datetime import datetime
import time
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                            QLineEdit, QPushButton, QSpinBox, QTableWidget,
                            QTableWidgetItem, QFileDialog, QMessageBox)
from .server import Registry, Receiver


class DeviceWatchWidget(QWidget):
    def __init__(self, state_path=None):
        super().__init__()
        layout = QVBoxLayout(self)
        intro = QLabel('Enroll each device, copy its configuration and companion.py to it, then run the sender with --accept. Collects hostname, OS/Python versions and sender uptime only. Online means a heartbeat arrived within 90 seconds. Status resets when Gnosis restarts.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.registry = None
        self.receiver = None
        try:
            self.registry = Registry(state_path or Path(__file__).resolve().parent / 'state' / 'devices.json')
            self.receiver = Receiver(self.registry)
        except (OSError, ValueError) as exc:
            layout.addWidget(QLabel(f'Cannot load enrollment registry: {exc}'))
            return
        form = QFormLayout()
        self.host = QLineEdit('127.0.0.1')
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8766)
        self.cert = QLineEdit()
        self.key = QLineEdit()
        self.url = QLineEdit('http://127.0.0.1:8766')
        self.name = QLineEdit()
        for label, control in [('Bind address', self.host), ('Port', self.port),
                               ('TLS certificate path (LAN)', self.cert), ('TLS private key path (LAN)', self.key),
                               ('Receiver URL reachable by devices', self.url), ('New device name', self.name)]:
            form.addRow(label, control)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.start = QPushButton('Start Receiver')
        self.stop = QPushButton('Stop Receiver')
        self.stop.setEnabled(False)
        enroll = QPushButton('Enroll & Export Config')
        revoke = QPushButton('Revoke Selected Device')
        for button in (self.start, self.stop, enroll, revoke):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel('Receiver stopped. LAN binding requires a TLS certificate and key.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Name', 'Status', 'Hostname', 'OS', 'Last heartbeat', 'Sender uptime (s)', 'Device ID'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.start.clicked.connect(self.start_receiver)
        self.stop.clicked.connect(self.stop_receiver)
        enroll.clicked.connect(self.enroll)
        revoke.clicked.connect(self.revoke)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def start_receiver(self):
        try:
            self.receiver.start(self.host.text().strip(), self.port.value(), self.cert.text().strip(), self.key.text().strip())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Receiver could not start', str(exc))
            return
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText(f'Receiver listening on {self.host.text()}:{self.port.value()}')

    def stop_receiver(self):
        self.receiver.stop()
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.status.setText('Receiver stopped. Devices cannot report until it is restarted.')
        self.refresh()

    def enroll(self):
        from urllib.parse import urlparse
        url = self.url.text().strip().rstrip('/')
        parsed = urlparse(url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment
                or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
            QMessageBox.warning(self, 'Invalid receiver URL', 'Use an HTTPS origin for LAN devices, or HTTP localhost for testing.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export private device configuration', 'sender.device-watch.json', 'JSON (*.json)')
        if not path:
            return
        config = None
        try:
            config = self.registry.enroll(self.name.text())
            config.update(server_url=url, ca_file='')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            os.chmod(path, 0o600)
        except (OSError, ValueError) as exc:
            if config:
                self.registry.revoke(config['device_id'])
            QMessageBox.warning(self, 'Enrollment failed', str(exc))
            return
        self.status.setText('Enrolled. Copy this private config and companion.py to that device. See docs/device_watch.md for TLS and launch instructions.')
        self.refresh()

    def revoke(self):
        row = self.table.currentRow()
        if row < 0:
            return
        device_id = self.table.item(row, 6).text()
        try:
            self.registry.revoke(device_id)
        except OSError as exc:
            QMessageBox.warning(self, 'Revocation failed', str(exc))
            return
        self.refresh()

    def refresh(self):
        selected = self.table.item(self.table.currentRow(), 6)
        selected_id = selected.text() if selected else None
        devices = self.registry.snapshot()
        self.table.setRowCount(len(devices))
        for row, (device_id, device) in enumerate(devices.items()):
            seen = device.get('last_seen', 0)
            status = 'Online' if seen and time.time() - seen < 90 else ('Offline' if seen else 'Awaiting sender')
            if not self.receiver.server:
                status = 'Receiver stopped'
            values = [device['name'], status, device.get('hostname', '—'),
                      ' '.join((device.get('system', ''), device.get('release', ''))),
                      datetime.fromtimestamp(seen).strftime('%Y-%m-%d %H:%M:%S') if seen else 'Never',
                      str(device.get('sender_uptime_seconds', '—')), device_id]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
            if selected_id == device_id:
                self.table.selectRow(row)

    def stop_and_cleanup(self):
        if hasattr(self, 'timer'):
            self.timer.stop()
        if self.receiver:
            self.receiver.stop()
