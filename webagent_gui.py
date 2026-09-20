"""
GUI for WebAgent - Modern chat interface with voice and web search capabilities
"""

import os
import sys
import html
import copy
import time
from contextlib import contextmanager
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
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QTextEdit, QTextBrowser, QPushButton, QLabel, QComboBox, QScrollArea,
        QFrame, QMessageBox, QStatusBar, QStackedLayout, QDialog, QLineEdit,
        QFileDialog, QRadioButton, QButtonGroup, QListWidget, QListWidgetItem, QStackedWidget,
        QSplitter, QTabWidget, QSpinBox
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QRectF, QObject
    from PyQt6.QtGui import (
        QFont, QTextCursor, QGuiApplication, QPainter, QColor, QPen,
        QTextBlockFormat, QTextCharFormat, QTextFrameFormat, QDesktopServices,
    )
except ModuleNotFoundError as e:
    raise SystemExit("PyQt6 is required to run the GUI. Install it with `pip install PyQt6`.") from e

import json
import math
import re

import webagent
import agent_dialogue
import code_review
from core import config as core_config
from core import models as core_models
from core import cloud_models
from games.zuma_endless import ZumaEndlessWidget
from games.solitaire import SolitaireWidget
from games.sudoku import SudokuWidget, DIFFICULTIES as SUDOKU_DIFFICULTIES
from games.mystery import MysteryWidget
from games.tetris import TetrisWidget
from games.hangman import HangmanWidget, CATEGORIES as HANGMAN_CATEGORIES
from games.idle_island import IdleIslandWidget
from games.cozy_world import CozyWorldWidget
from games.neon_racer import NeonRacerWidget
from games.minesweeper import MinesweeperWidget, DIFFICULTIES as MINESWEEPER_DIFFICULTIES
from games.mastermind import MastermindWidget, DIFFICULTIES as MASTERMIND_DIFFICULTIES
from games.nonogram import NonogramWidget, PATTERNS as NONOGRAM_PATTERNS
from games.slider_puzzle import SliderPuzzleWidget, DIFFICULTIES as SLIDER_DIFFICULTIES
from worklog import WorklogWidget
from weather_station import WeatherStationWidget
from stocks_tracker import StocksTrackerWidget
from radio import RadioWidget
from content_builder import LinkedInBlogBuilderWidget
from hacker import HackerWidget
from ethereal_dnd_widget import EtherealDndWidget
from penpot_studio import PenpotStudioWidget
from converter import ConverterWidget
from core import subscriptions
from core import sports as core_sports
from core.activity_log import load_activity, clear_activity
from memory.experience import load_experiences
from core.exceptions import ChatCancelled
from voice.runtime import VoiceSession, VoicePreview
from voice.panel import VoicePanel
from subscription_dashboard import SubscriptionDashboard, DashboardUpdateWorker

BG_APP = "#10141e"
BG_PANEL = "#171d2a"
BG_ELEVATED = "#222b3b"
BG_INPUT = "#1a2232"
BG_BUBBLE_USER = "#2b2949"
BG_BUBBLE_ASSISTANT = "#1c2534"
BORDER = "#2a3446"
BORDER_LIGHT = "#40506a"
TEXT_PRIMARY = "#edf1f8"
TEXT_SECONDARY = "#b8c3d6"
TEXT_MUTED = "#8c9ab1"
ACCENT = "#8b79f6"
ACCENT_LIGHT = "#b4a8ff"
ACCENT_HOVER = "#a092ff"
ACCENT_PRESSED = "#7766de"
SUCCESS_GREEN = "#3ecf8e"
SUCCESS_GREEN_HOVER = "#4ee0a0"

CHAT_BG_OPAQUE = f"""
    QTextEdit#chatDisplay {{
        background-color: {BG_PANEL};
        border: 1px solid {BORDER};
        border-radius: 16px;
        padding: 8px;
        color: {TEXT_PRIMARY};
        line-height: 1.5;
    }}
"""
CHAT_BG_TRANSLUCENT = f"""
    QTextEdit#chatDisplay {{
        background-color: rgba(23, 29, 42, 150);
        border: 1px solid {BORDER};
        border-radius: 16px;
        padding: 8px;
        color: {TEXT_PRIMARY};
        line-height: 1.5;
    }}
"""


class _ResponseCancelled(ChatCancelled):
    """Raised from inside a chunk/status callback to unwind out of
    webagent.chat_response when the user asked to stop - distinct from a
    real error so ResponseWorker can tell the two apart."""


class ResponseWorker(QThread):
    """Worker thread for handling AI responses"""
    response_chunk = pyqtSignal(str)  # Emits each chunk as it arrives
    response_ready = pyqtSignal(str)  # Emits complete response
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal()  # A deliberate user-initiated stop, not an error
    finished = pyqtSignal()
    status = pyqtSignal(str)  # Emits short progress text ("Searching the web...") between send and reply
    sources = pyqtSignal(list)  # Emits the raw evidence list when web search/Deep Think actually ran

    def __init__(self, user_input):
        super().__init__()
        self.user_input = user_input
        self._cancel_requested = False

    def cancel(self):
        """Stop at the next status/model chunk, including silent thinking.
        A blocked HTTP read remains bounded by the model transport timeout."""
        self._cancel_requested = True

    def run(self):
        def guarded_chunk(text):
            if self._cancel_requested:
                raise _ResponseCancelled()
            self.response_chunk.emit(text)

        def guarded_status(text):
            if self._cancel_requested:
                raise _ResponseCancelled()
            self.status.emit(text)

        try:
            def check_cancelled():
                if self._cancel_requested:
                    raise _ResponseCancelled()
            with core_models.request_control(check_cancelled):
                response = webagent.chat_response(
                    self.user_input, guarded_chunk, guarded_status, on_sources=self.sources.emit,
                )
            if self._cancel_requested:
                raise _ResponseCancelled()
            self.response_ready.emit(response)
        except _ResponseCancelled:
            self.cancelled.emit()
        except Exception as e:
            if self._cancel_requested:
                self.cancelled.emit()
            else:
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


_SUBSCRIPTION_TYPE_ICONS = {"team": "⚽", "topic": "📰", "website": "🌐", "weather": "🌦️"}

# The Subscriptions page's curated catalog - real, working sources grouped
# into the categories the button grid renders one row of buttons per. A
# starter set, not gospel: every entry here is a real, reputable source
# real enough to demo, but which specific outlets/teams/sites belong is an
# editorial call meant to be revisited, not treated as final. Weather is
# deliberately absent - it has no fixed "source" list the way News/Sports
# do, so it gets its own validated-text-entry section instead (see
# _build_weather_subscription_section) rather than a catalog category here.
#
# Popular soccer teams are shortcuts; the sports picker below also loads
# complete team directories for the supported leagues and sports.
from core.interest_catalog import CATALOG as SUBSCRIPTION_CATALOG, CATEGORIES as INTEREST_CATEGORIES, category_for


class WebAgentGUI(QMainWindow):
    """Main GUI window for WebAgent"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gnosis — AI workspace")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(self.get_stylesheet())

        self.response_worker = None
        self.current_response = ""
        self.assistant_message_started = False
        self._assistant_cursor = None
        self._pending_sources = None
        from background_tasks import DaytimeTasks
        self._daytime = DaytimeTasks(core_config.project_root())
        self._warmup_key = None
        self._voice_priority = None
        self._dashboard_worker = None
        self._sports_worker = None
        self._subscription_workers = []
        self._response_active = False
        self._voice_turn = False
        self._close_requested = False
        self.voice_preview = VoicePreview(self)
        self.voice_session = VoiceSession(self)
        self.voice_session.heard.connect(self._on_voice_input)
        self.voice_session.phase.connect(self._on_voice_phase)
        self.voice_session.level.connect(self._on_voice_level)
        self.voice_session.enabled_changed.connect(self._on_voice_enabled)
        self.voice_session.error.connect(self._on_voice_error)
        self.voice_session.interrupt_requested.connect(self._interrupt_voice_reply)
        self.voice_session.idle.connect(self._voice_idle)
        self._follow_latest = True
        self._updating_chat = False
        self._activity_phase = ""
        self._activity_started = None
        self._activity_outcome = "Finished"
        self._last_prompt = ""
        self._last_reply = ""
        self._last_turn_context = None
        self._last_turn_html = ""
        self._editing_last_turn = False
        self._draft_before_edit = ""
        self._last_retry_allowed = True
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(250)
        self.activity_timer.timeout.connect(self._refresh_chat_activity)

        self.clarify_bridge = ClarifyBridge(self)
        agent_dialogue.set_ui_asker(self.clarify_bridge.ask)

        self.init_ui()

        self._chat_bg_translucent = False
        self.mouth_timer = QTimer(self)
        self.mouth_timer.timeout.connect(self._update_mouth)
        self.mouth_timer.start(80)
        self.background_label = QLabel("Background: ready")
        self.background_pause = QPushButton("Pause background")
        self.background_pause.setCheckable(True)
        self.background_pause.toggled.connect(self._pause_background)
        self.statusBar().addPermanentWidget(self.background_label)
        self.statusBar().addPermanentWidget(self.background_pause)
        self.background_timer = QTimer(self)
        self.background_timer.setInterval(1000)
        self.background_timer.timeout.connect(self._tick_background)
        self.background_timer.start()

    def closeEvent(self, event):
        """Every game widget autosaves on its own timer already, but that
        can be up to 15-30s stale - explicitly flushing each one's
        save_now() here means closing the app (or restarting it) never
        loses whatever progress happened since the last autosave tick."""
        self._close_requested = True
        self.background_timer.stop()
        self._daytime.shutdown()
        if not self.voice_preview.shutdown():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        if any(worker.isRunning() for worker in self._subscription_workers):
            self.voice_session.stop()
            if self._response_active:
                self.response_worker.cancel()
            if self._dashboard_worker is not None:
                self._dashboard_worker.cancel()
            event.ignore()
            return
        if self._sports_worker is not None and self._sports_worker.isRunning():
            self.voice_session.stop()
            if self._response_active:
                self.response_worker.cancel()
            if self._dashboard_worker is not None:
                self._dashboard_worker.cancel()
            event.ignore()
            return
        if self._dashboard_worker is not None and self._dashboard_worker.isRunning():
            self._dashboard_worker.cancel()
            self.voice_session.stop()
            if self._response_active:
                self.response_worker.cancel()
            event.ignore()
            return
        if self._response_active:
            self.voice_session.stop()
            self.response_worker.cancel()
            event.ignore()
            self._set_chat_activity("Stopping")
            return
        if not self.voice_session.shutdown():
            event.ignore()
            return
        for widget in (
            self.zuma_widget, self.solitaire_widget, self.sudoku_widget,
            self.mystery_widget, self.tetris_widget, self.hangman_widget,
            self.idle_island_widget, self.cozy_world_widget, self.neon_racer_widget,
            self.minesweeper_widget, self.mastermind_widget, self.nonogram_widget,
            self.slider_puzzle_widget,
        ):
            widget.save_now()
        self.hacker_widget.stop_and_cleanup()
        if self._voice_priority is not None:
            self._voice_priority.__exit__(None, None, None)
            self._voice_priority = None
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, '_mode_grid'):
            return
        compact = self.width() < 1100
        if compact != self._compact_chat:
            self._compact_chat = compact
            self.history_button.setChecked(not compact)
        self._layout_chat_modes()

    def _toggle_chat_history(self, visible):
        self.convo_panel.setVisible(visible)
        self._layout_chat_modes()

    def _layout_chat_modes(self):
        available = self.width() - 220 - (216 if not self.convo_panel.isHidden() else 0)
        columns = 3 if available < 640 else 6
        if columns == self._mode_columns:
            return
        self._mode_columns = columns
        for button in self._mode_buttons:
            self._mode_grid.removeWidget(button)
        for column in range(6):
            self._mode_grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, button in enumerate(self._mode_buttons):
            self._mode_grid.addWidget(button, index // columns, index % columns)

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
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label in (
            "💬  Chat", "🔄  Self-Improve", "📊  Report", "📦  Proposals", "🧠  Knowledge",
            "🔔  Subscriptions", "🎮  Games", "🗂️  Work Tracker", "🌦️  Weather Station", "📈  Stocks Tracker", "📻  Radio",
            "📝  LinkedIn/Blog", "🕵️  Hacker", "🏕️  Cozy World", "🐉  Ethereal DND", "🎨  Penpot Studio",
            "🔁  Converter",
        ):
            self.nav_list.addItem(label)
        root_layout.addWidget(self.nav_list)

        self.pages = QStackedWidget()
        root_layout.addWidget(self.pages, 1)

        self.pages.addWidget(self._build_chat_page())
        self.pages.addWidget(self._build_selfimprove_page())
        self.pages.addWidget(self._build_report_page())
        self.pages.addWidget(self._build_proposals_page())
        self.pages.addWidget(self._build_knowledge_page())
        self.pages.addWidget(self._build_subscriptions_page())
        self.pages.addWidget(self._build_games_page())
        self.worklog_widget = WorklogWidget()
        self.pages.addWidget(self.worklog_widget)
        self.weather_station_widget = WeatherStationWidget()
        self.pages.addWidget(self.weather_station_widget)
        self.stocks_tracker_widget = StocksTrackerWidget()
        self.pages.addWidget(self.stocks_tracker_widget)
        self.radio_widget = RadioWidget()
        self.pages.addWidget(self.radio_widget)
        self.content_builder_widget = LinkedInBlogBuilderWidget()
        self.pages.addWidget(self.content_builder_widget)
        self.hacker_widget = HackerWidget()
        self.pages.addWidget(self.hacker_widget)
        self.cozy_world_widget = CozyWorldWidget()
        self.pages.addWidget(self.cozy_world_widget)
        self.ethereal_dnd_widget = EtherealDndWidget()
        self.pages.addWidget(self.ethereal_dnd_widget)
        self.penpot_studio_widget = PenpotStudioWidget()
        self.pages.addWidget(self.penpot_studio_widget)
        self.converter_widget = ConverterWidget()
        self.pages.addWidget(self.converter_widget)

        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav_list.currentRowChanged.connect(self._on_page_changed)
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

        outer_layout = QHBoxLayout(central_widget)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.setSpacing(16)

        # Conversation sidebar - lets you switch between saved conversations
        # or start a new one without losing the current one.
        self.current_conversation_file = None
        self.conversation_saved_length = len(webagent.context.assistant_convo)

        convo_panel = QFrame()
        self.convo_panel = convo_panel
        self._compact_chat = False
        convo_panel.setObjectName("convoPanel")
        convo_panel.setFixedWidth(200)
        convo_layout = QVBoxLayout(convo_panel)
        convo_layout.setContentsMargins(12, 14, 12, 12)
        convo_layout.setSpacing(12)

        convo_header_row = QHBoxLayout()
        convo_title_label = QLabel("Conversations")
        convo_title_label.setObjectName("mutedLabel")
        convo_header_row.addWidget(convo_title_label)
        convo_header_row.addStretch()
        new_convo_button = QPushButton("+ New")
        self.new_convo_button = new_convo_button
        new_convo_button.setMaximumWidth(64)
        new_convo_button.setToolTip("Start a new conversation")
        new_convo_button.clicked.connect(self.new_conversation_action)
        convo_header_row.addWidget(new_convo_button)
        convo_layout.addLayout(convo_header_row)

        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversationList")
        self.conversation_list.itemClicked.connect(self.load_selected_conversation)
        convo_layout.addWidget(self.conversation_list)

        outer_layout.addWidget(convo_panel)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        outer_layout.addLayout(main_layout, 1)

        # Header - one toolbar panel, two organized rows (title/agent/actions,
        # then mode toggles as pills) instead of the two separately-bordered
        # panels with plain checkboxes this used to be - that read as
        # visually messy once there were six of them plus an agent bar.
        header_frame = QFrame()
        header_frame.setObjectName("toolbar")
        header_frame_layout = QVBoxLayout(header_frame)
        header_frame_layout.setContentsMargins(18, 14, 18, 14)
        header_frame_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel("Gnosis")
        title_font = QFont(QApplication.font())
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        title_label.setFont(title_font)
        title_label.setObjectName("titleLabel")
        title_row.addWidget(title_label)
        self.history_button = QPushButton("History")
        self.history_button.setCheckable(True)
        self.history_button.setChecked(True)
        self.history_button.setToolTip("Show or hide saved conversations")
        self.history_button.toggled.connect(self._toggle_chat_history)
        title_row.addWidget(self.history_button)
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

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setToolTip(
            "Pick a local Ollama or connected cloud model for chat messages, "
            "overriding the mode toggles below. 'Auto' restores mode-based selection "
            "(Web/Think/Unfiltered/Code)."
        )
        self._populate_model_combo()
        self.model_combo.currentIndexChanged.connect(self.set_model_override)
        model_row.addWidget(self.model_combo, 1)
        cloud_button = QPushButton("Cloud models…")
        cloud_button.clicked.connect(self.open_cloud_models)
        model_row.addWidget(cloud_button)
        knowledge_button = QPushButton("Knowledge…")
        knowledge_button.clicked.connect(self.open_knowledge_settings)
        model_row.addWidget(knowledge_button)
        memory_button = QPushButton("Memory…")
        memory_button.clicked.connect(self.open_chat_memory)
        model_row.addWidget(memory_button)

        diff_review_button = QPushButton("📋 Diff Review")
        diff_review_button.setToolTip(
            "Paste a diff (optionally with a folder/zip for context), or leave the diff empty and "
            "point at a folder/zip to review the whole codebase directly."
        )
        diff_review_button.clicked.connect(self.open_diff_review)
        model_row.addWidget(diff_review_button)

        clear_button = QPushButton("🗑️")
        self.clear_chat_button = clear_button
        clear_button.setObjectName("clearButton")
        clear_button.setMaximumWidth(40)
        clear_button.setToolTip("Clear chat")
        clear_button.clicked.connect(self.clear_chat)
        title_row.addWidget(clear_button)

        header_frame_layout.addLayout(title_row)
        header_frame_layout.addLayout(model_row)

        def toggle_button(text, tooltip=None):
            button = QPushButton(text)
            button.setObjectName("modeToggle")
            button.setCheckable(True)
            if tooltip:
                button.setToolTip(tooltip)
            self._mode_buttons.append(button)
            return button

        self._mode_buttons = []
        self._mode_columns = 6
        toggles_row = QGridLayout()
        self._mode_grid = toggles_row
        toggles_row.setSpacing(6)

        self.voice_check = toggle_button("🎤 Voice chat", tooltip="Start a hands-free voice conversation with a live transcript")
        self.voice_check.toggled.connect(self.toggle_voice_mode)
        if not webagent.has_speech_recognition:
            self.voice_check.setEnabled(False)
            self.voice_check.setToolTip("Speech recognition is unavailable when SpeechRecognition is not installed.")
        toggles_row.addWidget(self.voice_check, 0, 0)

        self.tts_check = toggle_button("🔊 TTS")
        self.tts_check.toggled.connect(self.toggle_tts_mode)
        if not webagent.has_tts_backend():
            self.tts_check.setEnabled(False)
            self.tts_check.setToolTip("No supported TTS backend is available.")
        toggles_row.addWidget(self.tts_check, 0, 1)

        self.web_search_check = toggle_button("🔍 Web")
        self.web_search_check.toggled.connect(self.toggle_web_search)
        self.web_search_check.setChecked(webagent.context.web_search_mode)
        toggles_row.addWidget(self.web_search_check, 0, 2)

        self.deep_think_check = toggle_button(
            "🔬 Think", tooltip="Research multiple sources and return a structured analytical brief."
        )
        self.deep_think_check.toggled.connect(self.toggle_deep_think_mode)
        toggles_row.addWidget(self.deep_think_check, 0, 3)

        self.unfiltered_check = toggle_button("🕵️ Unfiltered")
        self.unfiltered_check.toggled.connect(self.toggle_unfiltered_mode)
        toggles_row.addWidget(self.unfiltered_check, 0, 4)

        self.coding_check = toggle_button("💻 Code")
        self.coding_check.toggled.connect(self.toggle_coding_mode)
        toggles_row.addWidget(self.coding_check, 0, 5)
        for column in range(6):
            toggles_row.setColumnStretch(column, 1)
        header_frame_layout.addLayout(toggles_row)

        main_layout.addWidget(header_frame)

        self.voice_panel = VoicePanel()
        self.voice_panel.mute_requested.connect(self.voice_session.mute)
        self.voice_panel.interrupt_requested.connect(self.interrupt_voice_chat)
        self.voice_panel.end_requested.connect(self.end_voice_chat)
        self.voice_panel.settings_requested.connect(self.open_voice_settings)
        main_layout.addWidget(self.voice_panel)

        # Chat display area - conversational style
        self.chat_display = QTextBrowser()
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setReadOnly(True)
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.setOpenLinks(False)
        self.chat_display.anchorClicked.connect(self._open_chat_source)
        self._source_inspections = {}
        self.chat_display.document().setDocumentMargin(16)
        self.interest_dashboard = SubscriptionDashboard()
        self.interest_dashboard.manage_requested.connect(lambda: self.nav_list.setCurrentRow(5))
        self.interest_dashboard.prompt_requested.connect(self._draft_interest_question)
        self.interest_dashboard.refresh_requested.connect(self._refresh_interest_updates)
        self.chat_surfaces = QStackedWidget()
        self.chat_surfaces.addWidget(self.interest_dashboard)
        self.chat_surfaces.addWidget(self.chat_display)
        main_layout.addWidget(self.chat_surfaces, 1)
        self.chat_display.document().contentsChanged.connect(self._sync_chat_dashboard)
        self._sync_chat_dashboard()
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_chat_scroll)
        scrollbar.rangeChanged.connect(self._on_chat_range_changed)

        self.reply_actions_widget = QWidget()
        actions = QHBoxLayout(self.reply_actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        self.copy_reply_button = QPushButton("Copy reply")
        self.copy_reply_button.setToolTip("Copy the latest reply")
        self.copy_reply_button.clicked.connect(self.copy_last_reply)
        actions.addWidget(self.copy_reply_button)
        self.retry_reply_button = QPushButton("Retry reply")
        self.retry_reply_button.setToolTip("Replace the last exchange with a new reply")
        self.retry_reply_button.clicked.connect(self.retry_last_reply)
        actions.addWidget(self.retry_reply_button)
        self.edit_prompt_button = QPushButton("Edit last prompt")
        self.edit_prompt_button.clicked.connect(self.edit_last_prompt)
        actions.addWidget(self.edit_prompt_button)
        actions.addStretch()
        self.jump_latest_button = QPushButton("Jump to latest")
        self.jump_latest_button.clicked.connect(self.jump_to_latest)
        self.jump_latest_button.hide()
        actions.addWidget(self.jump_latest_button)
        main_layout.addWidget(self.reply_actions_widget)
        self._update_reply_actions()

        # Activity phase and elapsed time remain visible throughout the turn.
        self.chat_status_label = self._muted_label("")
        self.chat_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.chat_status_label)

        composer = QFrame()
        composer.setObjectName("composer")
        composer.setFixedHeight(112)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(14, 10, 14, 10)
        composer_layout.setSpacing(4)
        input_layout = QHBoxLayout()
        input_layout.setSpacing(12)

        self.input_text = QTextEdit()
        self.input_text.setObjectName("inputText")
        self.input_text.setFixedHeight(64)
        self.input_text.setAcceptRichText(False)
        self.input_text.setPlaceholderText("Message Gnosis…")
        self.input_text.installEventFilter(self)
        input_layout.addWidget(self.input_text)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(76, 42)
        self.send_button.clicked.connect(self.on_send_button_clicked)
        input_layout.addWidget(self.send_button)

        composer_layout.addLayout(input_layout)

        # Hint label
        hint_label = QLabel("Ctrl+Enter to send")
        hint_label.setObjectName("mutedLabel")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        composer_layout.addWidget(hint_label)
        main_layout.addWidget(composer)

        self._refresh_conversation_list()
        self._sync_chat_dashboard()

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
        activity_button_row = QHBoxLayout()
        activity_button_row.addStretch()
        clear_activity_button = QPushButton("Clear Log")
        clear_activity_button.clicked.connect(self._clear_activity_log)
        activity_button_row.addWidget(clear_activity_button)
        activity_layout.addLayout(activity_button_row)
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

    def _clear_activity_log(self):
        reply = QMessageBox.question(
            self,
            "Clear Activity Log",
            "Are you sure you want to clear the activity log? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            clear_activity()
            self._refresh_activity_log()

    def _build_subscriptions_page(self):
        """Manage categorized interests with custom subjects, sources,
        sports teams, and validated weather locations."""
        page = QWidget()
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(15, 15, 15, 15)
        outer_layout.setSpacing(10)
        outer_layout.addWidget(self._section_title("🔔 Subscriptions"))
        outer_layout.addWidget(self._muted_label(
            "Make this space yours. Follow favorite teams, subjects, sources, and places "
            "to shape your welcome dashboard."
        ))

        self.subscription_status_label = self._muted_label("")
        outer_layout.addWidget(self.subscription_status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(18)

        scroll_layout.addWidget(self._build_custom_interest_section())
        self.subscription_catalog_buttons = {}  # (type, name) -> QPushButton
        for category, items in SUBSCRIPTION_CATALOG.items():
            scroll_layout.addWidget(self._build_subscription_category_section(category, items))
            if category == "Sports":
                scroll_layout.addWidget(self._build_weather_subscription_section())
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll, 1)

        self._refresh_subscription_buttons()
        self._refresh_weather_subscriptions()
        self._refresh_followed_interests()
        return page

    def _build_games_page(self):
        """Each game is its own pure-PyQt6 QPainter widget, no extra
        dependencies, and its own module (games/zuma_endless.py,
        games/solitaire.py, games/sudoku.py) rather than inlined here, so
        this file never owns any game's logic - one QTabWidget tab per
        game, same pattern the Knowledge page already uses for its
        sub-views."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        layout.addWidget(self._section_title("🎮 Games"))

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        zuma_page = QWidget()
        zuma_layout = QVBoxLayout(zuma_page)
        zuma_layout.addWidget(self._muted_label(
            "Zuma, but endless - match 3+ of the same color before the chain reaches the "
            "center. Aim with the mouse, left click or Space to shoot, right click or Q to "
            "swap your loaded ball."
        ))
        zuma_row = QHBoxLayout()
        zuma_row.addStretch()
        self.zuma_widget = ZumaEndlessWidget()
        zuma_row.addWidget(self.zuma_widget)
        zuma_row.addStretch()
        zuma_layout.addLayout(zuma_row)
        zuma_layout.addStretch()
        tabs.addTab(zuma_page, "Zuma Endless")

        solitaire_page = QWidget()
        solitaire_layout = QVBoxLayout(solitaire_page)
        solitaire_layout.addWidget(self._muted_label(
            "Klondike Solitaire - drag cards between piles, double-click to send a card to "
            "its foundation, Ctrl+Z to undo, N for a new game."
        ))
        solitaire_row = QHBoxLayout()
        solitaire_row.addStretch()
        self.solitaire_widget = SolitaireWidget()
        solitaire_row.addWidget(self.solitaire_widget)
        solitaire_row.addStretch()
        solitaire_layout.addLayout(solitaire_row)
        solitaire_layout.addStretch()
        tabs.addTab(solitaire_page, "Solitaire")

        sudoku_page = QWidget()
        sudoku_layout = QVBoxLayout(sudoku_page)
        sudoku_layout.addWidget(self._muted_label(
            "Sudoku - click a cell and type 1-9, Backspace to clear, arrow keys to move. "
            "Wrong numbers are checked instantly and highlighted in red - 5 mistakes and it's game over."
        ))
        sudoku_controls = QHBoxLayout()
        sudoku_controls.addWidget(QLabel("Difficulty:"))
        self.sudoku_difficulty_combo = QComboBox()
        self.sudoku_difficulty_combo.addItems(list(SUDOKU_DIFFICULTIES.keys()))
        self.sudoku_difficulty_combo.setCurrentText("Medium")
        sudoku_controls.addWidget(self.sudoku_difficulty_combo)
        sudoku_new_game_button = QPushButton("New Game")
        sudoku_new_game_button.clicked.connect(
            lambda: self.sudoku_widget._new_game(self.sudoku_difficulty_combo.currentText())
        )
        sudoku_controls.addWidget(sudoku_new_game_button)
        sudoku_controls.addStretch()
        sudoku_layout.addLayout(sudoku_controls)
        sudoku_row = QHBoxLayout()
        sudoku_row.addStretch()
        self.sudoku_widget = SudokuWidget()
        sudoku_row.addWidget(self.sudoku_widget)
        sudoku_row.addStretch()
        sudoku_layout.addLayout(sudoku_row)
        sudoku_layout.addStretch()
        tabs.addTab(sudoku_page, "Sudoku")

        mystery_page = QWidget()
        mystery_layout = QVBoxLayout(mystery_page)
        mystery_row = QHBoxLayout()
        self.mystery_widget = MysteryWidget()
        mystery_row.addWidget(self.mystery_widget, 1)
        mystery_layout.addLayout(mystery_row)
        tabs.addTab(mystery_page, "Mystery")

        tetris_page = QWidget()
        tetris_layout = QVBoxLayout(tetris_page)
        tetris_layout.addWidget(self._muted_label(
            "Tetris - Left/Right to move, Up to rotate, Down for a soft drop, Space to hard "
            "drop, P to pause. Clear lines to level up and speed up the fall."
        ))
        tetris_row = QHBoxLayout()
        tetris_row.addStretch()
        self.tetris_widget = TetrisWidget()
        tetris_row.addWidget(self.tetris_widget)
        tetris_row.addStretch()
        tetris_layout.addLayout(tetris_row)
        tetris_layout.addStretch()
        tabs.addTab(tetris_page, "Tetris")

        hangman_page = QWidget()
        hangman_layout = QVBoxLayout(hangman_page)
        hangman_layout.addWidget(self._muted_label(
            "Hangman - type a letter to guess. Six wrong guesses and it's game over."
        ))
        hangman_controls = QHBoxLayout()
        hangman_controls.addWidget(QLabel("Category:"))
        self.hangman_category_combo = QComboBox()
        self.hangman_category_combo.addItems(["Random"] + list(HANGMAN_CATEGORIES.keys()))
        self.hangman_category_combo.setCurrentText("Random")
        hangman_controls.addWidget(self.hangman_category_combo)
        hangman_new_game_button = QPushButton("New Word")
        hangman_new_game_button.clicked.connect(
            lambda: self.hangman_widget._new_game(self.hangman_category_combo.currentText())
        )
        hangman_controls.addWidget(hangman_new_game_button)
        hangman_controls.addStretch()
        hangman_layout.addLayout(hangman_controls)
        hangman_row = QHBoxLayout()
        hangman_row.addStretch()
        self.hangman_widget = HangmanWidget()
        hangman_row.addWidget(self.hangman_widget)
        hangman_row.addStretch()
        hangman_layout.addLayout(hangman_row)
        hangman_layout.addStretch()
        tabs.addTab(hangman_page, "Hangman")

        idle_island_page = QWidget()
        idle_island_layout = QVBoxLayout(idle_island_page)
        self.idle_island_widget = IdleIslandWidget()
        idle_island_layout.addWidget(self.idle_island_widget)
        tabs.addTab(idle_island_page, "Idle Island")

        racer_page = QWidget()
        racer_layout = QVBoxLayout(racer_page)
        racer_layout.addWidget(self._muted_label(
            "Neon Racer - anti-gravity racing, Wipeout-style. W/Up thrust, S/Down brake, "
            "A/D or arrow keys to steer, Space to power-slide through corners. Grab the "
            "glowing speed pads and stay off the walls across 3 laps against 3 rivals."
        ))
        racer_row = QHBoxLayout()
        racer_row.addStretch()
        self.neon_racer_widget = NeonRacerWidget()
        racer_row.addWidget(self.neon_racer_widget)
        racer_row.addStretch()
        racer_layout.addLayout(racer_row)
        racer_layout.addStretch()
        tabs.addTab(racer_page, "Neon Racer")

        minesweeper_page = QWidget()
        minesweeper_layout = QVBoxLayout(minesweeper_page)
        minesweeper_layout.addWidget(self._muted_label(
            "Minesweeper - left click to reveal a cell, right click to flag a suspected mine. "
            "Click a satisfied revealed number to clear its remaining neighbors at once."
        ))
        minesweeper_controls = QHBoxLayout()
        minesweeper_controls.addWidget(QLabel("Difficulty:"))
        self.minesweeper_difficulty_combo = QComboBox()
        self.minesweeper_difficulty_combo.addItems(list(MINESWEEPER_DIFFICULTIES.keys()))
        self.minesweeper_difficulty_combo.setCurrentText("Beginner")
        minesweeper_controls.addWidget(self.minesweeper_difficulty_combo)
        minesweeper_new_game_button = QPushButton("New Game")
        minesweeper_new_game_button.clicked.connect(
            lambda: self.minesweeper_widget._new_game(self.minesweeper_difficulty_combo.currentText())
        )
        minesweeper_controls.addWidget(minesweeper_new_game_button)
        minesweeper_controls.addStretch()
        minesweeper_layout.addLayout(minesweeper_controls)
        minesweeper_row = QHBoxLayout()
        minesweeper_row.addStretch()
        self.minesweeper_widget = MinesweeperWidget()
        minesweeper_row.addWidget(self.minesweeper_widget)
        minesweeper_row.addStretch()
        minesweeper_layout.addLayout(minesweeper_row)
        minesweeper_layout.addStretch()
        tabs.addTab(minesweeper_page, "Minesweeper")

        mastermind_page = QWidget()
        mastermind_layout = QVBoxLayout(mastermind_page)
        mastermind_layout.addWidget(self._muted_label(
            "Mastermind - click a palette swatch then a slot to place it, Submit to lock in a "
            "guess. Black pegs mean right color & position, white pegs mean right color only."
        ))
        mastermind_controls = QHBoxLayout()
        mastermind_controls.addWidget(QLabel("Difficulty:"))
        self.mastermind_difficulty_combo = QComboBox()
        self.mastermind_difficulty_combo.addItems(list(MASTERMIND_DIFFICULTIES.keys()))
        self.mastermind_difficulty_combo.setCurrentText("Standard")
        mastermind_controls.addWidget(self.mastermind_difficulty_combo)
        mastermind_new_game_button = QPushButton("New Game")
        mastermind_new_game_button.clicked.connect(
            lambda: self.mastermind_widget._new_game(self.mastermind_difficulty_combo.currentText())
        )
        mastermind_controls.addWidget(mastermind_new_game_button)
        mastermind_controls.addStretch()
        mastermind_layout.addLayout(mastermind_controls)
        mastermind_row = QHBoxLayout()
        mastermind_row.addStretch()
        self.mastermind_widget = MastermindWidget()
        mastermind_row.addWidget(self.mastermind_widget)
        mastermind_row.addStretch()
        mastermind_layout.addLayout(mastermind_row)
        mastermind_layout.addStretch()
        tabs.addTab(mastermind_page, "Mastermind")

        nonogram_page = QWidget()
        nonogram_layout = QVBoxLayout(nonogram_page)
        nonogram_layout.addWidget(self._muted_label(
            "Nonogram - fill cells using the row/column clues until the picture appears. Left "
            "click to fill, right click to mark a cell as definitely empty."
        ))
        nonogram_controls = QHBoxLayout()
        nonogram_controls.addWidget(QLabel("Picture:"))
        self.nonogram_pattern_combo = QComboBox()
        self.nonogram_pattern_combo.addItems(["Random"] + list(NONOGRAM_PATTERNS.keys()))
        self.nonogram_pattern_combo.setCurrentText("Random")
        nonogram_controls.addWidget(self.nonogram_pattern_combo)
        nonogram_new_game_button = QPushButton("New Puzzle")
        nonogram_new_game_button.clicked.connect(
            lambda: self.nonogram_widget._new_game(self.nonogram_pattern_combo.currentText())
        )
        nonogram_controls.addWidget(nonogram_new_game_button)
        nonogram_controls.addStretch()
        nonogram_layout.addLayout(nonogram_controls)
        nonogram_row = QHBoxLayout()
        nonogram_row.addStretch()
        self.nonogram_widget = NonogramWidget()
        nonogram_row.addWidget(self.nonogram_widget)
        nonogram_row.addStretch()
        nonogram_layout.addLayout(nonogram_row)
        nonogram_layout.addStretch()
        tabs.addTab(nonogram_page, "Nonogram")

        slider_puzzle_page = QWidget()
        slider_puzzle_layout = QVBoxLayout(slider_puzzle_page)
        slider_puzzle_layout.addWidget(self._muted_label(
            "Slider Puzzle - slide tiles into the empty slot to put them back in numeric "
            "order. Click a tile next to the empty slot, or use the arrow keys."
        ))
        slider_puzzle_controls = QHBoxLayout()
        slider_puzzle_controls.addWidget(QLabel("Size:"))
        self.slider_puzzle_difficulty_combo = QComboBox()
        self.slider_puzzle_difficulty_combo.addItems(list(SLIDER_DIFFICULTIES.keys()))
        self.slider_puzzle_difficulty_combo.setCurrentText("4x4 (15-puzzle)")
        slider_puzzle_controls.addWidget(self.slider_puzzle_difficulty_combo)
        slider_puzzle_new_game_button = QPushButton("New Shuffle")
        slider_puzzle_new_game_button.clicked.connect(
            lambda: self.slider_puzzle_widget._new_game(self.slider_puzzle_difficulty_combo.currentText())
        )
        slider_puzzle_controls.addWidget(slider_puzzle_new_game_button)
        slider_puzzle_controls.addStretch()
        slider_puzzle_layout.addLayout(slider_puzzle_controls)
        slider_puzzle_row = QHBoxLayout()
        slider_puzzle_row.addStretch()
        self.slider_puzzle_widget = SliderPuzzleWidget()
        slider_puzzle_row.addWidget(self.slider_puzzle_widget)
        slider_puzzle_row.addStretch()
        slider_puzzle_layout.addLayout(slider_puzzle_row)
        slider_puzzle_layout.addStretch()
        tabs.addTab(slider_puzzle_page, "Slider Puzzle")

        return page

    def _build_collapsible_section(self, title, content, expanded=True):
        """A category section whose body can be collapsed - the catalog is
        expected to keep growing as more sources get drilled into per
        category, and a long page of always-expanded button grids won't
        stay usable once there are many more of them than today's 5-6
        categories."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toggle = QPushButton(f"{'▼' if expanded else '▶'}  {title}")
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setObjectName("categoryToggle")
        toggle.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        content.setVisible(expanded)
        toggle.toggled.connect(lambda checked: self._on_category_toggled(checked, title, toggle, content))
        layout.addWidget(toggle)
        layout.addWidget(content)
        return section

    def _on_category_toggled(self, checked, title, toggle, content):
        toggle.setText(f"{'▼' if checked else '▶'}  {title}")
        content.setVisible(checked)

    def _track_subscription_worker(self, worker):
        self._subscription_workers.append(worker)
        def finished():
            if worker in self._subscription_workers:
                self._subscription_workers.remove(worker)
            if self._close_requested:
                QTimer.singleShot(0, self.close)
        worker.finished.connect(finished)

    def _build_custom_interest_section(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._muted_label("Follow any subject you like—an artist, hobby, league, destination, or local issue. Add a website if you prefer a specific source."))
        row = QHBoxLayout()
        self.interest_category_combo = QComboBox()
        for key, label in INTEREST_CATEGORIES.items():
            if key != "weather":
                self.interest_category_combo.addItem(label, key)
        self.interest_category_combo.setCurrentIndex(self.interest_category_combo.findData("other"))
        self.interest_name_input = QLineEdit()
        self.interest_name_input.setPlaceholderText("What interests you?")
        row.addWidget(self.interest_category_combo)
        row.addWidget(self.interest_name_input, 1)
        layout.addLayout(row)
        self.interest_keywords_input = QLineEdit()
        self.interest_keywords_input.setPlaceholderText("Optional aliases, separated by commas (e.g. F1, Formula One)")
        layout.addWidget(self.interest_keywords_input)
        row = QHBoxLayout()
        self.interest_url_input = QLineEdit()
        self.interest_url_input.setPlaceholderText("Optional website URL (https://…)")
        self.interest_add_button = QPushButton("Follow interest")
        self.interest_add_button.clicked.connect(self._add_custom_interest)
        row.addWidget(self.interest_url_input, 1)
        row.addWidget(self.interest_add_button)
        layout.addLayout(row)
        layout.addWidget(self._muted_label("Your followed topics and sources · Click × to unfollow"))
        self.followed_interest_grid = QGridLayout()
        layout.addLayout(self.followed_interest_grid)
        return self._build_collapsible_section("Your interests", content)

    def _add_custom_interest(self):
        name = self.interest_name_input.text().strip()
        category = self.interest_category_combo.currentData()
        keywords = self.interest_keywords_input.text().split(",")
        url = self.interest_url_input.text().strip()
        def added(record):
            for field in (self.interest_name_input, self.interest_keywords_input, self.interest_url_input):
                field.clear()
            self.subscription_status_label.setText(f'Following "{record["name"]}".')
            self._refresh_subscription_buttons()
        if not url:
            try:
                added(webagent.add_interest_subscription(name, category, keywords=keywords))
            except ValueError as error:
                self.subscription_status_label.setText(str(error))
            return
        self.interest_add_button.setEnabled(False)
        fields = (self.interest_name_input, self.interest_keywords_input, self.interest_url_input, self.interest_category_combo)
        for field in fields:
            field.setEnabled(False)
        self.subscription_status_label.setText("Checking the website…")
        worker = CycleWorker(lambda: webagent.add_interest_subscription(name, category, keywords=keywords, url=url))
        self._track_subscription_worker(worker)
        worker.result_ready.connect(added)
        worker.error_occurred.connect(self.subscription_status_label.setText)
        def finished():
            self.interest_add_button.setEnabled(True)
            for field in fields:
                field.setEnabled(True)
        worker.finished.connect(finished)
        worker.start()

    def _refresh_followed_interests(self):
        if not hasattr(self, "followed_interest_grid"):
            return
        while self.followed_interest_grid.count():
            taken = self.followed_interest_grid.takeAt(0)
            if taken.widget():
                taken.widget().deleteLater()
        records = [record for record in subscriptions.list_subscriptions() if record.get("type") in ("topic", "website")]
        for index, record in enumerate(sorted(records, key=lambda record: (category_for(record), record["name"].casefold()))):
            button = QPushButton(f'{record["name"][:60]} · {INTEREST_CATEGORIES[category_for(record)]} ×')
            button.setToolTip(f'Unfollow {record["name"]}')
            button.clicked.connect(lambda checked=False, key=record["id"]: self._remove_followed_interest(key))
            self.followed_interest_grid.addWidget(button, index // 2, index % 2)
        if not records:
            self.followed_interest_grid.addWidget(self._muted_label("Choose a suggestion below or add your own interest."), 0, 0)

    def _remove_followed_interest(self, subscription_id):
        subscriptions.remove_subscription(subscription_id)
        self._refresh_subscription_buttons()
        self.subscription_status_label.setText("Interest unfollowed.")

    def _build_subscription_category_section(self, category, items):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(8)
        layout.addLayout(grid)
        columns = 3
        for index, item in enumerate(items):
            button = QPushButton(item["name"])
            button.setObjectName("subscriptionButton")
            button.setCheckable(True)
            self._set_subscription_button_style(button, "off")
            button.toggled.connect(
                lambda checked, item=item, button=button: self._on_catalog_button_toggled(checked, item, button)
            )
            self.subscription_catalog_buttons[(item["type"], item["name"])] = button
            grid.addWidget(button, index // columns, index % columns)
        if category == "Sports":
            layout.addWidget(self._build_sports_subscription_section(collapsible=False))
        return self._build_collapsible_section(category, content, expanded=category in ("News", "Sports", "Entertainment"))

    def _build_weather_subscription_section(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._muted_label(
            "No preset list here - type a location and it's validated against the live "
            "weather source before saving."
        ))

        add_row = QHBoxLayout()
        self.weather_location_input = QLineEdit()
        self.weather_location_input.setPlaceholderText("City, state/country (e.g. Tucson, AZ)")
        add_row.addWidget(self.weather_location_input, 1)
        self.weather_add_button = QPushButton("+ Add")
        self.weather_add_button.clicked.connect(self._add_weather_subscription_clicked)
        add_row.addWidget(self.weather_add_button)
        layout.addLayout(add_row)

        self.weather_grid = QGridLayout()
        self.weather_grid.setSpacing(8)
        layout.addLayout(self.weather_grid)
        return self._build_collapsible_section("Weather", content)

    def _build_sports_subscription_section(self, collapsible=True):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._muted_label('Pick a league, load its teams, and follow your favorites for results and upcoming games.'))
        row = QHBoxLayout()
        self.sports_league_combo = QComboBox()
        for key, (label, sport, slug) in core_sports.LEAGUES.items():
            self.sports_league_combo.addItem(label, key)
        self.sports_league_combo.currentIndexChanged.connect(self._sports_league_changed)
        row.addWidget(self.sports_league_combo, 1)
        self.sports_load_button = QPushButton('Load teams')
        self.sports_load_button.clicked.connect(self._load_sports_teams)
        row.addWidget(self.sports_load_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.sports_team_combo = QComboBox()
        self.sports_team_combo.setEditable(True)
        self.sports_team_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sports_team_combo.setPlaceholderText('Load a league to choose a team')
        self.sports_team_combo.setEnabled(False)
        self.sports_team_combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.sports_team_combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        row.addWidget(self.sports_team_combo, 1)
        self.sports_follow_button = QPushButton('Follow team')
        self.sports_follow_button.setEnabled(False)
        self.sports_follow_button.clicked.connect(self._follow_sports_team)
        row.addWidget(self.sports_follow_button)
        layout.addLayout(row)
        self.sports_status = self._muted_label('Premier League is selected. Load teams to choose Manchester United or another club.')
        layout.addWidget(self.sports_status)
        self.sports_followed_grid = QGridLayout()
        self.sports_followed_grid.setSpacing(8)
        layout.addLayout(self.sports_followed_grid)
        self._refresh_sports_subscriptions()
        return self._build_collapsible_section('Sports', content) if collapsible else content

    def _sports_league_changed(self):
        self.sports_team_combo.clear()
        self.sports_team_combo.setEnabled(False)
        self.sports_follow_button.setEnabled(False)
        self.sports_status.setText('Load teams for this league.')

    def _load_sports_teams(self):
        if self._sports_worker is not None:
            return
        key = self.sports_league_combo.currentData()
        self.sports_league_combo.setEnabled(False)
        self.sports_load_button.setEnabled(False)
        self.sports_follow_button.setEnabled(False)
        self.sports_team_combo.setEnabled(False)
        self.sports_status.setText('Loading teams…')
        worker = CycleWorker(lambda: core_sports.list_teams(key))
        self._sports_worker = worker
        worker.result_ready.connect(self._on_sports_teams_loaded)
        worker.error_occurred.connect(lambda message: self.sports_status.setText(message))
        worker.finished.connect(self._on_sports_directory_finished)
        worker.start()

    def _on_sports_teams_loaded(self, teams):
        self.sports_team_combo.clear()
        for team in teams:
            self.sports_team_combo.addItem(team['name'], team['id'])
        index = self.sports_team_combo.findText('Manchester United')
        if index >= 0:
            self.sports_team_combo.setCurrentIndex(index)
        self.sports_team_combo.setEnabled(bool(teams))
        self.sports_follow_button.setEnabled(bool(teams))
        self.sports_status.setText(f'{len(teams)} teams loaded. Choose a team to follow.')

    def _on_sports_directory_finished(self):
        worker = self._sports_worker
        self._sports_worker = None
        self.sports_league_combo.setEnabled(True)
        self.sports_load_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()
        if self._close_requested:
            QTimer.singleShot(0, self.close)

    def _follow_sports_team(self):
        index = self.sports_team_combo.findText(self.sports_team_combo.currentText(), Qt.MatchFlag.MatchFixedString)
        if index < 0:
            self.sports_status.setText('Choose a team from the loaded list.')
            return
        try:
            record = webagent.add_sports_team_subscription(self.sports_league_combo.currentData(), self.sports_team_combo.itemData(index))
        except (ValueError, KeyError, webagent.requests.RequestException) as error:
            self.sports_status.setText(str(error))
            return
        self.sports_status.setText(f"Following {record['name']}.")
        self._refresh_subscription_buttons()

    def _refresh_sports_subscriptions(self):
        if not hasattr(self, 'sports_followed_grid'):
            return
        while self.sports_followed_grid.count():
            item = self.sports_followed_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, record in enumerate(subscriptions.list_subscriptions('team')):
            metadata = record.get('metadata', {})
            league = metadata.get('league_name') or core_sports.LEAGUE_NAMES.get(metadata.get('league_slug'), 'Team')
            button = QPushButton(f"{record['name']} · {league} ×")
            button.setToolTip('Unfollow this team')
            button.clicked.connect(lambda checked=False, key=record['id']: self._unfollow_sports_team(key))
            self.sports_followed_grid.addWidget(button, index // 2, index % 2)

    def _unfollow_sports_team(self, subscription_id):
        subscriptions.remove_subscription(subscription_id)
        self._refresh_subscription_buttons()

    def _set_subscription_button_style(self, button, state):
        """state is "off" (grey - not subscribed) or "on" (green -
        subscribed). A failed subscribe attempt reverts to "off" rather than
        a distinct error color - the failure reason still shows in
        subscription_status_label. A Qt dynamic property + unpolish/polish,
        not setStyleSheet, so this stays driven by the shared
        #subscriptionButton QSS rules (get_stylesheet) rather than an inline
        style that would need to be kept in sync by hand."""
        button.setProperty("subState", state)
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_subscription_buttons(self):
        subscribed = {(r["type"], r["name"].casefold()) for r in subscriptions.list_subscriptions()}
        for (sub_type, name), button in self.subscription_catalog_buttons.items():
            is_subscribed = (sub_type, name.casefold()) in subscribed
            button.blockSignals(True)
            button.setChecked(is_subscribed)
            button.blockSignals(False)
            self._set_subscription_button_style(button, "on" if is_subscribed else "off")
        self._refresh_interest_dashboard()
        self._refresh_sports_subscriptions()
        self._refresh_followed_interests()

    def _on_catalog_button_toggled(self, checked, item, button):
        if checked:
            self._subscribe_catalog_item(item, button)
        else:
            self._unsubscribe_catalog_item(item, button)

    def _subscribe_catalog_item(self, item, button):
        button.setEnabled(False)
        self.subscription_status_label.setText(f'Adding "{item["name"]}"...')
        if item["type"] == "topic":
            try:
                record = webagent.add_interest_subscription(item["name"], item["category"], keywords=item.get("keywords"))
            except ValueError as error:
                self._on_catalog_subscribe_error(str(error), button)
                return
            self._on_catalog_subscribe_success(record, button)
            return
        if item["type"] == "website":
            add_fn = lambda: webagent.add_interest_subscription(item["name"], item["category"], url=item["url"])  # noqa: E731
        else:
            add_fn = lambda: webagent.add_team_subscription(item["name"])  # noqa: E731

        self._subscription_worker = CycleWorker(add_fn)
        self._track_subscription_worker(self._subscription_worker)
        self._subscription_worker.result_ready.connect(
            lambda record, button=button: self._on_catalog_subscribe_success(record, button)
        )
        self._subscription_worker.error_occurred.connect(
            lambda message, button=button: self._on_catalog_subscribe_error(message, button)
        )
        self._subscription_worker.start()

    def _on_catalog_subscribe_success(self, record, button):
        self.subscription_status_label.setText(f'Subscribed to "{record["name"]}".')
        self._set_subscription_button_style(button, "on")
        button.setEnabled(True)
        self._refresh_interest_dashboard()
        self._refresh_sports_subscriptions()
        self._refresh_followed_interests()

    def _on_catalog_subscribe_error(self, message, button):
        self.subscription_status_label.setText(message)
        button.blockSignals(True)
        button.setChecked(False)
        button.blockSignals(False)
        self._set_subscription_button_style(button, "off")
        button.setEnabled(True)

    def _unsubscribe_catalog_item(self, item, button):
        lowered = item["name"].casefold()
        for record in subscriptions.list_subscriptions(sub_type=item["type"]):
            if record["name"].casefold() == lowered:
                subscriptions.remove_subscription(record["id"])
                self.subscription_status_label.setText(f'Unsubscribed from "{item["name"]}".')
                break
        self._set_subscription_button_style(button, "off")
        self._refresh_interest_dashboard()
        self._refresh_sports_subscriptions()
        self._refresh_followed_interests()

    def _refresh_weather_subscriptions(self):
        while self.weather_grid.count():
            taken = self.weather_grid.takeAt(0)
            widget = taken.widget()
            if widget:
                widget.deleteLater()
        columns = 4
        for index, record in enumerate(subscriptions.list_subscriptions(sub_type="weather")):
            button = QPushButton(f'{record["name"]} ✕')
            button.setObjectName("subscriptionButton")
            self._set_subscription_button_style(button, "on")  # only ever rendered for an already-subscribed location
            button.clicked.connect(lambda _checked=False, record=record: self._remove_weather_subscription_clicked(record))
            self.weather_grid.addWidget(button, index // columns, index % columns)
        self._refresh_interest_dashboard()

    def _sync_chat_dashboard(self):
        empty = self.chat_display.document().isEmpty()
        self.chat_surfaces.setCurrentWidget(self.interest_dashboard if empty else self.chat_display)
        if hasattr(self, 'reply_actions_widget'):
            self.reply_actions_widget.setVisible(not empty)
        if hasattr(self, 'chat_status_label'):
            self.chat_status_label.setVisible(not empty)
        if empty:
            self._refresh_interest_dashboard()

    def _refresh_interest_dashboard(self):
        self.interest_dashboard.set_records(subscriptions.list_subscriptions())

    def _on_page_changed(self, index):
        if index == 0:
            self._refresh_interest_dashboard()

    def _draft_interest_question(self, prompt):
        if self._response_active:
            return
        self.input_text.setPlainText(prompt)
        self.input_text.setFocus()

    def _refresh_interest_updates(self):
        if self._dashboard_worker is not None:
            self._dashboard_worker.cancel()
            self.interest_dashboard.refresh_button.setText('Stopping…')
            self.interest_dashboard.refresh_button.setEnabled(False)
            return
        if self._close_requested:
            return
        self._refresh_interest_dashboard()
        records = copy.deepcopy(self.interest_dashboard.records)
        if not records:
            return
        self.interest_dashboard.set_busy(True)
        worker = DashboardUpdateWorker(records, webagent.get_subscription_dashboard_evidence)
        self._dashboard_worker = worker
        worker.updated.connect(self.interest_dashboard.set_update)
        worker.finished.connect(self._on_interest_updates_finished)
        worker.start()

    def _on_interest_updates_finished(self):
        worker = self._dashboard_worker
        self._dashboard_worker = None
        self.interest_dashboard.set_busy(False)
        if worker is not None:
            worker.deleteLater()
        if self._close_requested:
            QTimer.singleShot(0, self.close)

    def _add_weather_subscription_clicked(self):
        location = self.weather_location_input.text().strip()
        if not location:
            self.subscription_status_label.setText("Enter a location first.")
            return
        self.weather_add_button.setEnabled(False)
        self.subscription_status_label.setText("Adding...")
        add_fn = lambda: webagent.add_weather_subscription(location)  # noqa: E731
        self._subscription_worker = CycleWorker(add_fn)
        self._track_subscription_worker(self._subscription_worker)
        self._subscription_worker.result_ready.connect(self._on_weather_subscription_added)
        self._subscription_worker.error_occurred.connect(self._on_weather_subscription_add_error)
        self._subscription_worker.start()

    def _on_weather_subscription_added(self, record):
        self.subscription_status_label.setText(f'Added "{record["name"]}".')
        self.weather_location_input.clear()
        self._refresh_weather_subscriptions()
        self.weather_add_button.setEnabled(True)

    def _on_weather_subscription_add_error(self, message):
        self.subscription_status_label.setText(message)
        self.weather_add_button.setEnabled(True)

    def _remove_weather_subscription_clicked(self, record):
        subscriptions.remove_subscription(record["id"])
        self.subscription_status_label.setText(f'Removed "{record["name"]}".')
        self._refresh_weather_subscriptions()

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
    
    def on_send_button_clicked(self):
        """The Send button doubles as Stop while a response is running."""
        if self._response_active and self.response_worker is not None:
            if self._voice_turn:
                self.voice_session.interrupt()
            self.response_worker.cancel()
            self.send_button.setEnabled(False)
            self._set_chat_activity("Stopping")
        else:
            self.send_message()

    def send_message(self, user_input=None):
        """Send user message and get AI response"""
        if self._response_active:
            return
        from_input = user_input is None
        user_input = (self.input_text.toPlainText() if from_input else user_input).strip()

        if not user_input:
            QMessageBox.warning(self, "Empty Input", "Please enter a message.")
            return

        if self._editing_last_turn:
            self._restore_last_turn()
            self._editing_last_turn = False
            self.edit_prompt_button.setText("Edit last prompt")
        self._voice_turn = self.voice_session.enabled
        if self._voice_turn:
            self.voice_session.begin_reply()
        self._last_turn_context = copy.deepcopy(webagent.context.assistant_convo)
        self._last_turn_html = self.chat_display.toHtml()
        self._last_prompt = user_input
        self._last_reply = ""
        # Scheduler chat can mutate real cron tasks; its actions aren't replayable.
        self._last_retry_allowed = webagent.context.current_agent != "scheduler"
        self._response_active = True
        self._activity_outcome = "Finished"
        self._activity_started = time.perf_counter()
        self._set_chat_activity("Preparing response")
        self.activity_timer.start()
        self._update_reply_actions()
        self.jump_to_latest()

        # Display user message
        self.display_message(user_input, is_user=True)
        if from_input:
            self.input_text.clear()

        # Disable input while processing
        self.input_text.setEnabled(False)
        self.send_button.setText("Stop")
        self.agent_combo.setEnabled(False)
        self.conversation_list.setEnabled(False)
        self.new_convo_button.setEnabled(False)
        self.clear_chat_button.setEnabled(False)

        # Initialize streaming response placeholder
        self.current_response = ""
        self.assistant_message_started = False
        self._pending_sources = None
        self._assistant_cursor = None
        self.response_start_time = datetime.now()

        # Start response worker
        self.response_worker = ResponseWorker(user_input)
        self.response_worker.response_chunk.connect(self.on_response_chunk)
        self.response_worker.response_ready.connect(self.on_response_ready)
        self.response_worker.error_occurred.connect(self.on_error)
        self.response_worker.cancelled.connect(self.on_response_cancelled)
        self.response_worker.finished.connect(self.on_response_finished)
        self.response_worker.status.connect(self.on_chat_status)
        self.response_worker.sources.connect(self.on_sources)
        self.response_worker.start()

    def _set_chat_activity(self, message):
        self._activity_phase = message.rstrip(". ")
        self._refresh_chat_activity()

    def _refresh_chat_activity(self):
        if self._activity_started is None:
            return
        elapsed = time.perf_counter() - self._activity_started
        self.chat_status_label.setText(f"{self._activity_phase} · {elapsed:.1f}s")

    def on_chat_status(self, message):
        if self._activity_phase == "Stopping":
            return
        # A pending API call may be loading or evaluating; don't guess which.
        self._set_chat_activity("Waiting for model" if message == "Writing a response..." else message)
        if self._voice_turn and self.voice_session.enabled and self.voice_session.speaker is None:
            self.voice_panel.set_phase(self._activity_phase)

    @contextmanager
    def _chat_scroll_guard(self):
        scrollbar = self.chat_display.verticalScrollBar()
        previous = scrollbar.value()
        selected = self.chat_display.textCursor()
        selection = (selected.anchor(), selected.position()) if selected.hasSelection() else None
        was_updating = self._updating_chat
        self._updating_chat = True
        try:
            yield
        finally:
            if selection:
                restored = QTextCursor(self.chat_display.document())
                restored.setPosition(selection[0])
                restored.setPosition(selection[1], QTextCursor.MoveMode.KeepAnchor)
                self.chat_display.setTextCursor(restored)
            scrollbar.setValue(scrollbar.maximum() if self._follow_latest else previous)
            self._updating_chat = was_updating
            self._update_jump_button()

    def _on_chat_scroll(self, value):
        if not self._updating_chat:
            scrollbar = self.chat_display.verticalScrollBar()
            self._follow_latest = scrollbar.maximum() - value <= 24
            self._update_jump_button()

    def _on_chat_range_changed(self, minimum, maximum):
        if self._follow_latest:
            previous = self._updating_chat
            self._updating_chat = True
            self.chat_display.verticalScrollBar().setValue(maximum)
            self._updating_chat = previous
        self._update_jump_button()

    def _update_jump_button(self, *args):
        if hasattr(self, "jump_latest_button"):
            scrollbar = self.chat_display.verticalScrollBar()
            self.jump_latest_button.setVisible(not self._follow_latest and scrollbar.value() < scrollbar.maximum())

    def jump_to_latest(self):
        self._follow_latest = True
        self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum())
        self._update_jump_button()

    def _update_reply_actions(self):
        idle = not self._response_active
        self.copy_reply_button.setEnabled(idle and bool(self._last_reply))
        can_replace = idle and bool(self._last_prompt) and self._last_turn_context is not None and self._last_retry_allowed
        self.retry_reply_button.setEnabled(can_replace and not self._editing_last_turn)
        self.edit_prompt_button.setEnabled(can_replace)

    def copy_last_reply(self):
        if not self._response_active and self._last_reply:
            QApplication.clipboard().setText(self._last_reply)

    def _restore_last_turn(self):
        webagent.context.assistant_convo = copy.deepcopy(self._last_turn_context)
        self.chat_display.setHtml(self._last_turn_html)
        self.conversation_saved_length = -1
        self._pending_sources = None
        self.jump_to_latest()

    def retry_last_reply(self):
        if not self.retry_reply_button.isEnabled():
            return
        prompt = self._last_prompt
        self._restore_last_turn()
        self.send_message(user_input=prompt)

    def edit_last_prompt(self):
        if not self.edit_prompt_button.isEnabled():
            return
        if self._editing_last_turn:
            self.input_text.setPlainText(self._draft_before_edit)
            self._editing_last_turn = False
            self.edit_prompt_button.setText("Edit last prompt")
        else:
            self._draft_before_edit = self.input_text.toPlainText()
            self.input_text.setPlainText(self._last_prompt)
            self._editing_last_turn = True
            self.edit_prompt_button.setText("Cancel edit")
        self.input_text.setFocus()
        self._update_reply_actions()

    def _reset_reply_actions(self):
        if self._editing_last_turn:
            self.input_text.setPlainText(self._draft_before_edit)
        self._editing_last_turn = False
        self._last_prompt = ""
        self._last_reply = ""
        self._last_turn_context = None
        self.edit_prompt_button.setText("Edit last prompt")
        self._update_reply_actions()
        self.chat_status_label.clear()
        self.jump_to_latest()

    def on_response_chunk(self, chunk):
        """Handle streaming response chunks"""
        with self._chat_scroll_guard():
            self.current_response += chunk
            if self._voice_turn:
                self.voice_session.feed(chunk)

            if not self.assistant_message_started:
                self._set_chat_activity("Replying")
                self._assistant_cursor = self._insert_message_card(False, self.response_start_time)
                self.assistant_message_started = True

            self._assistant_cursor.insertText(chunk)

    def on_response_ready(self, response):
        """Handle complete AI response"""
        with self._chat_scroll_guard():
            self._assistant_cursor = None
            self.assistant_message_started = False

            # Keep the plain reply for copying, excluding sources and decoration.
            self._last_reply = response
            self.current_response = ""

            # None means this wasn't a research turn (say nothing); [] means
            # web search/Deep Think ran and found nothing real - render that
            # distinctly rather than silently, which is the whole point of this.
            if self._pending_sources is not None:
                self._render_sources(self._pending_sources)
                self._pending_sources = None

    def on_sources(self, sources):
        """Buffers the evidence list for this turn. Fires before the assistant
        bubble opens (research happens before the model call starts streaming),
        so rendering immediately here would place it above the answer instead
        of under it - on_response_ready renders the buffered value once the
        bubble is closed."""
        self._pending_sources = sources

    def _open_chat_source(self, url):
        if url.scheme() != "evidence":
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
            return
        source = self._source_inspections.get(url.path())
        if source is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Evidence behind this reply")
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        provenance = source.get("provenance") or {}
        details = {
            "Source": source.get("title"),
            "Original URL": provenance.get("url") or source.get("url"),
            "Origin": provenance.get("origin") or source.get("search_provider"),
            "Captured": source.get("captured_at") or "Unknown",
            "Date basis": provenance.get("date_basis") or "Source capture",
            "Published": provenance.get("published_at") or source.get("published_at") or "Unknown",
            "Verification": source.get("verification_status") or "Not independently verified",
            "Retrieval": provenance.get("retrieval_method") or "Selected by research tools",
            "Matched terms": ", ".join(provenance.get("matched_terms", [])),
            "Query coverage": provenance.get("coverage"),
            "Semantic similarity": provenance.get("semantic_similarity"),
            "Embedding status": provenance.get("embedding_status"),
        }
        header = "".join(f"<p><b>{html.escape(k)}:</b> {html.escape(str(v or 'Unknown'))}</p>" for k, v in details.items())
        view.setHtml(header + "<hr><b>Evidence passage</b><pre style='white-space:pre-wrap'>" +
                     html.escape(str(source.get("content") or source.get("snippet") or "No passage retained.")) + "</pre>")
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _render_sources(self, sources):
        with self._chat_scroll_guard():
            cursor = QTextCursor(self.chat_display.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertBlock()
            cursor.setBlockFormat(QTextBlockFormat())
            cursor.setCharFormat(QTextCharFormat())

            if not sources:
                cursor.insertHtml(
                    f'<div style="margin: 2px 0 14px 0; font-size: 12px; color: {TEXT_MUTED};">'
                    f'⚠️ No live web results for this answer - it is not backed by fresh search data.</div>'
                )
                return

            items = []
            for result in sources[:8]:
                title = html.escape(str(result.get('title') or result.get('url') or 'Source'))
                url = (result.get('provenance') or {}).get('url') or result.get('url') or ''
                key = str(len(self._source_inspections))
                self._source_inspections[key] = copy.deepcopy(result)
                inspect_link = f' <a href="evidence:{key}" style="color: {ACCENT_LIGHT};">Inspect evidence</a>'
                confidence = result.get('truthfulness_confidence')
                conf_text = f' (source score {confidence}/100)' if isinstance(confidence, (int, float)) else ''
                if url:
                    if not str(url).startswith(('http://', 'https://')):
                        url = 'evidence:' + key
                    items.append(f'<li><a href="{html.escape(url)}" style="color: {ACCENT_LIGHT};">{title}</a>{conf_text}{inspect_link}</li>')
                else:
                    items.append(f'<li>{title}{conf_text}{inspect_link}</li>')

            cursor.insertHtml(
                f'<div style="margin: 2px 0 14px 0; font-size: 12px; color: {TEXT_SECONDARY};">'
                f'<b>Sources:</b><ul style="margin: 4px 0 0 0; padding-left: 18px;">{"".join(items)}</ul></div>'
            )

    def on_response_finished(self):
        """Handle response completion - always fires (success, error, or a
        user-initiated stop), so this is the one place that resets the
        Send/Stop button regardless of how the turn ended."""
        self._response_active = False
        self.activity_timer.stop()
        self._set_chat_activity(self._activity_outcome)
        self._update_reply_actions()
        self.input_text.setEnabled(True)
        self.input_text.setFocus()
        self.send_button.setText("Send")
        self.send_button.setEnabled(True)
        self.agent_combo.setEnabled(True)
        self.conversation_list.setEnabled(True)
        self.new_convo_button.setEnabled(True)
        self.clear_chat_button.setEnabled(True)
        if self._voice_turn:
            self.voice_session.finish_reply(success=self._activity_outcome == "Finished")
            self._voice_turn = False
        if self._close_requested:
            QTimer.singleShot(0, self.close)

    def on_response_cancelled(self):
        """A deliberate, user-initiated stop - distinct from on_error so it
        doesn't pop an alarming error dialog for something the user asked
        for. Whatever streamed before the stop stays on screen."""
        with self._chat_scroll_guard():
            cursor = QTextCursor(self.chat_display.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._assistant_cursor = None
            self.assistant_message_started = False
            cursor.insertHtml(
                f'<div style="margin: 0 0 14px 0; font-size: 12px; color: {TEXT_MUTED}; font-style: italic;">Stopped.</div>'
            )
            self._last_reply = self.current_response
            self._activity_outcome = "Stopped"
            self.current_response = ""

    def on_error(self, error_msg):
        """Handle errors"""
        if self._voice_turn:
            self.voice_session.cancel_audio()
        self._last_reply = self.current_response
        self._activity_outcome = "Failed"
        self._set_chat_activity("Failed")
        QMessageBox.critical(self, "Error", error_msg)
        self.input_text.setEnabled(True)

    def set_agent(self):
        if self._response_active:
            return
        self._reset_reply_actions()
        selected = self.agent_combo.currentText()
        result = webagent.job_command(selected if selected != "default" else "default")
        self.current_agent_label.setText(f"Current: {selected}")
        self.display_message(result, is_user=False)
        if webagent.context.current_agent:
            self.agent_combo.setCurrentText(webagent.context.current_agent)
        else:
            self.agent_combo.setCurrentText("default")

    def _populate_model_combo(self):
        """Fill the model picker with every locally-installed Ollama model,
        'Auto' first so mode-based selection (_selected_model()) stays the
        default with nothing selected."""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("Auto (mode-based)", None)
        for tag in core_models.list_installed():
            self.model_combo.addItem(tag, tag)
        for model in cloud_models.configured_models():
            provider, _, model_id = model.partition(":")
            self.model_combo.addItem(f"{cloud_models.PROVIDERS[provider][0]} · {model_id}", model)
        selected = self.model_combo.findData(webagent.context.selected_model)
        self.model_combo.setCurrentIndex(max(0, selected))
        self.model_combo.blockSignals(False)

    def open_chat_memory(self):
        agent = webagent.context.current_agent or "default"
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Conversation memory · {agent}")
        dialog.resize(640, 480)
        layout = QVBoxLayout(dialog)
        note = QLabel("Review saved conversation notes. Pin useful notes to retain them, edit corrections, or forget an entry.")
        note.setWordWrap(True)
        layout.addWidget(note)
        listing = QListWidget()
        editor = QTextEdit()
        editor.setAcceptRichText(False)
        layout.addWidget(listing)
        layout.addWidget(editor)
        status = QLabel("")
        layout.addWidget(status)
        buttons = QHBoxLayout()
        save = QPushButton("Save edit")
        pin = QPushButton("Pin / unpin")
        forget = QPushButton("Forget entry")
        for button in (save, pin, forget):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        def refresh():
            listing.clear()
            for entry in webagent.load_agent_memory(agent):
                item = QListWidgetItem(("★ " if entry.get("pinned") else "") + str(entry.get("summary", ""))[:160])
                item.setData(Qt.ItemDataRole.UserRole, entry)
                listing.addItem(item)
            if listing.count():
                listing.setCurrentRow(0)
            else:
                editor.clear()
                status.setText("No saved conversation notes for this agent.")
            for button in (save, pin, forget):
                button.setEnabled(bool(listing.count()))
        def select():
            item = listing.currentItem()
            editor.setPlainText(str(item.data(Qt.ItemDataRole.UserRole).get("summary", "")) if item else "")
        listing.currentItemChanged.connect(lambda *_: select())
        def update(action):
            if self._response_active:
                status.setText("Wait for the current reply to finish before editing memory.")
                return
            item = listing.currentItem()
            if not item:
                return
            entry = item.data(Qt.ItemDataRole.UserRole)
            kwargs = {"summary": editor.toPlainText()} if action == "save" else {"pinned": not entry.get("pinned")} if action == "pin" else {"forget": True}
            try:
                webagent.update_agent_memory(agent, entry.get("date"), **kwargs)
            except (OSError, ValueError) as error:
                status.setText(str(error))
                return
            refresh()
            status.setText("Memory updated.")
        save.clicked.connect(lambda: update("save"))
        pin.clicked.connect(lambda: update("pin"))
        forget.clicked.connect(lambda: update("forget"))
        refresh()
        dialog.exec()

    def open_knowledge_settings(self):
        from core.knowledge_retrieval import embedding_model, save_embedding_model
        dialog = QDialog(self)
        dialog.setWindowTitle("Local knowledge retrieval")
        layout = QVBoxLayout(dialog)
        note = QLabel("Search uses ranked passages and local concept matching. For semantic search, choose a dedicated embedding model already installed in Ollama.")
        note.setWordWrap(True)
        layout.addWidget(note)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("Keyword search only", "")
        for model in core_models.list_installed():
            combo.addItem(model, model)
        current = embedding_model(core_config.project_root())
        if current:
            combo.setCurrentText(current)
        layout.addWidget(combo)
        status = QLabel("Embedding models run locally. If unavailable, search falls back to keywords.")
        status.setWordWrap(True)
        layout.addWidget(status)
        save = QPushButton("Save")
        def apply():
            model = "" if combo.currentText() == "Keyword search only" else combo.currentText().strip()
            try:
                save_embedding_model(core_config.project_root(), model)
            except OSError as error:
                status.setText(f"Could not save settings: {error}")
                return
            dialog.accept()
        save.clicked.connect(apply)
        layout.addWidget(save)
        dialog.exec()

    def open_cloud_models(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Connect cloud models")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Connect with an OpenAI or Anthropic API key and model ID. "
            "API usage has separate billing from ChatGPT / Claude subscriptions. "
            "Cloud chat sends conversation, persona, and relevant saved context to the provider. "
            "Keys entered here are kept only for this session."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        provider = QComboBox()
        for name, details in cloud_models.PROVIDERS.items():
            provider.addItem(details[0], name)
        layout.addWidget(provider)
        layout.addWidget(QLabel("API key"))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(key)
        layout.addWidget(QLabel("Model ID"))
        model = QLineEdit()
        model.setPlaceholderText("Enter the chat model ID from your provider")
        layout.addWidget(model)
        links = QLabel('<a href="https://platform.openai.com/api-keys">OpenAI API keys</a> · '
                       '<a href="https://console.anthropic.com/settings/keys">Claude API keys</a>')
        links.setOpenExternalLinks(True)
        layout.addWidget(links)
        status = QLabel("")
        status.setWordWrap(True)
        layout.addWidget(status)
        def load_provider():
            current_key, current_model = cloud_models.settings(provider.currentData())
            key.setText(current_key)
            model.setText(current_model)
            status.clear()
        provider.currentIndexChanged.connect(load_provider)
        load_provider()
        buttons = QHBoxLayout()
        connect = QPushButton("Use cloud model")
        cancel = QPushButton("Cancel")
        buttons.addWidget(connect)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        def save():
            try:
                selected = cloud_models.configure(provider.currentData(), key.text(), model.text())
            except ValueError as exc:
                status.setText(str(exc))
                return
            webagent.context.selected_model = selected
            self._populate_model_combo()
            dialog.accept()
        connect.clicked.connect(save)
        cancel.clicked.connect(dialog.reject)
        dialog.exec()

    def set_model_override(self, index):
        if index <= 0:
            webagent.context.selected_model = None
        else:
            webagent.context.selected_model = self.model_combo.currentData()
        self._prewarm_model_for_current_modes()

    def toggle_unfiltered_mode(self, checked):
        if checked:
            self.coding_check.setChecked(False)
        webagent.context.unfiltered_mode = checked
        self._prewarm_model_for_current_modes()

    def toggle_coding_mode(self, checked):
        if checked:
            self.unfiltered_check.setChecked(False)
        webagent.context.coding_mode = checked
        self._prewarm_model_for_current_modes()

    def _prewarm_model_for_current_modes(self):
        """Best-effort background load of whichever model the active mode
        toggles now resolve to, so switching modes doesn't pay a multi-
        second cold-load cost on the next real message - confirmed live
        that 'main' and 'unfiltered'/'coding' are different model files.
        Fire-and-forget: a failed or slow warmup just means no speedup this
        time, not a wrong answer, so there's nothing here worth surfacing."""
        if webagent.ollama is None:
            return
        model_name = webagent._selected_model()
        if cloud_models.is_cloud(model_name):
            return
        if self._daytime.paused or self._daytime.closed:
            return
        key = "warmup:" + model_name
        if self._warmup_key and self._warmup_key != key:
            self._daytime.pool.cancel(self._warmup_key)
        self._warmup_key = key
        options = core_models.thinking_options(
            model_name, webagent.context.reasoning_mode or webagent.context.deep_think_mode)
        def warmup(token):
            with core_models.request_control(token.check):
                return webagent.model_chat(model=model_name, messages=[], **options)
        self._daytime.pool.submit(key, warmup, priority=5)

    def _pause_background(self, paused):
        self._daytime.pause(paused)
        self.background_pause.setText("Resume background" if paused else "Pause background")
        self._tick_background()

    def _tick_background(self):
        foreground = self._response_active or self.voice_session.enabled
        self._daytime.tick(foreground=foreground)
        snapshot = self._daytime.snapshot()
        if snapshot['paused']:
            label = "Background: paused"
        elif foreground:
            label = "Background: chat/voice has priority"
        else:
            label = f"Background: {len(snapshot['active'])} active task(s)"
        self.background_label.setText(label)
        self.background_label.setToolTip(json.dumps(snapshot, indent=2))

    def open_diff_review(self):
        dialog = DiffReviewDialog(self)
        dialog.exec()

    def _insert_message_card(self, is_user, timestamp=None):
        """Qt frames provide real padding for both saved and streamed messages."""
        cursor = QTextCursor(self.chat_display.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.setCharFormat(QTextCharFormat())
        card = QTextFrameFormat()
        card.setPadding(18)
        card.setTopMargin(8)
        card.setBottomMargin(8)
        card.setLeftMargin(36 if is_user else 0)
        card.setRightMargin(0 if is_user else 20)
        card.setBackground(QColor(BG_BUBBLE_USER if is_user else BG_BUBBLE_ASSISTANT))
        card.setBorder(1)
        card.setBorderBrush(QColor('#49416c' if is_user else BORDER))
        card.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        frame = cursor.insertFrame(card)
        cursor = frame.firstCursorPosition()

        header = QTextCharFormat()
        header.setForeground(QColor(ACCENT_LIGHT if is_user else TEXT_SECONDARY))
        header.setFontPointSize(9)
        header.setFontWeight(QFont.Weight.DemiBold)
        cursor.insertText('You' if is_user else 'Assistant', header)
        header.setForeground(QColor(TEXT_MUTED))
        header.setFontWeight(QFont.Weight.Normal)
        cursor.insertText(f"   ·   {(timestamp or datetime.now()).strftime('%H:%M')}", header)

        body = QTextBlockFormat()
        body.setTopMargin(10)
        body.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(TEXT_PRIMARY))
        text_format.setFontPointSize(11)
        cursor.insertBlock(body, text_format)
        return cursor

    def display_message(self, text, is_user=True):
        with self._chat_scroll_guard():
            cursor = self._insert_message_card(is_user)
            cursor.insertText(text)


    def clear_chat(self):
        """Clear chat history"""
        if self._response_active:
            return
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Are you sure you want to clear the chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            self._reset_reply_actions()
            webagent.new_conversation(save_current=False)
            self.current_conversation_file = None
            self.conversation_saved_length = len(webagent.context.assistant_convo)
            self._refresh_conversation_list()

    def _has_unsaved_messages(self):
        """True if the active conversation has content that hasn't been written to disk yet -
        either a brand-new conversation, or a loaded one with messages added since."""
        convo_length = len(webagent.context.assistant_convo)
        if convo_length <= 1:
            return False
        return convo_length != self.conversation_saved_length

    def _refresh_conversation_list(self):
        """Repopulate the sidebar from disk and re-select the active conversation, if any."""
        self.conversation_list.clear()
        for fname in webagent.list_conversations():
            label = fname[:-5] if fname.endswith(".json") else fname
            # Strip the trailing _YYYYMMDD_HHMMSS save-time stamp and turn the
            # sanitized underscores back into spaces - the stamp still lives
            # in the real filename (sorting/uniqueness), just not the label.
            label = re.sub(r"_\d{8}_\d{6}$", "", label).replace("_", " ") or label
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, fname)
            self.conversation_list.addItem(item)
            if fname == self.current_conversation_file:
                self.conversation_list.setCurrentItem(item)

    def _repaint_chat_from_history(self):
        self._source_inspections.clear()
        self.chat_display.clear()
        self._reset_reply_actions()
        history = webagent.context.assistant_convo
        last_user = max((i for i, msg in enumerate(history) if msg.get("role") == "user"), default=-1)
        for index, msg in enumerate(history):
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            if index == last_user:
                self._last_turn_context = copy.deepcopy(history[:index])
                self._last_turn_html = self.chat_display.toHtml()
                self._last_prompt = msg.get("content", "")
                self._last_retry_allowed = webagent.context.current_agent != "scheduler"
            self.display_message(msg.get("content", ""), is_user=(role == "user"))
            if role == "assistant":
                self._last_reply = msg.get("content", "")
                if "sources" in msg:
                    self._render_sources(msg["sources"])
        self._update_reply_actions()

    def new_conversation_action(self):
        """Start a fresh conversation, offering to save the current one first if it has
        unsaved content."""
        if self._response_active:
            return
        if self._has_unsaved_messages():
            reply = QMessageBox.question(
                self,
                "Unsaved Conversation",
                "Save the current conversation before starting a new one?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            webagent.new_conversation(save_current=(reply == QMessageBox.StandardButton.Save))
        else:
            webagent.new_conversation(save_current=False)

        self.current_conversation_file = None
        self.conversation_saved_length = len(webagent.context.assistant_convo)
        self.chat_display.clear()
        self._reset_reply_actions()
        self._refresh_conversation_list()

    def load_selected_conversation(self, item):
        fname = item.data(Qt.ItemDataRole.UserRole)
        if self._response_active:
            return
        if fname == self.current_conversation_file:
            return

        if self._has_unsaved_messages():
            reply = QMessageBox.question(
                self,
                "Unsaved Conversation",
                "Save the current conversation before switching?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self._refresh_conversation_list()
                return
            if reply == QMessageBox.StandardButton.Save:
                webagent.save_conversation()

        path = webagent.load_conversation(fname)
        if not path:
            QMessageBox.critical(self, "Load Failed", f"Could not load conversation:\n{fname}")
            self._refresh_conversation_list()
            return

        self.current_conversation_file = fname
        self.conversation_saved_length = len(webagent.context.assistant_convo)
        self._repaint_chat_from_history()
        self._refresh_conversation_list()

    def toggle_voice_mode(self, checked):
        """Voice mode owns microphone capture and streamed speech playback."""
        webagent.context.voice_mode = checked
        if checked:
            webagent.stop_tts()
            self.voice_panel.reset()
            self.voice_panel.show()
            if self._response_active:
                self._voice_turn = True
                self.voice_session.reply_pending = True
                self.voice_session.buffer.text = ""
            self.voice_session.start()
        else:
            self.voice_session.stop()
            if self._voice_turn and self._response_active:
                self._interrupt_voice_reply()

    def _on_voice_enabled(self, enabled):
        from core.background import foreground_activity
        if enabled and self._voice_priority is None:
            self._voice_priority = foreground_activity()
            self._voice_priority.__enter__()
        elif not enabled and self._voice_priority is not None:
            self._voice_priority.__exit__(None, None, None)
            self._voice_priority = None
        webagent.context.voice_mode = enabled
        self.voice_check.blockSignals(True)
        self.voice_check.setChecked(enabled)
        self.voice_check.blockSignals(False)
        self.voice_panel.setVisible(enabled)
        if not enabled and self._voice_turn and self._response_active:
            self._interrupt_voice_reply()

    def _on_voice_phase(self, phase):
        self.voice_panel.set_phase(phase)

    def _on_voice_level(self, level):
        self.voice_panel.set_level(level)

    def _on_voice_input(self, text):
        if self.voice_session.enabled and not self._response_active:
            self.send_message(user_input=text)

    def _on_voice_error(self, message):
        if self._voice_priority is not None:
            self._voice_priority.__exit__(None, None, None)
            self._voice_priority = None
        webagent.context.voice_mode = False
        self.voice_check.blockSignals(True)
        self.voice_check.setChecked(False)
        self.voice_check.blockSignals(False)
        self.voice_panel.show()
        self.voice_panel.set_phase(message)
        self.voice_panel.mute_button.setEnabled(False)
        self.voice_panel.interrupt_button.setEnabled(False)
        self.voice_panel.end_button.setEnabled(True)

    def end_voice_chat(self):
        self.voice_check.setChecked(False)
        if not self.voice_session.enabled:
            self.voice_panel.hide()

    def interrupt_voice_chat(self):
        self.voice_panel.mute_button.setChecked(False)
        self.voice_session.interrupt()

    def _interrupt_voice_reply(self):
        if self._response_active and self._voice_turn and self.response_worker is not None:
            self.response_worker.cancel()
            self.send_button.setEnabled(False)
            self._set_chat_activity("Stopping")

    def _voice_idle(self):
        if self._close_requested and not self._response_active:
            QTimer.singleShot(0, self.close)

    def open_voice_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Voice settings")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Speech recognition runs locally. No microphone audio is uploaded."))
        layout.addWidget(QLabel("Speech model folder"))
        model_row = QHBoxLayout()
        model = QLineEdit(self.voice_session.model_path)
        model_row.addWidget(model, 1)
        browse = QPushButton("Browse…")
        def choose_model():
            folder = QFileDialog.getExistingDirectory(dialog, "Choose a Vosk model folder", model.text())
            if folder:
                model.setText(folder)
        browse.clicked.connect(choose_model)
        model_row.addWidget(browse)
        layout.addLayout(model_row)
        layout.addWidget(QLabel("Reply voice"))
        voice = QComboBox()
        voice.addItem("System default (local)", "")
        for label, name in [("Aria — US English", "en-US-AriaNeural"),
                            ("Jenny — US English", "en-US-JennyNeural"),
                            ("Guy — US English", "en-US-GuyNeural"),
                            ("Sonia — UK English", "en-GB-SoniaNeural")]:
            voice.addItem(f"{label} (online neural)", f"neural:{name}")
        if webagent.platform.system() == "Darwin":
            try:
                voices = webagent.subprocess.check_output(["say", "-v", "?"], text=True, timeout=3)
                for line in voices.splitlines():
                    match = re.match(r"(.+?)\s+([a-z]{2}_[A-Z]{2})\s+", line)
                    if match:
                        name, language = match.groups()
                        voice.addItem(f"{name} ({language})", name)
            except (OSError, webagent.subprocess.SubprocessError):
                pass
        index = voice.findData(self.voice_session.output_voice)
        voice.setCurrentIndex(max(0, index))
        layout.addWidget(voice)
        voice_note = QLabel("Neural voices send reply text to Microsoft for speech and need internet. Local voices stay on this computer.")
        voice_note.setWordWrap(True)
        layout.addWidget(voice_note)
        layout.addWidget(QLabel("Speaking speed (words per minute)"))
        rate = QSpinBox()
        rate.setRange(80, 300)
        rate.setValue(self.voice_session.rate)
        layout.addWidget(rate)
        status = QLabel("")
        status.setWordWrap(True)
        layout.addWidget(status)
        preview = QPushButton("Preview voice")
        layout.addWidget(preview)
        def preview_clicked():
            if self.voice_preview.worker is not None:
                self.voice_preview.stop()
                preview.setEnabled(False)
                preview.setText("Stopping…")
            else:
                status.clear()
                webagent.stop_tts()
                self.voice_preview.start(voice.currentData(), rate.value())
        def preview_active(active):
            preview.setEnabled(True)
            preview.setText("Stop preview" if active else "Preview voice")
        preview.clicked.connect(preview_clicked)
        self.voice_preview.active_changed.connect(preview_active)
        self.voice_preview.error.connect(status.setText)
        dialog.finished.connect(lambda _: self.voice_preview.stop())
        buttons = QHBoxLayout()
        save, cancel = QPushButton("Save"), QPushButton("Cancel")
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        def apply():
            try:
                self.voice_session.save_settings(model.text().strip(), voice.currentData(), rate.value())
            except (ValueError, OSError) as exc:
                status.setText(str(exc))
                return
            if self.voice_session.enabled:
                self.voice_session.energy = None
            dialog.accept()
        save.clicked.connect(apply)
        cancel.clicked.connect(dialog.reject)
        was_muted = self.voice_session.muted
        if self.voice_session.enabled:
            self.voice_session.mute(True)
        dialog.exec()
        self.voice_preview.active_changed.disconnect(preview_active)
        self.voice_preview.error.disconnect(status.setText)
        if self.voice_session.enabled:
            # Keep recognition muted until the sample has actually stopped.
            if self.voice_preview.worker is not None:
                def restore_mic(active):
                    if not active:
                        self.voice_preview.active_changed.disconnect(restore_mic)
                        if self.voice_session.enabled:
                            self.voice_session.mute(was_muted)
                self.voice_preview.active_changed.connect(restore_mic)
            else:
                self.voice_session.mute(was_muted)

    def toggle_tts_mode(self, checked):
        """Text-mode read-aloud is separate from the hands-free voice session."""
        webagent.context.tts_mode = checked

    def toggle_web_search(self, checked):
        """Toggle web search mode"""
        webagent.context.web_search_mode = checked

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
                border-radius: 16px;
            }}
            QFrame#convoPanel {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 16px;
            }}
            QFrame#composer {{
                background-color: {BG_INPUT};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 16px;
            }}
            QScrollArea#interestDashboard {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 16px;
            }}
            QWidget#dashboardContent {{
                background-color: {BG_PANEL};
            }}
            QLabel#dashboardTitle {{
                color: {TEXT_PRIMARY};
                font-size: 23px;
                font-weight: 600;
            }}
            QLabel#dashboardEmpty {{
                color: {TEXT_SECONDARY};
                font-size: 14px;
                padding: 24px 0;
            }}
            QFrame#interestCard {{
                background-color: {BG_INPUT};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QLabel#interestTag {{
                color: {ACCENT_LIGHT};
                font-size: 10px;
                font-weight: 600;
            }}
            QLabel#interestName {{
                color: {TEXT_PRIMARY};
                font-size: 16px;
                font-weight: 600;
            }}
            QLabel#interestUpdate {{
                color: {TEXT_SECONDARY};
                font-size: 13px;
            }}
            QFrame#toggleSeparator {{
                background-color: {BORDER};
                max-width: 1px;
                margin: 2px 4px;
            }}
            QTextEdit {{
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                font-size: 14px;
                border-radius: 12px;
            }}
            QTextEdit#chatDisplay {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                padding: 8px;
                color: {TEXT_PRIMARY};
                border-radius: 16px;
            }}
            QTextEdit#inputText {{
                background-color: transparent;
                border: none;
                padding: 4px;
                color: {TEXT_PRIMARY};
            }}
            QTextEdit#inputText:focus {{
                border: none;
                background-color: transparent;
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
                border-radius: 10px;
                padding: 7px 12px;
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
            QPushButton#subscriptionButton {{
                background-color: {BG_ELEVATED};
                color: {TEXT_MUTED};
                border: 1px solid {BORDER};
            }}
            QPushButton#subscriptionButton:hover {{
                border: 1px solid {BORDER_LIGHT};
                color: {TEXT_SECONDARY};
            }}
            QPushButton#subscriptionButton[subState="on"] {{
                background-color: {SUCCESS_GREEN};
                color: white;
                border: 1px solid {SUCCESS_GREEN};
                font-weight: 600;
            }}
            QPushButton#subscriptionButton[subState="on"]:hover {{
                background-color: {SUCCESS_GREEN_HOVER};
                border: 1px solid {SUCCESS_GREEN_HOVER};
            }}
            QPushButton#subscriptionButton:disabled {{
                color: {TEXT_MUTED};
                border: 1px solid {BORDER};
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
            QListWidget#conversationList {{
                background-color: transparent;
                border: none;
            }}
            QListWidget#conversationList::item {{
                padding: 12px 10px;
                margin-bottom: 4px;
            }}
            QListWidget#conversationList::item:selected {{
                background-color: {BG_ELEVATED};
                color: {ACCENT_LIGHT};
                border: 1px solid {BORDER_LIGHT};
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
