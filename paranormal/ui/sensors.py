"""User-initiated camera and passive cache controls; never requests location."""
import time
from PyQt6.QtCore import Qt, QCameraPermission
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QApplication
from ..permissions import usage_declared
from ..session import now
from ..bluetooth_monitor import status as bluetooth_status


class SensorPanel(QWidget):
    def __init__(self, lab):
        super().__init__()
        self.lab = lab
        self.camera = None
        self.capture = None
        self.sink = None
        self.permission_pending = False
        self.camera_status = 'INACTIVE'
        self.network_enabled = False
        self.last_preview = 0
        self.last_sample = 0
        self.generation = 0
        layout = QVBoxLayout(self)
        text = QLabel('Camera access is requested only when you start the camera. Frames are saved locally for change analysis.\n'
                      'Wi-Fi reads only the existing macOS scan cache; it never initiates scans, probes or connections.\n'
                      'No location permission is requested. Redacted identifiers remain unknown. Cache freshness is unknown.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.status = QLabel('Camera: INACTIVE')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview = QLabel('Camera preview is inactive.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.start = QPushButton('Start built-in camera')
        self.start.clicked.connect(self.start_camera)
        row.addWidget(self.start)
        self.stop = QPushButton('Stop camera')
        self.stop.clicked.connect(self.stop_camera)
        row.addWidget(self.stop)
        self.wifi = QCheckBox('Observe existing Wi-Fi cache (every 15 seconds)')
        self.wifi.toggled.connect(self.toggle_network)
        row.addWidget(self.wifi)
        layout.addLayout(row)
        self.environment = QLabel()
        self.environment.setWordWrap(True)
        layout.addWidget(self.environment)
        self.bt = QLabel('BLUETOOTH OBSERVATION — ' + bluetooth_status()['detail'])
        self.bt.setWordWrap(True)
        layout.addWidget(self.bt)

    def active(self):
        return self.lab.worker and self.lab.worker.is_alive() and not self.lab.closing

    def set_state(self, state):
        self.camera_status = state
        if self.active():
            self.lab.worker.submit('sensor', ('camera', state))

    def start_camera(self):
        if not self.active() or self.camera or self.permission_pending:
            return
        try:
            if not usage_declared('NSCameraUsageDescription'):
                self.set_state('PERMISSION REQUIRED — restart using ./run_gui.sh for the camera usage declaration.')
                return
            app = QApplication.instance()
            permission = QCameraPermission()
            state = app.checkPermission(permission)
            if state == Qt.PermissionStatus.Undetermined:
                self.permission_pending = True
                self.set_state('PERMISSION REQUIRED — awaiting camera consent')
                generation = self.generation
                def result(permission):
                    self.permission_pending = False
                    if generation != self.generation or not self.active():
                        return
                    if permission.status() == Qt.PermissionStatus.Granted:
                        self.open_camera()
                    else:
                        self.set_state('PERMISSION REQUIRED — camera consent was denied.')
                app.requestPermission(permission, result)
            elif state == Qt.PermissionStatus.Granted:
                self.open_camera()
            else:
                self.set_state('PERMISSION REQUIRED — enable camera for Gnosis in macOS Privacy & Security.')
        except Exception as exc:
            self.set_state('ERROR — ' + str(exc))

    def open_camera(self):
        try:
            from PyQt6.QtMultimedia import QCamera, QMediaDevices, QMediaCaptureSession, QVideoSink
            devices = [d for d in QMediaDevices.videoInputs() if any(x in d.description().lower() for x in ('facetime hd', 'built-in', 'macbook'))]
            if not devices:
                self.set_state('UNAVAILABLE — no identifiable built-in Mac camera.')
                return
            self.last_sample = self.last_preview = 0
            self.lab.worker.submit('camera_device', devices[0].description())
            self.camera = QCamera(devices[0], self)
            self.capture = QMediaCaptureSession(self)
            self.sink = QVideoSink(self)
            self.capture.setCamera(self.camera)
            self.capture.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self.frame)
            self.camera.errorOccurred.connect(self.camera_error)
            self.camera.start()
            self.set_state('INACTIVE — awaiting camera frames: ' + devices[0].description())
        except Exception as exc:
            self.camera_error(None, str(exc))

    def camera_error(self, error, message):
        self.stop_camera()
        self.set_state('ERROR — ' + message)

    def frame(self, frame):
        clock = time.monotonic()
        if not self.active() or clock - self.last_preview < .2:
            return
        self.last_preview = clock
        try:
            image = frame.toImage()
            if image.isNull():
                return
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(720, 400, Qt.AspectRatioMode.KeepAspectRatio))
            if not self.camera_status.startswith('ACTIVE'):
                self.set_state('ACTIVE — live preview / frame-difference monitoring')
            worker = self.lab.worker
            if clock - self.last_sample >= worker.config.get('frame_interval_ms', 500) / 1000 and not worker.camera_pending:
                self.last_sample = clock
                worker.camera_pending = True
                if not worker.submit('camera', (image.copy(), now(), clock)):
                    worker.camera_pending = False
                    self.lab.end_session()
        except Exception as exc:
            self.camera_error(None, str(exc))

    def toggle_network(self, enabled):
        self.network_enabled = enabled
        if self.active():
            self.lab.worker.submit('network', enabled)
            self.lab.worker.submit('sensor', ('wifi', 'ACTIVE — cache observation requested' if enabled else 'INACTIVE'))

    def stop_camera(self):
        self.generation += 1
        if self.camera:
            self.camera.stop()
            self.capture.setCamera(None)
            self.camera.deleteLater()
            self.capture.deleteLater()
            self.sink.deleteLater()
            self.camera = self.capture = self.sink = None
        self.preview.clear()
        if self.active():
            self.lab.worker.submit('camera_stop')
        self.set_state('INACTIVE')

    def refresh(self):
        active = bool(self.active())
        self.start.setEnabled(active and self.camera is None and not self.permission_pending)
        self.stop.setEnabled(self.camera is not None)
        self.wifi.setEnabled(active)
        snapshot = self.lab.worker.snapshot if self.lab.worker else {}
        self.status.setText('Camera: ' + self.camera_status + '\nDerived camera measurements: ' + str(snapshot.get('camera') or '—'))
        n = snapshot.get('network', {'state': 'INACTIVE'})
        self.environment.setText('Wi-Fi: ' + ('INACTIVE' if not self.network_enabled else n['state']) + '\n' + str(n))

    def shutdown(self):
        self.stop_camera()
        self.wifi.setChecked(False)
