"""Converter pane: local file-format conversion via CLI tools the user
already has installed - Calibre's `ebook-convert` for PDF -> EPUB, and
`ffmpeg` for video -> MP4 (H.264/AAC), the latter feeding the user's
local-only Jellyfin library after ripping movies for travel.

Binary paths are configured once in the Settings tab (auto-detected via
shutil.which as an editable suggestion only, never silently assumed) and
verified with `<tool> --version` before being trusted. Conversions never
silently fall back to a guessed path or swallow a nonzero exit code - every
failure surfaces the tool's real stderr via QMessageBox and the queue row's
status (see MEMORY: "No silent fallbacks").
"""
import json
import os
import shutil
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

import core.config as core_config

TEXT_MUTED = "#797986"
ERROR_RED = "#e5484d"
SUCCESS_GREEN = "#2fb344"

PDF_FILTER = "PDF files (*.pdf)"
VIDEO_FILTER = "Video files (*.mp4 *.mkv *.avi *.mov *.m4v *.wmv);;All files (*)"


class ConversionError(Exception):
    pass


# ----------------------------------------------------------------------
# Config - binary paths for ebook-convert / ffmpeg
# ----------------------------------------------------------------------
def _config_path():
    return os.path.join(core_config.path("converter"), "config.json")


def load_config():
    path = _config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def save_config(config):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def ebook_convert_path():
    return (load_config().get("ebook_convert_path") or "").strip() or None


def set_ebook_convert_path(path):
    config = load_config()
    config["ebook_convert_path"] = (path or "").strip()
    save_config(config)


def ffmpeg_path():
    return (load_config().get("ffmpeg_path") or "").strip() or None


def set_ffmpeg_path(path):
    config = load_config()
    config["ffmpeg_path"] = (path or "").strip()
    save_config(config)


def verify_binary(path):
    """Runs `<path> --version` and returns (ok, message). Never raises -
    callers decide how to surface failure."""
    if not path:
        return False, "No path set."
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "non-zero exit").strip()
    first_line = (result.stdout or result.stderr or "").strip().splitlines()[:1]
    return True, (first_line[0] if first_line else "OK")


# ----------------------------------------------------------------------
# Conversion functions - plain, testable without Qt
# ----------------------------------------------------------------------
def convert_pdf_to_epub(src, dst, tool_path):
    result = subprocess.run(
        [tool_path, src, dst], capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ConversionError((result.stderr or result.stdout or "unknown error").strip())


def convert_video_to_mp4(src, dst, tool_path):
    result = subprocess.run(
        [tool_path, "-y", "-i", src, "-c:v", "libx264", "-c:a", "aac", dst],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ConversionError((result.stderr or result.stdout or "unknown error").strip())


# ----------------------------------------------------------------------
# Batch worker
# ----------------------------------------------------------------------
class ConversionWorker(QThread):
    item_started = pyqtSignal(int)
    item_finished = pyqtSignal(int, bool, str)
    batch_finished = pyqtSignal()

    def __init__(self, jobs):
        """jobs: list of (src_path, dst_path, convert_fn, tool_path)."""
        super().__init__()
        self.jobs = jobs

    def run(self):
        for i, (src, dst, convert_fn, tool_path) in enumerate(self.jobs):
            self.item_started.emit(i)
            try:
                convert_fn(src, dst, tool_path)
            except ConversionError as e:
                self.item_finished.emit(i, False, str(e))
                continue
            self.item_finished.emit(i, True, "")
        self.batch_finished.emit()


# ----------------------------------------------------------------------
# Shared queue tab (Documents / Video)
# ----------------------------------------------------------------------
class _ConversionTab(QWidget):
    def __init__(self, file_filter, dest_ext, convert_fn, tool_path_getter, tool_label):
        super().__init__()
        self.file_filter = file_filter
        self.dest_ext = dest_ext
        self.convert_fn = convert_fn
        self.tool_path_getter = tool_path_getter
        self.tool_label = tool_label
        self.queue = []  # list of {"src": str, "dst": str}
        self.worker = None

        layout = QVBoxLayout(self)

        controls_row = QHBoxLayout()
        self.add_button = QPushButton("Add Files…")
        self.add_button.clicked.connect(self._add_files)
        controls_row.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self._remove_selected)
        controls_row.addWidget(self.remove_button)
        controls_row.addStretch()
        self.convert_button = QPushButton("Convert All")
        self.convert_button.clicked.connect(self._convert_all)
        controls_row.addWidget(self.convert_button)
        layout.addLayout(controls_row)

        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet(f"color: {ERROR_RED};")
        layout.addWidget(self.warning_label)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["File", "Status"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        self.refresh_availability()

    def refresh_availability(self):
        tool_path = self.tool_path_getter()
        if tool_path:
            self.warning_label.setText("")
            self.convert_button.setEnabled(len(self.queue) > 0)
        else:
            self.warning_label.setText(
                f"Set the {self.tool_label} path in Settings before converting."
            )
            self.convert_button.setEnabled(False)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", self.file_filter)
        for src in paths:
            dst = os.path.splitext(src)[0] + self.dest_ext
            self.queue.append({"src": src, "dst": dst})
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(src))
            self.table.setItem(row, 1, QTableWidgetItem("Queued"))
        self.refresh_availability()

    def _remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.queue[row]
        self.refresh_availability()

    def _convert_all(self):
        tool_path = self.tool_path_getter()
        if not tool_path:
            self.refresh_availability()
            return
        jobs = []
        for item in self.queue:
            if os.path.exists(item["dst"]):
                reply = QMessageBox.question(
                    self, "File exists",
                    f"{item['dst']} already exists. Overwrite it?",
                )
                if reply != QMessageBox.StandardButton.Yes:
                    continue
            jobs.append((item["src"], item["dst"], self.convert_fn, tool_path))
        if not jobs:
            return
        self.add_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.convert_button.setEnabled(False)
        self.worker = ConversionWorker(jobs)
        self.worker.item_started.connect(self._on_item_started)
        self.worker.item_finished.connect(self._on_item_finished)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.start()

    def _on_item_started(self, row):
        self.table.setItem(row, 1, QTableWidgetItem("Converting…"))

    def _on_item_finished(self, row, success, message):
        item = QTableWidgetItem("Done" if success else f"Failed: {message}")
        item.setForeground(QColor(SUCCESS_GREEN if success else ERROR_RED))
        self.table.setItem(row, 1, item)

    def _on_batch_finished(self):
        self.add_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        failures = [
            self.table.item(row, 1).text()
            for row in range(self.table.rowCount())
            if self.table.item(row, 1).text().startswith("Failed")
        ]
        if failures:
            QMessageBox.critical(
                self, "Some conversions failed", "\n".join(failures)
            )
        self.refresh_availability()


# ----------------------------------------------------------------------
# Settings tab
# ----------------------------------------------------------------------
class _SettingsTab(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_tool_row(
            "Calibre ebook-convert", "ebook-convert", ebook_convert_path, set_ebook_convert_path,
        ))
        layout.addWidget(self._build_tool_row(
            "ffmpeg", "ffmpeg", ffmpeg_path, set_ffmpeg_path,
        ))
        layout.addStretch()

    def _build_tool_row(self, label, which_name, getter, setter):
        box = QWidget()
        row_layout = QVBoxLayout(box)
        row_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(label)
        title.setStyleSheet("font-weight: bold;")
        row_layout.addWidget(title)

        field_row = QHBoxLayout()
        edit = QLineEdit(getter() or shutil.which(which_name) or "")
        field_row.addWidget(edit, 1)
        browse_button = QPushButton("Browse…")
        field_row.addWidget(browse_button)
        save_button = QPushButton("Save")
        field_row.addWidget(save_button)
        row_layout.addLayout(field_row)

        status_label = QLabel("")
        status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        row_layout.addWidget(status_label)

        def browse():
            path, _ = QFileDialog.getOpenFileName(self, f"Select {label} binary", "")
            if path:
                edit.setText(path)

        def save():
            path = edit.text().strip()
            ok, message = verify_binary(path)
            if not ok:
                QMessageBox.critical(
                    self, f"{label} check failed",
                    f"Couldn't run '{path} --version':\n{message}",
                )
                status_label.setStyleSheet(f"color: {ERROR_RED};")
                status_label.setText(f"Not verified: {message}")
                return
            setter(path)
            status_label.setStyleSheet(f"color: {SUCCESS_GREEN};")
            status_label.setText(f"Verified: {message}")
            self.on_change()

        browse_button.clicked.connect(browse)
        save_button.clicked.connect(save)

        saved_path = getter()
        if saved_path:
            ok, message = verify_binary(saved_path)
            status_label.setStyleSheet(f"color: {SUCCESS_GREEN if ok else ERROR_RED};")
            status_label.setText((f"Verified: {message}" if ok else f"Not verified: {message}"))

        return box


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class ConverterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("🔁 Converter")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.documents_tab = _ConversionTab(
            PDF_FILTER, ".epub", convert_pdf_to_epub, ebook_convert_path, "Calibre ebook-convert",
        )
        self.video_tab = _ConversionTab(
            VIDEO_FILTER, ".mp4", convert_video_to_mp4, ffmpeg_path, "ffmpeg",
        )
        self.settings_tab = _SettingsTab(self._on_settings_changed)

        self.tabs.addTab(self.documents_tab, "Documents (PDF → EPUB)")
        self.tabs.addTab(self.video_tab, "Video (→ MP4)")
        self.tabs.addTab(self.settings_tab, "Settings")

    def _on_settings_changed(self):
        self.documents_tab.refresh_availability()
        self.video_tab.refresh_availability()
