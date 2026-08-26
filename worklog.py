"""Work Tracker - the pane living right after Idle Island in the nav: a
Todo/Calendar/Projects/Reports board for logging billable tasks against
project codes, sliding them through a status pipeline (New -> Working ->
Hold/Review -> Done -> Paid), and rolling daily/weekly hour totals up for
payroll reporting.

Split the same way as games/idle_island.py: plain-Python storage/reporting
logic up top (no Qt imports, unit-testable on its own) with WorklogWidget's
Qt layer below it as a thin UI over that state. All data lives in one JSON
file (projects/tasks/events) under core_config.path("worklog") - same
lazy-mkdir-on-write-only discipline as core/activity_log.py and
core/subscriptions.py: a read must never create the directory.
"""
import html
import json
import os
import uuid
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (
    QCalendarWidget, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTextEdit, QTimeEdit, QVBoxLayout, QWidget,
)

from core import config as core_config

STATUSES = ("New", "Working", "Hold", "Review", "Done", "Paid")
STATUS_COLORS = {
    "New": "#4c8bf5", "Working": "#f5a524", "Hold": "#e5484d",
    "Review": "#a855f7", "Done": "#3ecf8e", "Paid": "#eab308",
}
COLUMN_EXPANDED_WIDTH = 190
COLUMN_COLLAPSED_WIDTH = 60

BG_ELEVATED = "#262631"
BORDER = "#34343f"
TEXT_PRIMARY = "#eaeaf2"
TEXT_MUTED = "#797986"
TASK_ACTIVITY_BG = "#3a3160"

# phase -> (display label, accent color) - island-themed to match Idle Island
# right next door in the nav, instead of the standard-issue tomato.
FOCUS_PHASE_INFO = {
    "work": ("🌊 Diving In", "#2dd4bf"),
    "break": ("🏖️ Beach Break", "#fbbf24"),
}

# Retro dive-computer look for the Focus Timer tab: chunky pixel borders,
# a monospace "8-bit" font, and an inset LCD-style readout on a gradient
# ocean backdrop.
FOCUS_FONT = '"Courier New", "Menlo", "Consolas", monospace'
FOCUS_PANEL_BG = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #082436, stop:0.55 #0f4c68, stop:1 #146a8c)"
FOCUS_SCREEN_BG = "#04141f"
FOCUS_INK = "#8be9ff"
FOCUS_PIXEL_BUTTON_QSS = f"""
    QPushButton {{
        background-color: #0f4c68;
        color: {FOCUS_INK};
        border: 3px solid;
        border-top-color: #2dd4bf;
        border-left-color: #2dd4bf;
        border-right-color: {FOCUS_SCREEN_BG};
        border-bottom-color: {FOCUS_SCREEN_BG};
        border-radius: 0px;
        font-family: {FOCUS_FONT};
        font-weight: bold;
        padding: 8px 10px;
    }}
    QPushButton:hover {{ background-color: #146a8c; }}
    QPushButton:pressed {{
        border-top-color: {FOCUS_SCREEN_BG};
        border-left-color: {FOCUS_SCREEN_BG};
        border-right-color: #2dd4bf;
        border-bottom-color: #2dd4bf;
    }}
    QPushButton:disabled {{ color: #3d5a68; background-color: #0a2a43; }}
"""
FOCUS_PIXEL_INPUT_QSS = f"""
    background-color: {FOCUS_SCREEN_BG};
    color: {FOCUS_INK};
    border: 2px solid #2dd4bf;
    border-radius: 0px;
    font-family: {FOCUS_FONT};
    padding: 4px 6px;
"""


# ----------------------------------------------------------------------
# Storage - one JSON file, three lists
# ----------------------------------------------------------------------
def _data_path():
    return os.path.join(core_config.path("worklog"), "worklog.json")


def _new_id():
    return uuid.uuid4().hex[:8]


def load_data():
    path = _data_path()
    if not os.path.isfile(path):
        return {"projects": [], "tasks": [], "events": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"projects": [], "tasks": [], "events": []}
    if not isinstance(data, dict):
        return {"projects": [], "tasks": [], "events": []}
    data.setdefault("projects", [])
    data.setdefault("tasks", [])
    data.setdefault("events", [])
    for task in data["tasks"]:
        task.setdefault("notes", [])
        task.setdefault("daily_hours", {})
    return data


def save_data(data):
    path = _data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ----------------------------------------------------------------------
# Projects
# ----------------------------------------------------------------------
def list_projects():
    return load_data()["projects"]


def get_project(code):
    for p in list_projects():
        if p["code"] == code:
            return p
    return None


def add_project(name, code, description=""):
    name = (name or "").strip()
    code = (code or "").strip()
    if not name:
        raise ValueError("A project needs a name.")
    if not code:
        raise ValueError("A project needs a code.")
    data = load_data()
    if any(p["code"].casefold() == code.casefold() for p in data["projects"]):
        raise ValueError(f'Project code "{code}" is already in use.')
    record = {
        "id": _new_id(), "code": code, "name": name,
        "description": (description or "").strip(),
        "created_at": datetime.now().isoformat(),
    }
    data["projects"].append(record)
    save_data(data)
    return record


def duplicate_project(code):
    data = load_data()
    source = next((p for p in data["projects"] if p["code"] == code), None)
    if source is None:
        raise ValueError(f'No project with code "{code}".')
    existing_codes = {p["code"] for p in data["projects"]}
    new_code = f"{source['code']}-COPY"
    n = 2
    while new_code in existing_codes:
        new_code = f"{source['code']}-COPY{n}"
        n += 1
    record = {
        "id": _new_id(), "code": new_code, "name": f"{source['name']} (Copy)",
        "description": source["description"], "created_at": datetime.now().isoformat(),
    }
    data["projects"].append(record)
    save_data(data)
    return record


def delete_project(code):
    data = load_data()
    remaining = [p for p in data["projects"] if p["code"] != code]
    if len(remaining) == len(data["projects"]):
        return False
    data["projects"] = remaining
    save_data(data)
    return True


def tasks_for_project(code):
    return [t for t in load_data()["tasks"] if t["project_code"] == code]


# ----------------------------------------------------------------------
# Tasks
# ----------------------------------------------------------------------
def list_tasks():
    return load_data()["tasks"]


def _find_task(data, task_id):
    for t in data["tasks"]:
        if t["id"] == task_id:
            return t
    return None


def add_task(title, project_code, hours=0.0):
    title = (title or "").strip()
    if not title:
        raise ValueError("A task needs a title.")
    if get_project(project_code) is None:
        raise ValueError(f'No project with code "{project_code}".')
    now = datetime.now().isoformat()
    record = {
        "id": _new_id(), "title": title, "project_code": project_code,
        "status": STATUSES[0], "hours": float(hours or 0.0),
        "status_history": [{"status": STATUSES[0], "at": now}],
        "created_at": now, "notes": [], "daily_hours": {},
    }
    data = load_data()
    data["tasks"].append(record)
    save_data(data)
    return record


def set_task_status(task_id, new_status):
    if new_status not in STATUSES:
        raise ValueError(f'Unknown status "{new_status}".')
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    task["status"] = new_status
    task["status_history"].append({"status": new_status, "at": datetime.now().isoformat()})
    save_data(data)
    return task


def move_task_status(task_id, direction):
    """direction is +1 (slide right/forward) or -1 (slide left/back) - a
    no-op at either end of STATUSES rather than wrapping or erroring, so the
    UI can just disable the outermost arrow buttons instead of guarding
    here."""
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    index = STATUSES.index(task["status"])
    new_index = max(0, min(len(STATUSES) - 1, index + direction))
    if new_index == index:
        return task
    return set_task_status(task_id, STATUSES[new_index])


def set_task_hours(task_id, hours):
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    task["hours"] = float(hours or 0.0)
    save_data(data)
    return task


def log_task_hours(task_id, iso_date, hours):
    """Sets (overwrites) the hours logged for a task on one specific day.
    Unlike notes, this is edited in place rather than appended - so
    correcting an over-estimate, or zeroing out a day because the task
    finished early, just means logging that day again with the new
    number. Logging 0 removes the day's entry entirely rather than
    leaving a 0h row. daily_summary() sums these per-day entries directly
    for any task that has them, instead of lumping all its hours onto
    the day it was marked Done."""
    if not iso_date:
        raise ValueError("A day needs a date.")
    hours = float(hours or 0.0)
    if hours < 0:
        raise ValueError("Hours can't be negative.")
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    daily = task.setdefault("daily_hours", {})
    if hours == 0:
        daily.pop(iso_date, None)
    else:
        daily[iso_date] = hours
    save_data(data)
    return task


def log_task_hours_increment(task_id, iso_date, hours_delta):
    """Adds hours_delta on top of whatever's already logged for a task on
    iso_date, rather than replacing it - what a completed Focus Timer work
    session needs, since several sessions logged against the same task on
    the same day should accumulate instead of each one clobbering the
    last the way log_task_hours does."""
    if not iso_date:
        raise ValueError("A day needs a date.")
    if hours_delta <= 0:
        raise ValueError("Hours must be positive.")
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    daily = task.setdefault("daily_hours", {})
    daily[iso_date] = daily.get(iso_date, 0.0) + hours_delta
    save_data(data)
    return task


def total_task_hours(task):
    """The one number a task's hours display shows - sum of its daily
    log if it has one, otherwise its legacy lump-sum total. Same rule
    daily_summary() uses to decide which number is authoritative, so the
    UI never shows a total that disagrees with what gets reported."""
    daily = task.get("daily_hours") or {}
    if daily:
        return sum(daily.values())
    return task.get("hours", 0.0)


def set_task_project_code(task_id, project_code):
    """Corrects a task's job code after the fact - e.g. it was logged
    under the wrong project. daily_summary()/weekly_summary() group by
    task["project_code"] read live off the task each time they're called
    rather than off a snapshot taken when the task was completed, so this
    reassigns that task's hours to the new project in every past and
    future report automatically, with no separate reporting update."""
    if get_project(project_code) is None:
        raise ValueError(f'No project with code "{project_code}".')
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    task["project_code"] = project_code
    save_data(data)
    return task


def set_task_title(task_id, title):
    title = (title or "").strip()
    if not title:
        raise ValueError("A task needs a title.")
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    task["title"] = title
    save_data(data)
    return task


def add_task_note(task_id, text):
    """Append-only: notes are never edited or removed once saved, so a
    task's note history stays a permanent, chronological record even
    across status changes, hour edits, or project renames."""
    text = (text or "").strip()
    if not text:
        raise ValueError("A note needs some text.")
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    task.setdefault("notes", []).append({"id": _new_id(), "text": text, "at": datetime.now().isoformat()})
    save_data(data)
    return task


def list_task_notes(task_id):
    data = load_data()
    task = _find_task(data, task_id)
    if task is None:
        raise ValueError(f'No task with id "{task_id}".')
    return task["notes"]


def delete_task(task_id):
    data = load_data()
    remaining = [t for t in data["tasks"] if t["id"] != task_id]
    if len(remaining) == len(data["tasks"]):
        return False
    data["tasks"] = remaining
    save_data(data)
    return True


def task_activity_dates():
    """ISO date -> set of task ids that had a status_history entry that
    day (creation counts, since add_task seeds one). A task that lives
    through several days of status changes shows up on each of them, so
    the calendar tab can trace a task's whole lifecycle, not just its
    creation date."""
    dates = {}
    for task in list_tasks():
        for entry in task["status_history"]:
            iso_date = entry["at"][:10]
            dates.setdefault(iso_date, set()).add(task["id"])
    return dates


def tasks_active_on_date(iso_date):
    """Tasks with a status_history entry on iso_date, each paired with
    which status(es) it moved to that day."""
    result = []
    for task in list_tasks():
        statuses_that_day = [e["status"] for e in task["status_history"] if e["at"][:10] == iso_date]
        if statuses_that_day:
            result.append({"task": task, "statuses": statuses_that_day})
    return result


# ----------------------------------------------------------------------
# Calendar events
# ----------------------------------------------------------------------
def list_events():
    return load_data()["events"]


def events_on_date(iso_date):
    return [e for e in list_events() if e["date"] == iso_date]


def add_event(title, iso_date, time_str="", description=""):
    title = (title or "").strip()
    if not title:
        raise ValueError("An event needs a title.")
    if not iso_date:
        raise ValueError("An event needs a date.")
    record = {
        "id": _new_id(), "title": title, "date": iso_date,
        "time": (time_str or "").strip(), "description": (description or "").strip(),
        "created_at": datetime.now().isoformat(),
    }
    data = load_data()
    data["events"].append(record)
    save_data(data)
    return record


def delete_event(event_id):
    data = load_data()
    remaining = [e for e in data["events"] if e["id"] != event_id]
    if len(remaining) == len(data["events"]):
        return False
    data["events"] = remaining
    save_data(data)
    return True


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------
def _last_completed_date(task):
    """The date a task counts toward for daily/weekly hour reports - the
    most recent time it entered "Done", regardless of whether it has since
    moved on to "Paid". Paid is a payroll bookkeeping status, not a second
    unit of work, so it must never introduce a second reporting date."""
    completed_at = None
    for entry in task["status_history"]:
        if entry["status"] == "Done":
            completed_at = entry["at"]
    if completed_at is None:
        return None
    return datetime.fromisoformat(completed_at).date()


def daily_summary(iso_date):
    """A task with any daily_hours entries reports its hours for exactly
    the days they were logged on. A task with none falls back to the old
    behavior - its full total counted on the day it was marked Done - so
    tasks nobody has broken into a daily log still show up in reports."""
    target = date.fromisoformat(iso_date)
    tasks = []
    by_project = {}
    for t in list_tasks():
        daily = t.get("daily_hours") or {}
        if daily:
            hours = daily.get(iso_date, 0.0)
            if hours <= 0:
                continue
        elif _last_completed_date(t) == target:
            hours = t["hours"]
        else:
            continue
        tasks.append(t)
        by_project[t["project_code"]] = by_project.get(t["project_code"], 0.0) + hours
    return {
        "date": iso_date, "tasks": tasks, "by_project": by_project,
        "total_hours": sum(by_project.values()),
    }


def week_start_for(iso_date):
    d = date.fromisoformat(iso_date)
    return (d - timedelta(days=d.weekday())).isoformat()


def weekly_summary(week_start_iso):
    start = date.fromisoformat(week_start_iso)
    days = [daily_summary((start + timedelta(days=i)).isoformat()) for i in range(7)]
    by_project = {}
    for day in days:
        for code, hours in day["by_project"].items():
            by_project[code] = by_project.get(code, 0.0) + hours
    return {
        "week_start": week_start_iso, "days": days, "by_project": by_project,
        "total_hours": sum(by_project.values()),
    }


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class WorklogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("🗂️ Work Tracker")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.todo_tab = self._build_todo_tab()
        self.focus_tab = self._build_focus_tab()
        self.calendar_tab = self._build_calendar_tab()
        self.projects_tab = self._build_projects_tab()
        self.reports_tab = self._build_reports_tab()
        self.tabs.addTab(self.todo_tab, "Todo")
        self.tabs.addTab(self.focus_tab, "🌊 Focus")
        self.tabs.addTab(self.calendar_tab, "Calendar")
        self.tabs.addTab(self.projects_tab, "Projects")
        self.tabs.addTab(self.reports_tab, "Reports")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._rebuild_todo()
        self._refresh_focus_tasks()
        self._refresh_calendar_events()
        self._rebuild_projects()
        self._refresh_reports()

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.todo_tab:
            self._rebuild_todo()
        elif widget is self.focus_tab:
            self._refresh_focus_tasks()
        elif widget is self.calendar_tab:
            self._refresh_calendar_events()
        elif widget is self.projects_tab:
            self._rebuild_projects()
        elif widget is self.reports_tab:
            self._refresh_reports()

    # ------------------------------------------------------------------
    # Todo (kanban board)
    # ------------------------------------------------------------------
    def _build_todo_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        top_row = QHBoxLayout()
        new_task_button = QPushButton("+ New Task")
        new_task_button.clicked.connect(self._new_task_clicked)
        top_row.addWidget(new_task_button)
        top_row.addStretch()
        outer.addLayout(top_row)

        board_scroll = QScrollArea()
        board_scroll.setWidgetResizable(True)
        board_content = QWidget()
        board = QHBoxLayout(board_content)

        self.status_columns = {}
        for status in STATUSES:
            column_widget = QFrame()
            column_widget.setObjectName(f"column_{status}")
            column_widget.setMinimumWidth(COLUMN_EXPANDED_WIDTH)
            # ID-scoped selector, not a bare "QFrame" one - QLabel and
            # QScrollArea both subclass QFrame, so a bare type selector here
            # would cascade this border onto every label and card nested
            # inside the column instead of just its own outline.
            column_widget.setStyleSheet(
                f"QFrame#column_{status} {{ border: 2px solid {STATUS_COLORS[status]}; border-radius: 8px; }}"
            )
            column = QVBoxLayout(column_widget)
            column.setContentsMargins(6, 6, 6, 6)

            toggle_row = QHBoxLayout()
            toggle_button = QPushButton("▼")
            toggle_button.setFixedSize(20, 18)
            toggle_button.setFlat(True)
            toggle_row.addWidget(toggle_button)
            toggle_row.addStretch()
            column.addLayout(toggle_row)

            header = QLabel(status)
            header.setWordWrap(True)
            header.setStyleSheet(f"font-weight: bold; color: {STATUS_COLORS[status]}; font-size: 13px;")
            column.addWidget(header)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.addStretch()
            scroll.setWidget(content)
            column.addWidget(scroll, 1)

            board.addWidget(column_widget)
            self.status_columns[status] = {
                "header": header, "layout": content_layout,
                "widget": column_widget, "scroll": scroll, "toggle": toggle_button,
            }
            toggle_button.clicked.connect(lambda checked=False, status=status: self._toggle_column_collapsed(status))

        board_scroll.setWidget(board_content)
        outer.addWidget(board_scroll, 1)
        return page

    def _rebuild_todo(self):
        for status in STATUSES:
            self._clear_layout(self.status_columns[status]["layout"])
        counts = {status: 0 for status in STATUSES}
        for task in list_tasks():
            counts[task["status"]] += 1
            self.status_columns[task["status"]]["layout"].addWidget(self._build_task_card(task))
        for status in STATUSES:
            self.status_columns[status]["layout"].addStretch()
            self.status_columns[status]["header"].setText(f"{status} ({counts[status]})")

    def _toggle_column_collapsed(self, status):
        col = self.status_columns[status]
        expanded = col["scroll"].isVisible()
        col["scroll"].setVisible(not expanded)
        if expanded:
            col["toggle"].setText("▶")
            col["widget"].setMinimumWidth(0)
            col["widget"].setMaximumWidth(COLUMN_COLLAPSED_WIDTH)
        else:
            col["toggle"].setText("▼")
            col["widget"].setMinimumWidth(COLUMN_EXPANDED_WIDTH)
            col["widget"].setMaximumWidth(16_777_215)  # QWIDGETSIZE_MAX - clears the collapsed cap

    def _build_task_card(self, task):
        card = QFrame()
        card.setObjectName(f"card_{task['id']}")
        # ID-scoped selector - see the column outline comment above; a bare
        # "QFrame" selector here would also border every QLabel this card
        # contains (title, project, hours, timestamp).
        card.setStyleSheet(
            f"QFrame#card_{task['id']} {{ background-color: {BG_ELEVATED}; "
            f"border: 2px solid {STATUS_COLORS[task['status']]}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        title_label = QLabel(task["title"])
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        layout.addWidget(title_label)

        project = get_project(task["project_code"])
        project_text = f'{task["project_code"]} — {project["name"]}' if project else f'{task["project_code"]} (deleted)'
        project_label = QLabel(project_text)
        project_label.setWordWrap(True)
        project_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(project_label)

        today_hours = task.get("daily_hours", {}).get(date.today().isoformat(), 0.0)

        hours_row = QHBoxLayout()
        hours_row.addWidget(QLabel("Today:"))
        today_value_label = QLabel(f"{today_hours:.2f}")
        today_value_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        hours_row.addWidget(today_value_label)
        hours_row.addSpacing(12)
        hours_row.addWidget(QLabel("Total:"))
        total_value_label = QLabel(f"{total_task_hours(task):.2f}")
        total_value_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        hours_row.addWidget(total_value_label)
        hours_row.addStretch()
        log_hours_button = QPushButton("📅")
        log_hours_button.setToolTip("Log or edit hours for a specific day")
        log_hours_button.setFixedWidth(24)
        log_hours_button.clicked.connect(
            lambda checked=False, task_id=task["id"], title=task["title"]: self._log_hours_clicked(task_id, title)
        )
        hours_row.addWidget(log_hours_button)
        layout.addLayout(hours_row)

        last_entry = task["status_history"][-1]
        stamp = datetime.fromisoformat(last_entry["at"]).strftime("%b %d, %I:%M %p")
        stamp_label = QLabel(f"Since {stamp}")
        stamp_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        layout.addWidget(stamp_label)

        notes_row = QHBoxLayout()
        notes_input = QLineEdit()
        notes_input.setPlaceholderText("Add a note…")
        notes_row.addWidget(notes_input)
        notes_button = QPushButton("+")
        notes_button.setFixedWidth(24)
        notes_row.addWidget(notes_button)
        layout.addLayout(notes_row)

        def _add_note(checked=False, task_id=task["id"], field=notes_input):
            text = field.text().strip()
            if not text:
                return
            try:
                add_task_note(task_id, text)
            except ValueError as exc:
                QMessageBox.warning(self, "Can't Add Note", str(exc))
                return
            field.clear()

        notes_button.clicked.connect(_add_note)
        notes_input.returnPressed.connect(_add_note)

        button_row = QHBoxLayout()
        back_button = QPushButton("◀")
        back_button.setEnabled(task["status"] != STATUSES[0])
        back_button.clicked.connect(lambda checked=False, task_id=task["id"]: self._slide_task(task_id, -1))
        button_row.addWidget(back_button)
        forward_button = QPushButton("▶")
        forward_button.setEnabled(task["status"] != STATUSES[-1])
        forward_button.clicked.connect(lambda checked=False, task_id=task["id"]: self._slide_task(task_id, 1))
        button_row.addWidget(forward_button)
        button_row.addStretch()
        view_notes_button = QPushButton("📝")
        view_notes_button.setToolTip("View notes")
        view_notes_button.clicked.connect(
            lambda checked=False, task_id=task["id"], title=task["title"]: self._view_notes_clicked(task_id, title)
        )
        button_row.addWidget(view_notes_button)
        edit_button = QPushButton("✎")
        edit_button.setToolTip("Edit title / job code")
        edit_button.clicked.connect(lambda checked=False, task_id=task["id"]: self._edit_task_clicked(task_id))
        button_row.addWidget(edit_button)
        delete_button = QPushButton("🗑")
        delete_button.clicked.connect(
            lambda checked=False, task_id=task["id"], title=task["title"]: self._delete_task_clicked(task_id, title)
        )
        button_row.addWidget(delete_button)
        layout.addLayout(button_row)
        return card

    def _view_notes_clicked(self, task_id, title):
        notes = list_task_notes(task_id)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Notes — {title}")
        dialog.resize(420, 380)
        layout = QVBoxLayout(dialog)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        if not notes:
            content_layout.addWidget(QLabel("No notes yet."))
        for note in notes:
            stamp = datetime.fromisoformat(note["at"]).strftime("%b %d, %Y %I:%M %p")
            entry_label = QLabel(f'<b>{html.escape(stamp)}</b><br>{html.escape(note["text"])}')
            entry_label.setWordWrap(True)
            entry_label.setStyleSheet(
                f"background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px;"
            )
            content_layout.addWidget(entry_label)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def _log_hours_clicked(self, task_id, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Log Hours — {title}")
        dialog.resize(360, 340)
        layout = QVBoxLayout(dialog)

        entries_label = QLabel()
        entries_label.setWordWrap(True)
        entries_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(entries_label)

        def _refresh_entries():
            task = next((t for t in list_tasks() if t["id"] == task_id), None)
            daily = (task or {}).get("daily_hours", {})
            if daily:
                lines = [f"{d}: {h:.2f}h" for d, h in sorted(daily.items())]
                entries_label.setText("Logged so far:\n" + "\n".join(lines))
            else:
                entries_label.setText("No days logged yet.")
            return daily

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date:"))
        date_edit = QDateEdit(QDate.currentDate())
        date_edit.setCalendarPopup(True)
        date_row.addWidget(date_edit)
        layout.addLayout(date_row)

        hours_row = QHBoxLayout()
        hours_row.addWidget(QLabel("Hours:"))
        hours_spin = QDoubleSpinBox()
        hours_spin.setRange(0, 24)
        hours_spin.setDecimals(2)
        hours_spin.setSingleStep(0.25)
        hours_row.addWidget(hours_spin)
        layout.addLayout(hours_row)

        daily = _refresh_entries()

        def _sync_spin_to_date():
            hours_spin.setValue(daily.get(date_edit.date().toPyDate().isoformat(), 0.0))

        date_edit.dateChanged.connect(lambda _: _sync_spin_to_date())
        _sync_spin_to_date()

        def _save():
            nonlocal daily
            iso_date = date_edit.date().toPyDate().isoformat()
            try:
                log_task_hours(task_id, iso_date, hours_spin.value())
            except ValueError as exc:
                QMessageBox.warning(self, "Can't Log Hours", str(exc))
                return
            daily = _refresh_entries()
            self._rebuild_todo()

        save_button = QPushButton("Save Day (0 clears it)")
        save_button.clicked.connect(_save)
        layout.addWidget(save_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def _edit_task_clicked(self, task_id):
        task = next((t for t in list_tasks() if t["id"] == task_id), None)
        if task is None:
            return
        projects = list_projects()
        if not projects:
            QMessageBox.information(self, "No Projects Yet", "Create a project code first, in the Projects tab.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Task")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Title:"))
        title_input = QLineEdit(task["title"])
        layout.addWidget(title_input)
        layout.addWidget(QLabel("Project:"))
        project_combo = QComboBox()
        for index, p in enumerate(projects):
            project_combo.addItem(f'{p["code"]} — {p["name"]}', p["code"])
            if p["code"] == task["project_code"]:
                project_combo.setCurrentIndex(index)
        layout.addWidget(project_combo)
        buttons = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(dialog.accept)
        buttons.addWidget(save_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            set_task_title(task_id, title_input.text())
            set_task_project_code(task_id, project_combo.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "Can't Update Task", str(exc))
            return
        self._rebuild_todo()

    def _new_task_clicked(self):
        projects = list_projects()
        if not projects:
            QMessageBox.information(self, "No Projects Yet", "Create a project code first, in the Projects tab.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("New Task")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Title:"))
        title_input = QLineEdit()
        layout.addWidget(title_input)
        layout.addWidget(QLabel("Project:"))
        project_combo = QComboBox()
        for p in projects:
            project_combo.addItem(f'{p["code"]} — {p["name"]}', p["code"])
        layout.addWidget(project_combo)
        layout.addWidget(QLabel("Hours (optional):"))
        hours_input = QDoubleSpinBox()
        hours_input.setRange(0, 999)
        hours_input.setDecimals(2)
        hours_input.setSingleStep(0.25)
        layout.addWidget(hours_input)
        buttons = QHBoxLayout()
        ok_button = QPushButton("Create")
        ok_button.clicked.connect(dialog.accept)
        buttons.addWidget(ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            add_task(title_input.text(), project_combo.currentData(), hours_input.value())
        except ValueError as exc:
            QMessageBox.warning(self, "Can't Create Task", str(exc))
            return
        self._rebuild_todo()

    def _slide_task(self, task_id, direction):
        move_task_status(task_id, direction)
        self._rebuild_todo()

    def _delete_task_clicked(self, task_id, title):
        reply = QMessageBox.question(
            self, "Delete Task", f'Permanently delete "{title}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_task(task_id)
            self._rebuild_todo()

    # ------------------------------------------------------------------
    # Focus Timer (work / break, island + 8-bit dive-computer themed)
    # ------------------------------------------------------------------
    def _build_focus_tab(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setObjectName("focusPanel")
        panel.setStyleSheet(
            f"QFrame#focusPanel {{ background: {FOCUS_PANEL_BG}; "
            f"border: 4px solid {FOCUS_SCREEN_BG}; border-radius: 0px; }}"
        )
        page_layout.addWidget(panel)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addStretch(1)

        def _wave_label():
            wave = QLabel("〜" * 30)
            wave.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wave.setStyleSheet(f"color: #2dd4bf; font-family: {FOCUS_FONT}; font-size: 12px;")
            return wave

        outer.addWidget(_wave_label())

        self.focus_phase_label = QLabel()
        self.focus_phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.focus_phase_label)

        self.focus_time_label = QLabel()
        self.focus_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_time_label.setStyleSheet(
            f"font-family: {FOCUS_FONT}; font-size: 68px; font-weight: bold; color: {FOCUS_INK}; "
            f"background-color: {FOCUS_SCREEN_BG}; border: 3px solid; "
            f"border-top-color: {FOCUS_SCREEN_BG}; border-left-color: {FOCUS_SCREEN_BG}; "
            f"border-right-color: #2dd4bf; border-bottom-color: #2dd4bf; padding: 6px 24px;"
        )
        time_row = QHBoxLayout()
        time_row.addStretch()
        time_row.addWidget(self.focus_time_label)
        time_row.addStretch()
        outer.addLayout(time_row)

        self.focus_progress_label = QLabel()
        self.focus_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_progress_label.setStyleSheet(f"color: {FOCUS_INK}; font-family: {FOCUS_FONT}; font-size: 11px;")
        outer.addWidget(self.focus_progress_label)

        controls_row = QHBoxLayout()
        controls_row.addStretch()
        self.focus_start_button = QPushButton("▶ START")
        self.focus_start_button.setFixedWidth(120)
        self.focus_start_button.setStyleSheet(FOCUS_PIXEL_BUTTON_QSS)
        self.focus_start_button.clicked.connect(self._focus_start_pause_clicked)
        controls_row.addWidget(self.focus_start_button)
        reset_button = QPushButton("⟲ RESET")
        reset_button.setFixedWidth(120)
        reset_button.setStyleSheet(FOCUS_PIXEL_BUTTON_QSS)
        reset_button.clicked.connect(self._focus_reset_clicked)
        controls_row.addWidget(reset_button)
        skip_button = QPushButton("⏭ SKIP")
        skip_button.setFixedWidth(120)
        skip_button.setStyleSheet(FOCUS_PIXEL_BUTTON_QSS)
        skip_button.clicked.connect(self._focus_skip_clicked)
        controls_row.addWidget(skip_button)
        controls_row.addStretch()
        outer.addLayout(controls_row)

        task_row = QHBoxLayout()
        task_row.addStretch()
        task_label = QLabel("LOG TO TASK:")
        task_label.setStyleSheet(f"color: {FOCUS_INK}; font-family: {FOCUS_FONT}; font-size: 11px;")
        task_row.addWidget(task_label)
        self.focus_task_combo = QComboBox()
        self.focus_task_combo.setMinimumWidth(240)
        self.focus_task_combo.setStyleSheet(FOCUS_PIXEL_INPUT_QSS)
        task_row.addWidget(self.focus_task_combo)
        task_row.addStretch()
        outer.addLayout(task_row)

        settings_row = QHBoxLayout()
        settings_row.addStretch()

        def _labeled_spin(label_text, default, maximum=180):
            col = QVBoxLayout()
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {FOCUS_INK}; font-family: {FOCUS_FONT}; font-size: 10px;")
            col.addWidget(label)
            spin = QSpinBox()
            spin.setRange(1, maximum)
            spin.setValue(default)
            spin.setSuffix(" min")
            spin.setStyleSheet(FOCUS_PIXEL_INPUT_QSS)
            col.addWidget(spin)
            settings_row.addLayout(col)
            return spin

        self.focus_work_spin = _labeled_spin("WORK", 25)
        self.focus_break_spin = _labeled_spin("BREAK", 5)
        for spin in (self.focus_work_spin, self.focus_break_spin):
            spin.valueChanged.connect(self._focus_settings_changed)
        settings_row.addStretch()
        outer.addLayout(settings_row)

        outer.addWidget(_wave_label())
        outer.addStretch(2)

        self._focus_phase = "work"
        self._focus_completed_today = 0
        self._focus_running = False
        self._focus_remaining = self.focus_work_spin.value() * 60
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(1000)
        self._focus_timer.timeout.connect(self._focus_tick)

        self._focus_refresh_display()
        return page

    def _refresh_focus_tasks(self):
        current_id = self.focus_task_combo.currentData()
        self.focus_task_combo.blockSignals(True)
        self.focus_task_combo.clear()
        self.focus_task_combo.addItem("(none — just time it)", None)
        restore_index = 0
        for task in list_tasks():
            if task["status"] == "Paid":
                continue
            project = get_project(task["project_code"])
            project_label = project["code"] if project else task["project_code"]
            self.focus_task_combo.addItem(f'{task["title"]} — {project_label}', task["id"])
            if task["id"] == current_id:
                restore_index = self.focus_task_combo.count() - 1
        self.focus_task_combo.setCurrentIndex(restore_index)
        self.focus_task_combo.blockSignals(False)

    def _focus_phase_seconds(self, phase):
        spin = self.focus_work_spin if phase == "work" else self.focus_break_spin
        return spin.value() * 60

    def _focus_refresh_display(self):
        label_text, color = FOCUS_PHASE_INFO[self._focus_phase]
        self.focus_phase_label.setText(label_text.upper())
        self.focus_phase_label.setStyleSheet(
            f"font-family: {FOCUS_FONT}; font-size: 20px; font-weight: bold; color: {color}; letter-spacing: 2px;"
        )
        minutes, seconds = divmod(max(0, self._focus_remaining), 60)
        self.focus_time_label.setText(f"{minutes:02d}:{seconds:02d}")
        self.focus_progress_label.setText(f"⭐ {self._focus_completed_today} WORK SESSION(S) COMPLETED TODAY")
        self.focus_start_button.setText("⏸ PAUSE" if self._focus_running else "▶ START")
        editable = not self._focus_running
        self.focus_work_spin.setEnabled(editable)
        self.focus_break_spin.setEnabled(editable)

    def _focus_settings_changed(self):
        if self._focus_running:
            return
        self._focus_remaining = self._focus_phase_seconds(self._focus_phase)
        self._focus_refresh_display()

    def _focus_start_pause_clicked(self):
        if self._focus_running:
            self._focus_timer.stop()
            self._focus_running = False
        else:
            if self._focus_remaining <= 0:
                self._focus_remaining = self._focus_phase_seconds(self._focus_phase)
            self._focus_timer.start()
            self._focus_running = True
        self._focus_refresh_display()

    def _focus_reset_clicked(self):
        self._focus_timer.stop()
        self._focus_running = False
        self._focus_remaining = self._focus_phase_seconds(self._focus_phase)
        self._focus_refresh_display()

    def _focus_skip_clicked(self):
        self._focus_timer.stop()
        self._focus_running = False
        self._focus_advance_phase()
        self._focus_refresh_display()

    def _focus_tick(self):
        self._focus_remaining -= 1
        if self._focus_remaining <= 0:
            self._focus_timer.stop()
            self._focus_running = False
            self._focus_phase_finished()
        else:
            self._focus_refresh_display()

    def _focus_phase_finished(self):
        finished_phase = self._focus_phase
        if finished_phase == "work":
            self._focus_completed_today += 1
            self._focus_log_hours_if_selected()
        self._focus_advance_phase()
        self._focus_refresh_display()
        finished_label, _ = FOCUS_PHASE_INFO[finished_phase]
        next_label, _ = FOCUS_PHASE_INFO[self._focus_phase]
        QMessageBox.information(self, "Focus Timer", f"{finished_label} done! Next up: {next_label}.")

    def _focus_log_hours_if_selected(self):
        task_id = self.focus_task_combo.currentData()
        if not task_id:
            return
        hours = self.focus_work_spin.value() / 60.0
        try:
            log_task_hours_increment(task_id, date.today().isoformat(), hours)
        except ValueError as exc:
            QMessageBox.warning(self, "Can't Log Hours", str(exc))
            return
        self._rebuild_todo()

    def _focus_advance_phase(self):
        self._focus_phase = "break" if self._focus_phase == "work" else "work"
        self._focus_remaining = self._focus_phase_seconds(self._focus_phase)

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------
    def _build_calendar_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)

        self._highlighted_dates = set()
        self.calendar = QCalendarWidget()
        self.calendar.selectionChanged.connect(self._refresh_calendar_events)
        outer.addWidget(self.calendar, 1)

        side_widget = QWidget()
        side_widget.setMinimumWidth(280)
        side = QVBoxLayout(side_widget)
        self.calendar_date_label = QLabel("")
        self.calendar_date_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        side.addWidget(self.calendar_date_label)
        add_event_button = QPushButton("+ Add Event")
        add_event_button.clicked.connect(self._add_event_clicked)
        side.addWidget(add_event_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.calendar_events_content = QWidget()
        self.calendar_events_layout = QVBoxLayout(self.calendar_events_content)
        self.calendar_events_layout.addStretch()
        scroll.setWidget(self.calendar_events_content)
        side.addWidget(scroll, 1)

        outer.addWidget(side_widget)
        return page

    def _refresh_calendar_events(self):
        iso_date = self.calendar.selectedDate().toPyDate().isoformat()
        self.calendar_date_label.setText(f"Activity on {iso_date}")
        self._clear_layout(self.calendar_events_layout)

        tasks_header = QLabel("Tasks")
        tasks_header.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold; font-size: 11px;")
        self.calendar_events_layout.addWidget(tasks_header)
        active_tasks = tasks_active_on_date(iso_date)
        if not active_tasks:
            self.calendar_events_layout.addWidget(QLabel("No task activity."))
        for entry in active_tasks:
            self.calendar_events_layout.addWidget(self._build_task_activity_row(entry))

        events_header = QLabel("Events")
        events_header.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: bold; font-size: 11px;")
        self.calendar_events_layout.addWidget(events_header)
        events = events_on_date(iso_date)
        if not events:
            self.calendar_events_layout.addWidget(QLabel("No events."))
        for event in events:
            self.calendar_events_layout.addWidget(self._build_event_row(event))

        self.calendar_events_layout.addStretch()
        self._highlight_task_dates()

    def _build_task_activity_row(self, entry):
        task, statuses = entry["task"], entry["statuses"]
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; "
            f"border-left: 3px solid {STATUS_COLORS[task['status']]}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)

        title_label = QLabel(task["title"])
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        layout.addWidget(title_label)

        detail_label = QLabel(f'{task["project_code"]} — {" → ".join(statuses)}')
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(detail_label)
        return row

    def _highlight_task_dates(self):
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(TASK_ACTIVITY_BG))
        current = set(task_activity_dates().keys())
        for iso_date in self._highlighted_dates - current:
            self.calendar.setDateTextFormat(QDate.fromString(iso_date, "yyyy-MM-dd"), QTextCharFormat())
        for iso_date in current:
            self.calendar.setDateTextFormat(QDate.fromString(iso_date, "yyyy-MM-dd"), fmt)
        self._highlighted_dates = current

    def _build_event_row(self, event):
        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; border-radius: 6px; }}")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)

        header_row = QHBoxLayout()
        title_text = event["title"] if not event["time"] else f'{event["time"]} — {event["title"]}'
        title_label = QLabel(title_text)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        header_row.addWidget(title_label, 1)
        delete_button = QPushButton("✕")
        delete_button.clicked.connect(lambda checked=False, event_id=event["id"]: self._delete_event_clicked(event_id))
        header_row.addWidget(delete_button)
        layout.addLayout(header_row)

        if event["description"]:
            description_label = QLabel(event["description"])
            description_label.setWordWrap(True)
            description_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(description_label)
        return row

    def _add_event_clicked(self):
        selected_date = self.calendar.selectedDate().toPyDate().isoformat()
        dialog = QDialog(self)
        dialog.setWindowTitle("New Calendar Event")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Date: {selected_date}"))
        layout.addWidget(QLabel("Title:"))
        title_input = QLineEdit()
        layout.addWidget(title_input)
        layout.addWidget(QLabel("Time (optional):"))
        time_input = QTimeEdit()
        time_input.setDisplayFormat("h:mm AP")
        layout.addWidget(time_input)
        layout.addWidget(QLabel("Description (optional):"))
        description_input = QTextEdit()
        description_input.setFixedHeight(70)
        layout.addWidget(description_input)
        buttons = QHBoxLayout()
        ok_button = QPushButton("Add")
        ok_button.clicked.connect(dialog.accept)
        buttons.addWidget(ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            add_event(
                title_input.text(), selected_date,
                time_input.time().toString("h:mm AP"), description_input.toPlainText(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Can't Add Event", str(exc))
            return
        self._refresh_calendar_events()

    def _delete_event_clicked(self, event_id):
        delete_event(event_id)
        self._refresh_calendar_events()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def _build_projects_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        top_row = QHBoxLayout()
        new_project_button = QPushButton("+ New Project")
        new_project_button.clicked.connect(self._new_project_clicked)
        top_row.addWidget(new_project_button)
        top_row.addStretch()
        outer.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.projects_content = QWidget()
        self.projects_layout = QVBoxLayout(self.projects_content)
        self.projects_layout.addStretch()
        scroll.setWidget(self.projects_content)
        outer.addWidget(scroll, 1)
        return page

    def _rebuild_projects(self):
        self._clear_layout(self.projects_layout)
        projects = list_projects()
        if not projects:
            self.projects_layout.addWidget(QLabel("No projects yet - create one above."))
        for project in projects:
            self.projects_layout.addWidget(self._build_project_card(project))
        self.projects_layout.addStretch()

    def _build_project_card(self, project):
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; border-radius: 8px; }}")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)

        text_col = QVBoxLayout()
        name_label = QLabel(f'{html.escape(project["name"])}  <span style="color:{TEXT_MUTED};">[{html.escape(project["code"])}]</span>')
        name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        text_col.addWidget(name_label)
        if project["description"]:
            description_label = QLabel(project["description"])
            description_label.setWordWrap(True)
            description_label.setStyleSheet(f"color: {TEXT_MUTED};")
            text_col.addWidget(description_label)
        layout.addLayout(text_col, 1)

        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(lambda checked=False, code=project["code"]: self._duplicate_project_clicked(code))
        layout.addWidget(duplicate_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(
            lambda checked=False, code=project["code"], name=project["name"]: self._delete_project_clicked(code, name)
        )
        layout.addWidget(delete_button)
        return card

    def _new_project_clicked(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("New Project")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Name:"))
        name_input = QLineEdit()
        layout.addWidget(name_input)
        layout.addWidget(QLabel("Code:"))
        code_input = QLineEdit()
        layout.addWidget(code_input)
        layout.addWidget(QLabel("Description (optional):"))
        description_input = QTextEdit()
        description_input.setFixedHeight(70)
        layout.addWidget(description_input)
        buttons = QHBoxLayout()
        ok_button = QPushButton("Create")
        ok_button.clicked.connect(dialog.accept)
        buttons.addWidget(ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            add_project(name_input.text(), code_input.text(), description_input.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Can't Create Project", str(exc))
            return
        self._rebuild_projects()

    def _duplicate_project_clicked(self, code):
        duplicate_project(code)
        self._rebuild_projects()

    def _delete_project_clicked(self, code, name):
        in_use = len(tasks_for_project(code))
        warning = f'Permanently delete project "{name}" ({code})?'
        if in_use:
            warning += f"\n\n{in_use} task(s) reference this project code and will keep it as text."
        reply = QMessageBox.question(
            self, "Delete Project", warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_project(code)
            self._rebuild_projects()

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def _build_reports_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)

        self.report_calendar = QCalendarWidget()
        self.report_calendar.selectionChanged.connect(self._refresh_reports)
        outer.addWidget(self.report_calendar, 1)

        self.report_output = QTextEdit()
        self.report_output.setReadOnly(True)
        outer.addWidget(self.report_output, 1)
        return page

    def _refresh_reports(self):
        iso_date = self.report_calendar.selectedDate().toPyDate().isoformat()
        daily = daily_summary(iso_date)
        week_start = week_start_for(iso_date)
        weekly = weekly_summary(week_start)

        lines = [f"<h3>Daily Summary — {iso_date}</h3>"]
        if not daily["tasks"]:
            lines.append("<p><i>No tasks completed this day.</i></p>")
        else:
            lines.append("<ul>")
            for t in daily["tasks"]:
                project = get_project(t["project_code"])
                project_name = project["name"] if project else t["project_code"]
                lines.append(
                    f"<li><b>{html.escape(t['title'])}</b> — "
                    f"{html.escape(project_name)} ({html.escape(t['project_code'])}) — {t['hours']:.2f}h</li>"
                )
            lines.append("</ul>")
            lines.append(
                "<p><b>By project:</b><br>" +
                "<br>".join(f"{html.escape(code)}: {hours:.2f}h" for code, hours in daily["by_project"].items()) +
                "</p>"
            )
        lines.append(f"<p><b>Day total: {daily['total_hours']:.2f} hours</b></p>")

        lines.append(f"<hr><h3>Weekly Wrap-Up — week of {week_start}</h3>")
        for day in weekly["days"]:
            weekday_name = date.fromisoformat(day["date"]).strftime("%A %m/%d")
            lines.append(f"<p><b>{weekday_name}:</b> {len(day['tasks'])} task(s), {day['total_hours']:.2f}h</p>")
        project_lines = "<br>".join(f"{html.escape(code)}: {hours:.2f}h" for code, hours in weekly["by_project"].items())
        lines.append(f"<p><b>Weekly totals by project:</b><br>{project_lines or 'None'}</p>")
        lines.append(f"<p><b>Week grand total: {weekly['total_hours']:.2f} hours</b></p>")

        self.report_output.setHtml("".join(lines))

    # ------------------------------------------------------------------
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout is not None:
                    self._clear_layout(child_layout)
