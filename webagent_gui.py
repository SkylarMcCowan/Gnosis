"""
GUI for WebAgent - Modern chat interface with voice and web search capabilities
"""

import os
import sys
import threading
import asyncio
import html
from datetime import datetime


def _relaunch_with_project_venv():
    """Ensure the GUI and its TTS dependency use the project's virtualenv."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_dir, "venv", "bin", "python")
    if not os.path.isfile(venv_python):
        return
    if os.path.realpath(sys.executable) == os.path.realpath(venv_python):
        return

    os.execv(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]])


if __name__ == "__main__":
    _relaunch_with_project_venv()

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QPushButton, QLabel, QComboBox, QScrollArea,
        QFrame, QMessageBox, QStatusBar, QStackedLayout, QDialog, QLineEdit,
        QFileDialog, QRadioButton, QButtonGroup, QListWidget, QStackedWidget,
        QSplitter, QTabWidget
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QRectF, QObject
    from PyQt6.QtGui import (
        QFont, QTextCursor, QGuiApplication, QPainter, QColor, QPen,
        QTextBlockFormat, QTextCharFormat,
    )
except ModuleNotFoundError as e:
    raise SystemExit("PyQt6 is required to run the GUI. Install it with `pip install PyQt6`.") from e

import json
import math

import webagent
import agent_dialogue
import code_review
from core import config as core_config
from core.activity_log import load_activity
from memory.experience import load_experiences

BG_APP = "#16161c"
BG_PANEL = "#1e1e26"
BG_ELEVATED = "#262631"
BG_INPUT = "#20202a"
BG_BUBBLE_USER = "#3a3160"
BG_BUBBLE_ASSISTANT = "#23232e"
BORDER = "#34343f"
BORDER_LIGHT = "#44445a"
TEXT_PRIMARY = "#eaeaf2"
TEXT_SECONDARY = "#b4b4c4"
TEXT_MUTED = "#797986"
ACCENT = "#7c5cff"
ACCENT_LIGHT = "#9d85ff"
ACCENT_HOVER = "#8f6fff"
ACCENT_PRESSED = "#6a4cf0"

CHAT_BG_OPAQUE = f"""
    QTextEdit#chatDisplay {{
        background-color: {BG_PANEL};
        border: 1px solid {BORDER};
        padding: 15px;
        color: {TEXT_PRIMARY};
        line-height: 1.5;
    }}
"""
CHAT_BG_TRANSLUCENT = f"""
    QTextEdit#chatDisplay {{
        background-color: rgba(30, 30, 38, 150);
        border: 1px solid {BORDER};
        padding: 15px;
        color: {TEXT_PRIMARY};
        line-height: 1.5;
    }}
"""


class ResponseWorker(QThread):
    """Worker thread for handling AI responses"""
    response_chunk = pyqtSignal(str)  # Emits each chunk as it arrives
    response_ready = pyqtSignal(str)  # Emits complete response
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    status = pyqtSignal(str)  # Emits short progress text ("Searching the web...") between send and reply

    def __init__(self, user_input):
        super().__init__()
        self.user_input = user_input

    def run(self):
        try:
            response = webagent.chat_response(self.user_input, self.response_chunk.emit, self.status.emit)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}")
        finally:
            self.finished.emit()


class CycleWorker(QThread):
    """Runs one zero-arg callable off the GUI thread - the same shape as
    ResponseWorker/CodeReviewTaskWorker, generalized for the real,
    potentially slow autonomous pipelines (self-improve, tool generation,
    the overnight cycle) so triggering one from a button never freezes the
    window. Whatever the callable returns is passed through unchanged
    (a plain string for most of these, a (success, report) tuple for
    run_self_improve_cycle) - the caller who built the callable already
    knows which shape to expect back."""
    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn()
            self.result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}")


class QuestionDialog(QDialog):
    """Modal dialog presenting one or more clarifying questions from the model."""

    def __init__(self, questions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clarifying Question")
        self.setMinimumWidth(420)
        self._inputs = {}

        layout = QVBoxLayout(self)
        for q in questions:
            question_text = (q.get("question") or "").strip()
            if not question_text:
                continue
            label = QLabel(question_text)
            label.setWordWrap(True)
            layout.addWidget(label)

            options = q.get("options") or []
            if options:
                group = QButtonGroup(self)
                radios = []
                for opt in options:
                    radio = QRadioButton(str(opt))
                    layout.addWidget(radio)
                    group.addButton(radio)
                    radios.append(radio)
                radios[0].setChecked(True)
                self._inputs[question_text] = ("radio", radios)
            else:
                edit = QLineEdit()
                layout.addWidget(edit)
                self._inputs[question_text] = ("text", edit)

        button_row = QHBoxLayout()
        button_row.addStretch()
        submit_button = QPushButton("Submit")
        submit_button.clicked.connect(self.accept)
        button_row.addWidget(submit_button)
        layout.addLayout(button_row)

    def answers(self):
        result = {}
        for question_text, (kind, widget) in self._inputs.items():
            if kind == "radio":
                result[question_text] = next((r.text() for r in widget if r.isChecked()), "")
            else:
                result[question_text] = widget.text().strip()
        return result


class ClarifyBridge(QObject):
    """Lets a background QThread block on a main-thread question dialog.

    agent_dialogue.call_agent_json() runs on worker threads (ResponseWorker,
    DiffReviewWorker, ...), never the GUI thread, so a BlockingQueuedConnection
    here blocks the worker - not the UI - until the user answers.
    """
    ask_requested = pyqtSignal(list, dict)

    def __init__(self, parent_window):
        super().__init__()
        self._parent_window = parent_window
        self.ask_requested.connect(self._handle_ask, Qt.ConnectionType.BlockingQueuedConnection)

    def _handle_ask(self, questions, answers_out):
        dialog = QuestionDialog(questions, self._parent_window)
        if dialog.exec():
            answers_out.update(dialog.answers())
        else:
            answers_out.update({(q.get("question") or ""): "" for q in questions})

    def ask(self, questions):
        answers = {}
        self.ask_requested.emit(questions, answers)
        return answers


class CodeReviewTaskWorker(QThread):
    """Runs one code_review.py call off the GUI thread. task_fn receives a
    progress_emit(str) callback it may call zero or more times before returning."""
    result_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def run(self):
        try:
            result = self.task_fn(self.progress.emit)
            self.result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))


class DiffReviewDialog(QDialog):
    """Paste a diff, optionally point at a folder/zip for reference context,
    and get a two-pass (+ tie-break) checklist review from the coding model."""

    _VERDICT_COLORS = {"APPROVE": "#4caf50", "REJECT": "#e05252", "NEEDS_INFO": "#e0a952"}
    _STATUS_ICONS = {"pass": "✅", "concern": "⚠️", "fail": "❌", "waived": "🙈"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 Diff Review")
        self.setMinimumSize(720, 680)
        self.record = None
        self.worker = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Paste diff (leave empty to review the whole folder/zip below instead):"))
        self.diff_input = QTextEdit()
        self.diff_input.setPlaceholderText("Paste a unified diff here, or leave empty for a whole-folder review...")
        self.diff_input.setMinimumHeight(140)
        layout.addWidget(self.diff_input)

        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Folder to review (or reference, if a diff is pasted above)")
        folder_browse = QPushButton("Browse Folder")
        folder_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_input)
        folder_row.addWidget(folder_browse)
        layout.addLayout(folder_row)

        zip_row = QHBoxLayout()
        self.zip_input = QLineEdit()
        self.zip_input.setPlaceholderText("Zip to review (or reference, if a diff is pasted above)")
        zip_browse = QPushButton("Browse Zip")
        zip_browse.clicked.connect(self._browse_zip)
        zip_row.addWidget(self.zip_input)
        zip_row.addWidget(zip_browse)
        layout.addLayout(zip_row)

        run_row = QHBoxLayout()
        self.run_button = QPushButton("Run Review")
        self.run_button.clicked.connect(self._run_review)
        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedLabel")
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.status_label)
        run_row.addStretch()
        layout.addLayout(run_row)

        self.verdict_label = QLabel("")
        layout.addWidget(self.verdict_label)

        self.item_rows = {}
        checklist_frame = QFrame()
        checklist_layout = QVBoxLayout(checklist_frame)
        for key, display_label in code_review.CHECKLIST:
            row = QHBoxLayout()
            name_label = QLabel(display_label)
            name_label.setMinimumWidth(140)
            status_label = QLabel("—")
            status_label.setWordWrap(True)
            waive_button = QPushButton("Waive")
            waive_button.setMaximumWidth(60)
            waive_button.setVisible(False)
            waive_button.clicked.connect(lambda _checked, k=key: self._waive_item(k))
            row.addWidget(name_label)
            row.addWidget(status_label, 1)
            row.addWidget(waive_button)
            checklist_layout.addLayout(row)
            self.item_rows[key] = (status_label, waive_button)
        layout.addWidget(checklist_frame)

        followup_row = QHBoxLayout()
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText("Add context to resolve an open concern, then Submit")
        followup_button = QPushButton("Submit")
        followup_button.clicked.connect(self._submit_followup)
        followup_row.addWidget(self.followup_input)
        followup_row.addWidget(followup_button)
        layout.addLayout(followup_row)

        layout.addWidget(QLabel("History:"))
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.itemClicked.connect(self._load_history_item)
        layout.addWidget(self.history_list)

        self._refresh_history()

    def _set_busy(self, busy, message=""):
        self.run_button.setEnabled(not busy)
        self.status_label.setText(message)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self.folder_input.setText(path)

    def _browse_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Zip", "", "Zip files (*.zip)")
        if path:
            self.zip_input.setText(path)

    def _run_review(self):
        diff_text = self.diff_input.toPlainText().strip()
        folder = self.folder_input.text().strip() or None
        zip_path = self.zip_input.text().strip() or None

        if not diff_text and not folder and not zip_path:
            QMessageBox.warning(
                self, "Nothing To Review",
                "Paste a diff, or provide a folder/zip to review the whole codebase instead."
            )
            return

        if diff_text:
            self._set_busy(True, "Running two review passes...")

            def task(progress_emit):
                record = code_review.review_diff(diff_text, folder=folder, zip_path=zip_path)
                code_review.save_review(record)
                return record
        else:
            self._set_busy(True, "Scanning folder...")

            def task(progress_emit):
                record = code_review.review_folder(
                    folder=folder,
                    zip_path=zip_path,
                    on_progress=lambda i, n, files: progress_emit(
                        f"Batch {i}/{n}: {', '.join(files)}"
                    ),
                )
                code_review.save_review(record)
                return record

        self.worker = CodeReviewTaskWorker(task)
        self.worker.result_ready.connect(self._on_review_result)
        self.worker.error_occurred.connect(self._on_review_error)
        self.worker.progress.connect(lambda msg: self.status_label.setText(msg))
        self.worker.start()

    def _on_review_result(self, record):
        self.record = record
        if record.get("mode") == "folder":
            done_message = f"Done — {record.get('summary', '')}"
        else:
            done_message = f"Done ({len(record['passes'])} pass(es) run)."
        self._set_busy(False, done_message)
        self._render_record()
        self._refresh_history()

    def _on_review_error(self, message):
        self._set_busy(False, "")
        QMessageBox.critical(self, "Review Failed", message)

    def _render_record(self):
        if not self.record:
            return
        verdict = self.record.get("verdict", "")
        color = self._VERDICT_COLORS.get(verdict, TEXT_PRIMARY)
        self.verdict_label.setText(f"Verdict: {verdict} — {self.record.get('summary', '')}")
        self.verdict_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        for key, (status_label, waive_button) in self.item_rows.items():
            item = self.record.get("items", {}).get(key, {})
            status = item.get("status", "—")
            icon = self._STATUS_ICONS.get(status, "")
            status_label.setText(f"{icon} {item.get('comment', '')}".strip())
            waive_button.setVisible(status in ("concern", "fail"))

    def _waive_item(self, key):
        if not self.record:
            return
        self.record = code_review.resolve_open_item(self.record, key, waived=True)
        code_review.save_review(self.record)
        self._render_record()
        self._refresh_history()

    def _submit_followup(self):
        text = self.followup_input.text().strip()
        if not self.record or not text:
            return
        open_items = [
            key for key, _ in code_review.CHECKLIST
            if self.record.get("items", {}).get(key, {}).get("status") not in ("pass", "waived")
        ]
        if not open_items:
            QMessageBox.information(self, "Nothing Open", "There are no open concerns to resolve.")
            return

        self._set_busy(True, "Re-reviewing with your answer...")
        record = self.record
        item_key = open_items[0]

        def task(progress_emit):
            return code_review.resolve_open_item(record, item_key, answer_text=text)

        self.worker = CodeReviewTaskWorker(task)
        self.worker.result_ready.connect(self._on_followup_result)
        self.worker.error_occurred.connect(self._on_review_error)
        self.worker.start()

    def _on_followup_result(self, record):
        self.record = record
        code_review.save_review(record)
        self.followup_input.clear()
        self._set_busy(False, "Updated.")
        self._render_record()
        self._refresh_history()

    def _refresh_history(self):
        self.history_list.clear()
        for filename in code_review.list_reviews()[:20]:
            self.history_list.addItem(filename)

    def _load_history_item(self, item):
        record = code_review.load_review(item.text())
        self.record = record
        self.diff_input.setPlainText(record.get("diff_text", ""))
        self.folder_input.setText(record.get("folder") or "")
        self.zip_input.setText(record.get("zip_path") or "")
        self._render_record()


class MouthWidget(QWidget):
    """Decorative animated mouth shown as a backdrop while TTS is speaking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._openness = 0.0
        self._phase = 0.0
        self._talking = False
        self._enabled = False

    def tick(self, enabled, talking):
        self._enabled = enabled
        self._talking = talking
        if not enabled:
            self._phase = 0.0
            target = 0.0
        elif talking:
            self._phase += 0.5
            target = 0.15 + 0.85 * abs(math.sin(self._phase))
        else:
            target = 0.12
        self._openness += (target - self._openness) * 0.4
        self.update()

    def paintEvent(self, event):
        if not self._enabled and self._openness < 0.01:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        mouth_width = min(w, h) * 0.55
        mouth_height = mouth_width * 0.5 * max(self._openness, 0.05)

        base_alpha = 140 if self._talking else 55
        lip_color = QColor(ACCENT)
        lip_color.setAlpha(min(255, base_alpha + 60))
        cavity_color = QColor("#050507")
        cavity_color.setAlpha(min(255, base_alpha))
        teeth_color = QColor(TEXT_PRIMARY)
        teeth_color.setAlpha(min(255, int(base_alpha * 0.8)))

        cavity_rect = QRectF(cx - mouth_width / 2, cy - mouth_height / 2, mouth_width, mouth_height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(cavity_color)
        painter.drawEllipse(cavity_rect)

        if self._openness > 0.3:
            teeth_rect = QRectF(
                cavity_rect.left() + mouth_width * 0.14,
                cavity_rect.top() + mouth_height * 0.08,
                mouth_width * 0.72,
                mouth_height * 0.24,
            )
            painter.setBrush(teeth_color)
            painter.drawRoundedRect(teeth_rect, teeth_rect.height() / 2, teeth_rect.height() / 2)

        lip_rect = cavity_rect.adjusted(-5, -5, 5, 5)
        painter.setPen(QPen(lip_color, 7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(lip_rect)


class WebAgentGUI(QMainWindow):
    """Main GUI window for WebAgent"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🤖 WebAgent - AI Assistant")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(self.get_stylesheet())

        self.response_worker = None
        self.search_worker = None
        self.current_response = ""
        self.assistant_message_started = False

        self.clarify_bridge = ClarifyBridge(self)
        agent_dialogue.set_ui_asker(self.clarify_bridge.ask)

        self.init_ui()

        self._chat_bg_translucent = False
        self.mouth_timer = QTimer(self)
        self.mouth_timer.timeout.connect(self._update_mouth)
        self.mouth_timer.start(80)

    def _update_mouth(self):
        enabled = webagent.context.tts_mode
        talking = enabled and webagent.is_speaking()
        self.mouth_widget.tick(enabled, talking)
        if enabled != self._chat_bg_translucent:
            self._chat_bg_translucent = enabled
            self.chat_display.setStyleSheet(CHAT_BG_TRANSLUCENT if enabled else CHAT_BG_OPAQUE)

    def init_ui(self):
        """Initialize the user interface - a left-hand nav rail switching
        between the Chat page (unchanged behavior) and the newer
        autonomous-pipeline/observability/proposal/knowledge pages that
        expose what used to be CLI-only (/selfimprove, /generate,
        /overnight, /report, /learning) from this app instead."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setFixedWidth(180)
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label in ("💬  Chat", "🔄  Self-Improve", "📊  Report", "📦  Proposals", "🧠  Knowledge"):
            self.nav_list.addItem(label)
        root_layout.addWidget(self.nav_list)

        self.pages = QStackedWidget()
        root_layout.addWidget(self.pages, 1)

        self.pages.addWidget(self._build_chat_page())
        self.pages.addWidget(self._build_selfimprove_page())
        self.pages.addWidget(self._build_report_page())
        self.pages.addWidget(self._build_proposals_page())
        self.pages.addWidget(self._build_knowledge_page())

        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

    def _build_chat_page(self):
        """Everything the single-window app used to be - unchanged, just
        returned as a page widget instead of set directly as the central
        widget."""
        central_wrapper = QWidget()
        stack = QStackedLayout(central_wrapper)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)

        self.mouth_widget = MouthWidget()
        stack.addWidget(self.mouth_widget)

        central_widget = QWidget()
        central_widget.setObjectName("centralContent")
        stack.addWidget(central_widget)
        stack.setCurrentWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # Header - one toolbar panel, two organized rows (title/agent/actions,
        # then mode toggles as pills) instead of the two separately-bordered
        # panels with plain checkboxes this used to be - that read as
        # visually messy once there were six of them plus an agent bar.
        header_frame = QFrame()
        header_frame.setObjectName("toolbar")
        header_frame_layout = QVBoxLayout(header_frame)
        header_frame_layout.setContentsMargins(14, 10, 14, 10)
        header_frame_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel("💬 WebAgent")
        title_font = QFont("Arial", 16, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setObjectName("titleLabel")
        title_row.addWidget(title_label)
        title_row.addStretch()

        title_row.addWidget(QLabel("Agent:"))
        self.agent_combo = QComboBox()
        self.agent_combo.addItem("default")
        for agent_key in webagent.AVAILABLE_AGENTS:
            self.agent_combo.addItem(agent_key)
        title_row.addWidget(self.agent_combo)

        set_agent_button = QPushButton("Set")
        set_agent_button.setMaximumWidth(60)
        set_agent_button.clicked.connect(self.set_agent)
        title_row.addWidget(set_agent_button)

        self.current_agent_label = QLabel("Current: default")
        self.current_agent_label.setObjectName("mutedLabel")
        title_row.addWidget(self.current_agent_label)

        diff_review_button = QPushButton("📋 Diff Review")
        diff_review_button.setToolTip(
            "Paste a diff (optionally with a folder/zip for context), or leave the diff empty and "
            "point at a folder/zip to review the whole codebase directly."
        )
        diff_review_button.clicked.connect(self.open_diff_review)
        title_row.addWidget(diff_review_button)

        clear_button = QPushButton("🗑️")
        clear_button.setObjectName("clearButton")
        clear_button.setMaximumWidth(40)
        clear_button.setToolTip("Clear chat")
        clear_button.clicked.connect(self.clear_chat)
        title_row.addWidget(clear_button)

        header_frame_layout.addLayout(title_row)

        def toggle_button(text, tooltip=None):
            button = QPushButton(text)
            button.setObjectName("modeToggle")
            button.setCheckable(True)
            if tooltip:
                button.setToolTip(tooltip)
            return button

        def separator():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setObjectName("toggleSeparator")
            return line

        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(6)

        self.voice_check = toggle_button("🎤 Voice")
        self.voice_check.toggled.connect(self.toggle_voice_mode)
        if not webagent.has_speech_recognition:
            self.voice_check.setEnabled(False)
            self.voice_check.setToolTip("Speech recognition is unavailable when SpeechRecognition is not installed.")
        toggles_row.addWidget(self.voice_check)

        self.tts_check = toggle_button("🔊 TTS")
        self.tts_check.toggled.connect(self.toggle_tts_mode)
        if not webagent.has_tts_backend():
            self.tts_check.setEnabled(False)
            self.tts_check.setToolTip("No supported TTS backend is available.")
        toggles_row.addWidget(self.tts_check)

        toggles_row.addWidget(separator())

        self.web_search_check = toggle_button("🔍 Web")
        self.web_search_check.toggled.connect(self.toggle_web_search)
        self.web_search_check.setChecked(webagent.context.web_search_mode)
        toggles_row.addWidget(self.web_search_check)

        self.reasoning_check = toggle_button("🧠 Reason")
        self.reasoning_check.toggled.connect(self.toggle_reasoning_mode)
        toggles_row.addWidget(self.reasoning_check)

        self.deep_think_check = toggle_button(
            "🔬 Think", tooltip="Research multiple sources and return a structured analytical brief."
        )
        self.deep_think_check.toggled.connect(self.toggle_deep_think_mode)
        toggles_row.addWidget(self.deep_think_check)

        toggles_row.addWidget(separator())

        self.unfiltered_check = toggle_button("🕵️ Unfiltered")
        self.unfiltered_check.toggled.connect(self.toggle_unfiltered_mode)
        toggles_row.addWidget(self.unfiltered_check)

        self.coding_check = toggle_button("💻 Code")
        self.coding_check.toggled.connect(self.toggle_coding_mode)
        toggles_row.addWidget(self.coding_check)

        toggles_row.addStretch()
        header_frame_layout.addLayout(toggles_row)

        main_layout.addWidget(header_frame)

        # Chat display area - conversational style
        self.chat_display = QTextEdit()
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setReadOnly(True)
        main_layout.addWidget(self.chat_display)

        # Transient status line ("Searching the web...", "Verifying facts...")
        # shown between sending a message and the reply starting to stream -
        # see ResponseWorker.status / webagent.chat_response's on_status.
        self.chat_status_label = self._muted_label("")
        self.chat_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.chat_status_label)

        # Input area - compact and clean
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_text = QTextEdit()
        self.input_text.setObjectName("inputText")
        self.input_text.setMaximumHeight(50)
        self.input_text.setPlaceholderText("Type your message... (Ctrl+Enter to send)")
        self.input_text.installEventFilter(self)
        input_layout.addWidget(self.input_text)

        send_button = QPushButton("Send")
        send_button.setObjectName("sendButton")
        send_button.setMaximumWidth(80)
        send_button.setMinimumHeight(50)
        send_button.clicked.connect(self.send_message)
        input_layout.addWidget(send_button)

        main_layout.addLayout(input_layout)

        # Hint label
        hint_label = QLabel("💡 Ctrl+Enter to send")
        hint_label.setObjectName("mutedLabel")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(hint_label)

        return central_wrapper

    def _build_selfimprove_page(self):
        """Self-Improve & Overnight control - the GUI equivalent of typing
        /selfimprove, /selfimprove preview, /generate, or /overnight, since
        none of those commands were ever reachable from here before. Each
        button runs the same real function the CLI command calls, off the
        GUI thread (CycleWorker), and shows the same report text a terminal
        user would see. A direct button click is the same kind of attended,
        human-initiated action a typed command is - no extra confirmation
        dialog, matching Phase 15's "typing the command is the approval"
        stance."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        layout.addWidget(self._section_title("🔄 Self-Improve & Overnight"))
        layout.addWidget(self._muted_label(
            "Runs the real autonomous pipelines against this actual project. "
            "Preview is safe to run anytime; the others can write files or run "
            "tests for real."
        ))

        button_row = QHBoxLayout()
        self.si_preview_button = QPushButton("👁  Preview (dry run)")
        self.si_run_button = QPushButton("🚀  Run /selfimprove")
        self.si_generate_button = QPushButton("🔧  Generate skill")
        self.si_overnight_button = QPushButton("🌙  Run overnight cycle")
        for button in (self.si_preview_button, self.si_run_button, self.si_generate_button, self.si_overnight_button):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.si_preview_button.clicked.connect(lambda: self._run_cycle(
            "Preview", lambda: webagent.run_self_improve_cycle(dry_run=True)))
        self.si_run_button.clicked.connect(lambda: self._run_cycle(
            "/selfimprove", lambda: webagent.run_self_improve_cycle(dry_run=False)))
        self.si_generate_button.clicked.connect(lambda: self._run_cycle(
            "Generate", lambda: webagent.run_tool_generation_cycle(
                webagent._selfimprove_coding_chat, webagent._selfimprove_root(),
                [(t.name, t.description) for t in webagent.tool_registry.list()],
                agent="self-improve",
            )))
        self.si_overnight_button.clicked.connect(lambda: self._run_cycle(
            "Overnight", webagent.run_overnight_cycle))

        self.si_status_label = self._muted_label("")
        layout.addWidget(self.si_status_label)

        self.si_output = QTextEdit()
        self.si_output.setObjectName("chatDisplay")
        self.si_output.setReadOnly(True)
        self.si_output.setFontFamily("Menlo, Consolas, monospace")
        layout.addWidget(self.si_output, 1)

        self._si_worker = None
        return page

    def _run_cycle(self, label, fn):
        """Shared trigger for every Self-Improve/Overnight button: disable
        all four while one runs (they'd otherwise contend for the same
        worktree/crontab-classified real resources), run fn() on a
        CycleWorker, and render whatever it returns."""
        for button in (self.si_preview_button, self.si_run_button, self.si_generate_button, self.si_overnight_button):
            button.setEnabled(False)
        self.si_status_label.setText(f"Running {label}...")

        self._si_worker = CycleWorker(fn)
        self._si_worker.result_ready.connect(lambda result: self._on_cycle_result(label, result))
        self._si_worker.error_occurred.connect(self._on_cycle_error)
        self._si_worker.start()

    def _on_cycle_result(self, label, result):
        if isinstance(result, tuple) and len(result) == 2:
            success, report = result
            self.si_status_label.setText(f"{label}: {'succeeded' if success else 'reverted/blocked'}")
        else:
            report = result
            self.si_status_label.setText(f"{label}: done")
        self.si_output.setPlainText(str(report))
        self._reset_cycle_buttons()

    def _on_cycle_error(self, message):
        self.si_status_label.setText("Failed")
        self.si_output.setPlainText(message)
        self._reset_cycle_buttons()

    def _reset_cycle_buttons(self):
        for button in (self.si_preview_button, self.si_run_button, self.si_generate_button, self.si_overnight_button):
            button.setEnabled(True)

    def _build_report_page(self):
        """The GUI equivalent of /report + /learning - both are pure,
        fast queries over Phase 5/6/12's already-recorded data (no model
        call, no subprocess), so this runs synchronously on the GUI thread
        with a Refresh button rather than needing a worker."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.addWidget(self._section_title("📊 Observability"))
        header_row.addStretch()
        refresh_button = QPushButton("🔄 Refresh")
        refresh_button.clicked.connect(self._refresh_report)
        header_row.addWidget(refresh_button)
        layout.addLayout(header_row)

        self.report_output = QTextEdit()
        self.report_output.setObjectName("chatDisplay")
        self.report_output.setReadOnly(True)
        layout.addWidget(self.report_output, 1)

        self._refresh_report()
        return page

    def _refresh_report(self):
        lines = []

        def section(title):
            lines.append(f"\n=== {title} ===")

        section("Task completion")
        completion = webagent.task_completion_stats()
        if completion["total_completed"] == 0:
            lines.append("None recorded yet.")
        else:
            lines.append(f"{completion['total_completed']} total")
            for agent_name, count in completion["by_agent"].items():
                lines.append(f"  {agent_name}: {count}")

        section("Search quality")
        search = webagent.search_quality_stats()
        if search["total_searches"] == 0:
            lines.append("No searches recorded yet.")
        else:
            lines.append(
                f"{search['total_searches']} searches, {search['zero_result_searches']} returned "
                f"nothing ({search['zero_result_rate']:.0%}), average {search['avg_result_count']:.1f} results"
            )

        section("Tool usage")
        tools = webagent.tool_usage_stats()
        if not tools:
            lines.append("No recorded self-improve/tool-generator activity yet.")
        else:
            for name, stats in sorted(tools.items(), key=lambda item: -item[1]["used"]):
                rate = f"{stats['success_rate']:.0%}" if stats["success_rate"] is not None else "n/a"
                lines.append(f"  {name}: used {stats['used']}x, {rate} in a successful outcome")

        section("Self-improve: files changed over time")
        files = webagent.self_improve_target_file_stats()
        if not files:
            lines.append("No recorded self-improve attempts yet.")
        else:
            for target_file, stats in sorted(files.items(), key=lambda item: -item[1]["attempts"]):
                lines.append(f"  {target_file}: {stats['attempts']} attempt(s), {stats['succeeded']} succeeded")

        for agent_name, label in (("self-improve", "Self-improve"), ("tool-generator", "Tool generation")):
            section(f"{label} performance")
            performance = webagent.evaluate_recent_performance(agent=agent_name)
            if performance["attempted"] == 0:
                lines.append("No attempts recorded yet.")
            else:
                lines.append(f"{performance['attempted']} attempted, {performance['success_rate']:.0%} succeeded")

            findings = webagent.critique_recent_failures(agent=agent_name)
            if findings:
                lines.append("Patterns in recent failures:")
                for finding in findings:
                    lines.append(f"  - {finding['summary']}")

            lessons = webagent.consolidated_lessons(agent=agent_name)
            if lessons:
                lines.append("Recent lessons:")
                for lesson, count in lessons[:5]:
                    suffix = f" (x{count})" if count > 1 else ""
                    lines.append(f"  - {lesson}{suffix}")

        self.report_output.setPlainText("\n".join(lines).strip())

    def _build_proposals_page(self):
        """Browses gnosis_workspace/proposals/ - Phase 9's generated-skill
        proposals, each already carrying Phase 11's reviewer-panel findings
        in its own report.md. Nothing here registers a proposal; this is
        read-only, the same "a human reads it first" stance every proposal
        has had since Phase 9."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.addWidget(self._section_title("📦 Generated Skill Proposals"))
        header_row.addStretch()
        refresh_button = QPushButton("🔄 Refresh")
        refresh_button.clicked.connect(self._refresh_proposals)
        header_row.addWidget(refresh_button)
        layout.addLayout(header_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.proposals_list = QListWidget()
        self.proposals_list.setMaximumWidth(260)
        self.proposals_list.itemClicked.connect(self._load_proposal)
        splitter.addWidget(self.proposals_list)

        self.proposals_detail = QTextEdit()
        self.proposals_detail.setObjectName("chatDisplay")
        self.proposals_detail.setReadOnly(True)
        splitter.addWidget(self.proposals_detail)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._refresh_proposals()
        return page

    def _refresh_proposals(self):
        self.proposals_list.clear()
        proposals_dir = core_config.path("gnosis_workspace", "proposals")
        if not os.path.isdir(proposals_dir):
            self.proposals_detail.setPlainText("No proposals yet - run Generate on the Self-Improve page.")
            return
        for proposal_id in sorted(os.listdir(proposals_dir), reverse=True):
            if os.path.isdir(os.path.join(proposals_dir, proposal_id)):
                self.proposals_list.addItem(proposal_id)

    def _load_proposal(self, item):
        proposals_dir = core_config.path("gnosis_workspace", "proposals")
        proposal_dir = os.path.join(proposals_dir, item.text())
        parts = []
        report_path = os.path.join(proposal_dir, "report.md")
        if os.path.isfile(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                parts.append(f.read())
        for filename in sorted(os.listdir(proposal_dir)):
            file_path = os.path.join(proposal_dir, filename)
            if filename == "report.md" or not os.path.isfile(file_path):
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                parts.append(f"\n\n--- {filename} ---\n{f.read()}")
        self.proposals_detail.setPlainText("\n".join(parts))

    def _build_knowledge_page(self):
        """Browses the three flat on-disk stores that used to only be
        readable by grepping JSON Lines/markdown files by hand:
        knowledge_base/ (includes self-improve's and overnight's own
        report archives), the Experience log (Phase 5), and the activity
        log (Phase 12)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        layout.addWidget(self._section_title("🧠 Knowledge & Experience"))

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        kb_page = QWidget()
        kb_layout = QVBoxLayout(kb_page)
        kb_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.kb_list = QListWidget()
        self.kb_list.setMaximumWidth(320)
        self.kb_list.itemClicked.connect(self._load_kb_file)
        kb_splitter.addWidget(self.kb_list)
        self.kb_detail = QTextEdit()
        self.kb_detail.setObjectName("chatDisplay")
        self.kb_detail.setReadOnly(True)
        kb_splitter.addWidget(self.kb_detail)
        kb_splitter.setStretchFactor(1, 1)
        kb_layout.addWidget(kb_splitter)
        tabs.addTab(kb_page, "Knowledge base")

        exp_page = QWidget()
        exp_layout = QVBoxLayout(exp_page)
        self.experience_output = QTextEdit()
        self.experience_output.setObjectName("chatDisplay")
        self.experience_output.setReadOnly(True)
        exp_layout.addWidget(self.experience_output)
        tabs.addTab(exp_page, "Experience log")

        activity_page = QWidget()
        activity_layout = QVBoxLayout(activity_page)
        self.activity_output = QTextEdit()
        self.activity_output.setObjectName("chatDisplay")
        self.activity_output.setReadOnly(True)
        activity_layout.addWidget(self.activity_output)
        tabs.addTab(activity_page, "Activity log")

        tabs.currentChanged.connect(lambda _index: self._refresh_knowledge_tab(tabs.currentIndex()))
        self._refresh_knowledge_tab(0)
        return page

    def _refresh_knowledge_tab(self, index):
        if index == 0:
            self._refresh_kb_list()
        elif index == 1:
            self._refresh_experience_log()
        elif index == 2:
            self._refresh_activity_log()

    def _refresh_kb_list(self):
        self.kb_list.clear()
        kb_dir = core_config.path("knowledge_base")
        if not os.path.isdir(kb_dir):
            return
        for dirpath, _dirnames, filenames in os.walk(kb_dir):
            for filename in sorted(filenames):
                rel_path = os.path.relpath(os.path.join(dirpath, filename), kb_dir)
                self.kb_list.addItem(rel_path)
        self.kb_list.sortItems(Qt.SortOrder.DescendingOrder)

    def _load_kb_file(self, item):
        kb_dir = core_config.path("knowledge_base")
        file_path = os.path.join(kb_dir, item.text())
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.kb_detail.setPlainText(f.read())
        except OSError as e:
            self.kb_detail.setPlainText(f"Could not read {item.text()}: {e}")

    def _refresh_experience_log(self):
        records = load_experiences(limit=100)
        if not records:
            self.experience_output.setPlainText("No experiences recorded yet.")
            return
        lines = []
        for record in reversed(records):
            lines.append(
                f"[{record.get('timestamp', '?')}] {record.get('agent', '?')} - "
                f"success={record.get('success')} - {record.get('goal', '')}"
            )
        self.experience_output.setPlainText("\n".join(lines))

    def _refresh_activity_log(self):
        records = load_activity(limit=100)
        if not records:
            self.activity_output.setPlainText("No activity recorded yet.")
            return
        lines = []
        for record in reversed(records):
            payload = {k: v for k, v in record.items() if k not in ("event", "timestamp")}
            lines.append(f"[{record.get('timestamp', '?')}] {record.get('event', '?')} - {json.dumps(payload)}")
        self.activity_output.setPlainText("\n".join(lines))

    def _section_title(self, text):
        label = QLabel(text)
        label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        label.setObjectName("titleLabel")
        return label

    def _muted_label(self, text):
        label = QLabel(text)
        label.setObjectName("mutedLabel")
        label.setWordWrap(True)
        return label

    def eventFilter(self, source, event):
        if source is self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(source, event)
    
    def send_message(self):
        """Send user message and get AI response"""
        user_input = self.input_text.toPlainText().strip()
        
        if not user_input:
            QMessageBox.warning(self, "Empty Input", "Please enter a message.")
            return
        
        # Display user message
        self.display_message(user_input, is_user=True)
        self.input_text.clear()
        
        # Disable input while processing
        self.input_text.setEnabled(False)
        
        # Initialize streaming response placeholder
        self.current_response = ""
        self.assistant_message_started = False
        self.response_start_time = datetime.now()
        self.chat_status_label.setText("Thinking...")

        # Start response worker
        self.response_worker = ResponseWorker(user_input)
        self.response_worker.response_chunk.connect(self.on_response_chunk)
        self.response_worker.response_ready.connect(self.on_response_ready)
        self.response_worker.error_occurred.connect(self.on_error)
        self.response_worker.finished.connect(self.on_response_finished)
        self.response_worker.status.connect(self.on_chat_status)
        self.response_worker.start()

    def on_chat_status(self, message):
        """Show a short progress update ("Searching the web...") between
        sending a message and the reply starting to stream. Cleared once
        the first real chunk arrives (on_response_chunk) or the turn ends
        (on_response_finished/on_error)."""
        self.chat_status_label.setText(message)

    def on_response_chunk(self, chunk):
        """Handle streaming response chunks"""
        self.current_response += chunk

        if not self.assistant_message_started:
            self.chat_status_label.setText("")
            timestamp = self.response_start_time.strftime("%H:%M")
            cursor = self.chat_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if not self.chat_display.document().isEmpty():
                cursor.insertBlock()
                cursor.setBlockFormat(QTextBlockFormat())
                cursor.setCharFormat(QTextCharFormat())
            cursor.insertHtml(
                f'<div style="margin: 14px 0;"><span style="color: {ACCENT_LIGHT}; font-weight: bold;">Assistant</span> '
                f'<span style="color: {TEXT_MUTED}; font-size: 11px;">{timestamp}</span><br/>'
                f'<div style="background-color: {BG_BUBBLE_ASSISTANT}; border-radius: 10px; padding: 10px 12px; '
                f'margin-top: 4px; color: {TEXT_PRIMARY};">'
            )
            self.assistant_message_started = True

        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def on_response_ready(self, response):
        """Handle complete AI response"""
        # Close the div tag for the assistant message
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml('</div></div>')
        self.chat_display.setTextCursor(cursor)

        # Response already displayed via streaming, just reset state
        self.current_response = ""

    def on_response_finished(self):
        """Handle response completion"""
        self.chat_status_label.setText("")
        self.input_text.setEnabled(True)
        self.input_text.setFocus()

    def on_error(self, error_msg):
        """Handle errors"""
        self.chat_status_label.setText("")
        QMessageBox.critical(self, "Error", error_msg)
        self.input_text.setEnabled(True)

    def set_agent(self):
        selected = self.agent_combo.currentText()
        result = webagent.job_command(selected if selected != "default" else "default")
        self.current_agent_label.setText(f"Current: {selected}")
        self.display_message(result, is_user=False)
        if webagent.context.current_agent:
            self.agent_combo.setCurrentText(webagent.context.current_agent)
        else:
            self.agent_combo.setCurrentText("default")

    def toggle_unfiltered_mode(self, checked):
        if checked:
            self.reasoning_check.setChecked(False)
            self.coding_check.setChecked(False)
        webagent.context.unfiltered_mode = checked

    def toggle_coding_mode(self, checked):
        if checked:
            self.reasoning_check.setChecked(False)
            self.unfiltered_check.setChecked(False)
        webagent.context.coding_mode = checked

    def open_diff_review(self):
        dialog = DiffReviewDialog(self)
        dialog.exec()

    def display_message(self, text, is_user=True):
        """Display a message in the chat with conversational styling"""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.chat_display.document().isEmpty():
            cursor.insertBlock()
            cursor.setBlockFormat(QTextBlockFormat())
            cursor.setCharFormat(QTextCharFormat())

        timestamp = datetime.now().strftime("%H:%M")
        
        safe_text = html.escape(text).replace("\n", "<br/>")
        if is_user:
            formatted_text = (
                f'<div style="margin: 14px 0; text-align: right;">'
                f'<span style="color: {ACCENT_LIGHT}; font-weight: bold;">You</span> '
                f'<span style="color: {TEXT_MUTED}; font-size: 11px;">{timestamp}</span><br/>'
                f'<div style="background-color: {BG_BUBBLE_USER}; border-radius: 10px; padding: 10px 12px; '
                f'margin-top: 4px; color: {TEXT_PRIMARY};">{safe_text}</div></div>'
            )
        else:
            formatted_text = (
                f'<div style="margin: 14px 0;">'
                f'<span style="color: {ACCENT_LIGHT}; font-weight: bold;">Assistant</span> '
                f'<span style="color: {TEXT_MUTED}; font-size: 11px;">{timestamp}</span><br/>'
                f'<div style="background-color: {BG_BUBBLE_ASSISTANT}; border-radius: 10px; padding: 10px 12px; '
                f'margin-top: 4px; color: {TEXT_PRIMARY};">{safe_text}</div></div>'
            )

        cursor.insertHtml(formatted_text)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def clear_chat(self):
        """Clear chat history"""
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            webagent.new_conversation(save_current=False)
    
    def toggle_voice_mode(self, checked):
        """Toggle voice input mode"""
        webagent.context.voice_mode = checked
        if checked and self.tts_check.isChecked():
            self.tts_check.setChecked(False)

    def toggle_tts_mode(self, checked):
        """Toggle text-to-speech mode"""
        webagent.context.tts_mode = checked
        if checked and self.voice_check.isChecked():
            self.voice_check.setChecked(False)

    def toggle_web_search(self, checked):
        """Toggle web search mode"""
        webagent.context.web_search_mode = checked

    def toggle_reasoning_mode(self, checked):
        """Toggle reasoning mode"""
        if checked:
            self.unfiltered_check.setChecked(False)
            self.coding_check.setChecked(False)
        webagent.context.reasoning_mode = checked

    def toggle_deep_think_mode(self, checked):
        """Toggle evidence-led, structured web research."""
        webagent.context.deep_think_mode = checked
        if checked:
            self.web_search_check.setChecked(True)
    
    def get_stylesheet(self):
        """Return custom dark stylesheet for the application"""
        return f"""
            QMainWindow {{
                background-color: {BG_APP};
            }}
            #centralContent {{
                background-color: transparent;
            }}
            QLabel {{
                color: {TEXT_SECONDARY};
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            }}
            QLabel#titleLabel {{
                color: {TEXT_PRIMARY};
            }}
            QLabel#mutedLabel {{
                color: {TEXT_MUTED};
                font-size: 11px;
            }}
            QFrame#toolbar {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QFrame#toggleSeparator {{
                background-color: {BORDER};
                max-width: 1px;
                margin: 2px 4px;
            }}
            QTextEdit {{
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                font-size: 13px;
                border-radius: 8px;
            }}
            QTextEdit#chatDisplay {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                padding: 15px;
                color: {TEXT_PRIMARY};
                line-height: 1.5;
            }}
            QTextEdit#inputText {{
                background-color: {BG_INPUT};
                border: 1px solid {BORDER};
                padding: 10px;
                color: {TEXT_PRIMARY};
            }}
            QTextEdit#inputText:focus {{
                border: 1px solid {ACCENT};
                background-color: {BG_ELEVATED};
            }}
            QComboBox {{
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 5px 8px;
                background-color: {BG_INPUT};
                color: {TEXT_PRIMARY};
            }}
            QComboBox:hover {{
                border: 1px solid {BORDER_LIGHT};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                selection-background-color: {ACCENT};
                border: 1px solid {BORDER_LIGHT};
                outline: none;
            }}
            QPushButton {{
                background-color: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {BORDER_LIGHT};
            }}
            QPushButton:pressed {{
                background-color: {BORDER};
            }}
            QPushButton#sendButton {{
                background-color: {ACCENT};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton#sendButton:hover {{
                background-color: {ACCENT_HOVER};
            }}
            QPushButton#sendButton:pressed {{
                background-color: {ACCENT_PRESSED};
            }}
            QPushButton#clearButton {{
                background-color: transparent;
                border: 1px solid {BORDER};
            }}
            QPushButton#clearButton:hover {{
                background-color: {BORDER};
            }}
            QPushButton#modeToggle {{
                background-color: transparent;
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-radius: 14px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton#modeToggle:hover {{
                border: 1px solid {BORDER_LIGHT};
                background-color: {BG_ELEVATED};
            }}
            QPushButton#modeToggle:checked {{
                background-color: {ACCENT};
                color: white;
                border: 1px solid {ACCENT};
                font-weight: 600;
            }}
            QPushButton#modeToggle:checked:hover {{
                background-color: {ACCENT_HOVER};
            }}
            QPushButton#modeToggle:disabled {{
                color: {TEXT_MUTED};
                border: 1px solid {BORDER};
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_LIGHT};
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {ACCENT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QStatusBar {{
                background-color: {BG_PANEL};
                color: {TEXT_SECONDARY};
            }}
            QMessageBox {{
                background-color: {BG_PANEL};
            }}
            QMessageBox QLabel {{
                color: {TEXT_PRIMARY};
            }}
            QToolTip {{
                background-color: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_LIGHT};
                padding: 4px;
            }}
            QListWidget {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-radius: 6px;
            }}
            QListWidget::item:hover {{
                background-color: {BG_ELEVATED};
            }}
            QListWidget::item:selected {{
                background-color: {ACCENT};
                color: white;
            }}
            QListWidget#navList {{
                background-color: {BG_APP};
                border: none;
                border-right: 1px solid {BORDER};
                border-radius: 0;
                font-size: 14px;
                padding: 10px 6px;
            }}
            QListWidget#navList::item {{
                padding: 10px 12px;
                margin-bottom: 2px;
            }}
            QTabWidget::pane {{
                background-color: {BG_APP};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {BG_ELEVATED};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 14px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
            }}
            QSplitter::handle {{
                background-color: {BG_APP};
                width: 6px;
            }}
        """


def main():
    """Main entry point"""
    app = QApplication(sys.argv)

    if not QGuiApplication.screens():
        raise SystemExit("No display detected. The GUI requires a graphical desktop environment to run.")

    # Set application style
    app.setStyle('Fusion')
    
    window = WebAgentGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
