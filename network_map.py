"""Visual LAN inventory, using the Hacker tab's existing discovery widget."""
import math
import json
import os
from pathlib import Path
from datetime import datetime
from device_identity import identify_device, identity_key, ROLES

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QPen, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QGraphicsScene, QGraphicsView, QGraphicsItem,
    QComboBox, QLineEdit, QMessageBox,
)


class NetworkMapPanel(QWidget):
    scan_requested = pyqtSignal(str)
    inspect_requested = pyqtSignal(str)

    def __init__(self, discovery, labels_path=None):
        super().__init__()
        self.devices = {}
        self.selected_ip = None
        self.labels_path = Path(labels_path) if labels_path else Path(__file__).resolve().parent / 'network_map_state' / 'labels.json'
        self.labels_error = None
        try:
            self.labels = json.loads(self.labels_path.read_text()) if self.labels_path.exists() else {}
            if not isinstance(self.labels, dict) or any(
                not isinstance(v, dict) or v.get('role') not in ('Automatic',) + ROLES
                or not isinstance(v.get('name'), str) for v in self.labels.values()
            ):
                raise ValueError('Invalid labels file')
        except (OSError, ValueError) as exc:
            self.labels = {}
            self.labels_error = str(exc)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Scan your subnet below, then click a device. Lines show subnet membership, "
            "not observed traffic or physical connections. Scroll to zoom; drag to pan."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.view.setMinimumHeight(240)
        self.view.setBackgroundBrush(QColor("#11151e"))
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.view)
        split.addWidget(discovery)
        layout.addWidget(split, 1)
        self.details = QLabel("No device selected. Run a subnet scan to build the map.")
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        identity_row = QHBoxLayout()
        self.role_combo = QComboBox()
        self.role_combo.addItems(('Automatic',) + ROLES)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('Friendly name (optional)')
        self.name_edit.setMaxLength(80)
        self.save_identity = QPushButton('Save Device Label')
        self.save_identity.setEnabled(False)
        identity_row.addWidget(QLabel('Device role:'))
        identity_row.addWidget(self.role_combo)
        identity_row.addWidget(self.name_edit)
        identity_row.addWidget(self.save_identity)
        layout.addLayout(identity_row)
        self.save_identity.clicked.connect(self._save_identity)
        if self.labels_error:
            warning = QLabel('Saved labels could not be loaded; saving is disabled: ' + self.labels_error)
            warning.setTextFormat(Qt.TextFormat.PlainText)
            warning.setWordWrap(True)
            layout.addWidget(warning)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("Open Port Scanner")
        self.inspect_button = QPushButton("Inspect Captured Traffic")
        self.fit_button = QPushButton("Fit Map")
        for button in (self.scan_button, self.inspect_button):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addWidget(self.fit_button)
        layout.addLayout(actions)
        self.scan_button.clicked.connect(lambda: self.scan_requested.emit(self.selected_ip))
        self.inspect_button.clicked.connect(lambda: self.inspect_requested.emit(self.selected_ip))
        self.fit_button.clicked.connect(self.fit_map)
        discovery.devices_discovered.connect(self.set_devices)
        self.scene.selectionChanged.connect(self._selection_changed)
        if hasattr(discovery, "table"):
            discovery.table.itemSelectionChanged.connect(lambda: self._table_selected(discovery.table))

    def set_devices(self, devices):
        self.devices = {device["ip"]: dict(device) for device in devices}
        self.seen_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._draw_map()

    def _draw_map(self):
        self.scene.clear()
        self.selected_ip = None
        self._selection_changed()
        hub = self.scene.addText(f"Discovered subnet\n{len(self.devices)} devices")
        hub.setDefaultTextColor(QColor("#eaeaf2"))
        hub.setPos(-70, -25)
        count = len(self.devices)
        radius = max(210, count * 32)
        for index, device in enumerate(self.devices.values()):
            angle = 2 * math.pi * index / max(count, 1)
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            edge = self.scene.addLine(0, 0, x, y, QPen(QColor("#344054")))
            edge.setZValue(-1)
            role, confidence, evidence, name = self._identity(device)
            color = {'Router': '#5b9bff', 'Firewall': '#f59e42', 'Switch': '#b394ff',
                     'Access point': '#55cddd'}.get(role, '#3ecf8e')
            node = self.scene.addRect(-100, -45, 200, 90,
                                      QPen(QColor(color)), QBrush(QColor("#192d32")))
            node.setPos(x, y)
            node.setData(0, device["ip"])
            node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            label = self.scene.addText(role + (' ?' if confidence in ('Tentative', 'Conflicting hints') else '') + '\n' + device['ip'] + '\n' + name[:24])
            label.setDefaultTextColor(QColor("#eaeaf2"))
            label.setParentItem(node)
            label.setPos(-95, -40)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            node.setToolTip(role + ' — ' + confidence + '\n' + '\n'.join(evidence))
        self.fit_map()

    def fit_map(self):
        self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30),
                            Qt.AspectRatioMode.KeepAspectRatio)

    def _table_selected(self, table):
        row = table.currentRow()
        if row < 0 or table.item(row, 0) is None:
            return
        ip = table.item(row, 0).text()
        self.scene.clearSelection()
        for item in self.scene.items():
            if item.data(0) == ip:
                item.setSelected(True)
                self.view.ensureVisible(item)
                break

    def _selection_changed(self):
        selected = self.scene.selectedItems()
        self.selected_ip = selected[0].data(0) if selected else None
        device = self.devices.get(self.selected_ip)
        self.scan_button.setEnabled(device is not None)
        self.inspect_button.setEnabled(device is not None)
        self.save_identity.setEnabled(device is not None and identity_key(device) is not None and self.labels_error is None)
        self.role_combo.setEnabled(device is not None)
        self.name_edit.setEnabled(device is not None)
        if device is None:
            self.details.setText("Select a device to inspect it. Scan results describe devices that replied to ARP discovery.")
            return
        saved = self.labels.get(identity_key(device), {})
        self.role_combo.setCurrentText(saved.get('role', 'Automatic'))
        self.name_edit.setText(saved.get('name', ''))
        role, confidence, evidence, name = self._identity(device)
        rtt = device.get("rtt_ms")
        response = f"{rtt:.1f} ms" if rtt is not None else "Unknown"
        self.details.setText(
            f"IP: {device['ip']}    MAC: {device.get('mac') or 'Unknown'}\n"
            f"Hostname: {device.get('hostname') or 'Unknown'}    Vendor: {device.get('vendor') or 'Unknown'}\n"
            f"Response: {response}    Last seen: {self.seen_at}\n"
            f"Role: {role} ({confidence})    Name: {name}\n" + '\n'.join(evidence)
        )

    def _identity(self, device):
        role, confidence, evidence = identify_device(device)
        saved = self.labels.get(identity_key(device), {})
        if saved.get('role', 'Automatic') != 'Automatic':
            role, confidence = saved['role'], 'User assigned'
            evidence = ['Manually assigned role; not independently verified.'] + evidence
        name = saved.get('name') or device.get('hostname') or device.get('vendor') or 'Unknown'
        return role, confidence, evidence, name

    def _save_identity(self):
        device = self.devices.get(self.selected_ip)
        key = identity_key(device) if device else None
        if not key or self.labels_error:
            return
        updated = dict(self.labels)
        name, role = self.name_edit.text().strip(), self.role_combo.currentText()
        if not name and role == 'Automatic':
            updated.pop(key, None)
        else:
            updated[key] = {'name': name, 'role': role}
        try:
            self.labels_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.labels_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(updated, indent=2))
            os.replace(temporary, self.labels_path)
        except OSError as exc:
            QMessageBox.warning(self, 'Could not save device label', str(exc))
            return
        self.labels = updated
        selected_ip = self.selected_ip
        self._draw_map()
        for item in self.scene.items():
            if item.data(0) == selected_ip:
                item.setSelected(True)
                break


class MapView(QGraphicsView):
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        scale = self.transform().m11() * factor
        if 0.02 <= scale <= 8:
            self.scale(factor, factor)
        event.accept()
