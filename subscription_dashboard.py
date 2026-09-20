"""The empty-chat dashboard for saved interests and source updates."""
import html
import threading
from core.interest_catalog import CATEGORIES, category_for
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout


INTEREST_TYPES = {
    'team': ('TEAMS', 'Results and upcoming schedule', 'What are the next five fixtures and latest result for {name}?'),
    'weather': ('WEATHER', 'Current conditions', 'What is the weather in {name} right now?'),
    'topic': ('TOPICS', 'News and developments', 'What are the latest developments in {name}?'),
    'website': ('SOURCES', 'From your followed website', 'What are the latest stories from {name}?'),
}


class DashboardUpdateWorker(QThread):
    updated = pyqtSignal(str, object)

    def __init__(self, records, lookup):
        super().__init__()
        self.records, self.lookup = records, lookup
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        for record in self.records:
            if self.cancelled.is_set():
                break
            try:
                evidence = self.lookup(record)
            except Exception:
                evidence = []
            if not self.cancelled.is_set():
                self.updated.emit(record['id'], evidence)


class SubscriptionDashboard(QScrollArea):
    prompt_requested = pyqtSignal(str)
    manage_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('interestDashboard')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records = []
        self.cards = {}
        self.snapshots = {}
        self.busy = False
        content = QWidget()
        content.setObjectName('dashboardContent')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)
        title = QLabel('Your interests, at a glance')
        title.setObjectName('dashboardTitle')
        title.setWordWrap(True)
        layout.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName('mutedLabel')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh updates')
        self.refresh_button.clicked.connect(self.refresh_requested)
        actions.addWidget(self.refresh_button)
        manage = QPushButton('Manage interests')
        manage.clicked.connect(self.manage_requested)
        actions.addWidget(manage)
        actions.addStretch()
        layout.addLayout(actions)
        self.empty = QLabel('Make this space yours.\nFollow sports, news, entertainment, weather, and your own interests in Subscriptions.')
        self.empty.setObjectName('dashboardEmpty')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        layout.addLayout(self.grid)
        layout.addStretch()
        self.setWidget(content)
        self.set_records([])

    def set_records(self, records):
        records = [r for r in records if isinstance(r, dict) and r.get('type') in INTEREST_TYPES and r.get('id') and r.get('name')]
        if records == self.records and self.cards:
            return
        self.records = records
        self.snapshots = {key: value for key, value in self.snapshots.items() if key in {r['id'] for r in records}}
        while self.grid.count():
            taken = self.grid.takeAt(0)
            if taken.widget():
                taken.widget().deleteLater()
        self.cards = {}
        self.empty.setVisible(not records)
        self.summary.setText(f'{len(records)} followed interests · Choose one to prepare a question, or refresh for source updates.' if records
                             else 'A personal starting point for the things you follow.')
        self.refresh_button.setEnabled(bool(records))
        ordered = sorted(records, key=lambda r: (list(CATEGORIES).index(category_for(r)), r['name'].casefold()))
        for record in ordered:
            card = QFrame()
            card.setObjectName('interestCard')
            body = QVBoxLayout(card)
            body.setContentsMargins(16, 16, 16, 16)
            body.setSpacing(10)
            category, description, prompt = INTEREST_TYPES[record['type']]
            if record['type'] == 'team' and record.get('metadata', {}).get('league_name'):
                description = record['metadata']['league_name'] + ' · Results and schedule'
            category = CATEGORIES[category_for(record)].upper()
            tag = QLabel(category)
            tag.setObjectName('interestTag')
            body.addWidget(tag)
            name = QLabel(record['name'])
            name.setTextFormat(Qt.TextFormat.PlainText)
            name.setObjectName('interestName')
            name.setWordWrap(True)
            body.addWidget(name)
            info = QLabel(description)
            info.setObjectName('mutedLabel')
            info.setWordWrap(True)
            body.addWidget(info)
            update = QLabel()
            update.setObjectName('interestUpdate')
            update.setWordWrap(True)
            update.setOpenExternalLinks(True)
            update.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            update.hide()
            body.addWidget(update, 1)
            stamp = QLabel('Refresh for source updates')
            stamp.setObjectName('mutedLabel')
            body.addWidget(stamp)
            ask = QPushButton('Ask about this')
            ask.setToolTip('Prepare a question in the message box')
            ask.clicked.connect(lambda checked=False, text=prompt.format(name=record['name']): self.prompt_requested.emit(text))
            body.addWidget(ask)
            self.cards[record['id']] = (card, update, stamp)
        self._layout_cards()
        for key, (evidence, timestamp) in self.snapshots.items():
            self._show_update(key, evidence, timestamp)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'grid'):
            self._layout_cards()

    def _layout_cards(self):
        columns = 2 if self.viewport().width() >= 600 else 1
        for card, _, _ in self.cards.values():
            self.grid.removeWidget(card)
        for column in range(2):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, (card, _, _) in enumerate(self.cards.values()):
            self.grid.addWidget(card, index // columns, index % columns)

    def set_busy(self, busy):
        self.busy = busy
        self.refresh_button.setText('Stop refresh' if busy else 'Refresh updates')
        self.refresh_button.setEnabled(bool(self.records))

    def set_update(self, key, evidence):
        if key not in self.cards:
            return  # an interest may have been removed during the request
        timestamp = datetime.now().strftime('%H:%M')
        evidence = [r for r in (evidence or []) if isinstance(r, dict) and r.get('content') and
                    str(r.get('url', '')).startswith(('https://', 'http://'))]
        if evidence:
            self.snapshots[key] = (evidence, timestamp)
            self._show_update(key, evidence, timestamp)
        else:
            # Keep an earlier successful update and its original time on failure.
            _, label, stamp = self.cards[key]
            if key not in self.snapshots:
                label.setText('No update available from this source right now.')
                label.show()
            if key in self.snapshots:
                stamp.setText(f'Fetched {self.snapshots[key][1]} · Refresh unavailable at {timestamp}')
            else:
                stamp.setText(f'Update unavailable · Tried {timestamp}')

    def _show_update(self, key, evidence, timestamp):
        _, label, stamp = self.cards[key]
        parts = []
        for item in evidence[:2]:
            url = html.escape(item['url'], quote=True)
            title = html.escape(str(item.get('title') or 'Source'))
            schedule = item.get('sports_schedule')
            if isinstance(schedule, dict) and isinstance(schedule.get('lines'), list):
                lines = '<br/><br/>'.join(html.escape(str(line)) for line in schedule['lines'])
                parts.append(f'<a href="{url}" style="color: #b4a8ff;">{title}</a><br/><br/>{lines}')
                continue
            content = ' '.join(str(item['content']).split())
            excerpt = content[:400] + ('…' if len(content) > 400 else '')
            parts.append(f'<a href="{url}" style="color: #b4a8ff;">{title}</a><br/>{html.escape(excerpt)}')
        label.setText('<br/><br/>'.join(parts))
        label.show()
        stamp.setText(f'Fetched {timestamp} · Source excerpt')
