"""Dashboard updates stay separate from the chat turn and its transcript."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PyQt6')
from PyQt6.QtWidgets import QApplication, QPushButton
from core import subscriptions
import webagent
import webagent_gui
from subscription_dashboard import SubscriptionDashboard, DashboardUpdateWorker


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def gui(qapp, monkeypatch, fake_ollama_chat):
    monkeypatch.setattr(webagent_gui.core_models, 'list_installed', lambda: ['local-model'])
    monkeypatch.setattr(webagent_gui.ResponseWorker, 'start', lambda self: None)
    window = webagent_gui.WebAgentGUI()
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_empty_chat_shows_interests_and_manage_navigation(gui):
    assert gui.chat_surfaces.currentWidget() is gui.interest_dashboard
    assert not gui.interest_dashboard.refresh_button.isEnabled()
    record = subscriptions.add_subscription('topic', 'Space exploration')
    gui._refresh_interest_dashboard()
    assert record['id'] in gui.interest_dashboard.cards
    gui.interest_dashboard.manage_requested.emit()
    assert gui.nav_list.currentRow() == 5
    subscriptions.remove_subscription(record['id'])
    gui.nav_list.setCurrentRow(0)
    assert not gui.interest_dashboard.cards


def test_interest_prompt_is_a_draft_and_dashboard_returns_when_cleared(gui):
    record = subscriptions.add_subscription('weather', 'Phoenix', {'location': 'Phoenix'})
    gui._refresh_interest_dashboard()
    card, _, _ = gui.interest_dashboard.cards[record['id']]
    card.findChild(QPushButton).click()
    assert 'Phoenix' in gui.input_text.toPlainText()
    assert not gui._response_active
    assert gui.chat_surfaces.currentWidget() is gui.interest_dashboard
    gui.display_message('An actual chat message')
    assert gui.chat_surfaces.currentWidget() is gui.chat_display
    gui.chat_display.clear()
    assert gui.chat_surfaces.currentWidget() is gui.interest_dashboard


def test_update_preserves_earlier_data_when_refresh_fails(gui):
    record = subscriptions.add_subscription('team', 'Example team')
    gui._refresh_interest_dashboard()
    dashboard = gui.interest_dashboard
    dashboard.set_update(record['id'], [{'title': 'Results', 'url': 'https://example.com', 'content': 'Won 2–0.'}])
    _, label, stamp = dashboard.cards[record['id']]
    old = label.text()
    dashboard.set_update(record['id'], [])
    assert label.text() == old
    assert 'Refresh unavailable' in stamp.text()
    dashboard.set_update(record['id'], [{'url': 'system://intelligent-fallback', 'content': 'Synthetic answer'}])
    assert label.text() == old
    subscriptions.remove_subscription(record['id'])
    gui._refresh_interest_dashboard()
    dashboard.set_update(record['id'], [])  # late signals for removed interests are harmless
    assert record['id'] not in dashboard.snapshots


def test_background_refresh_delivers_source_updates_without_chat_changes(gui, monkeypatch, qapp):
    record = subscriptions.add_subscription('topic', 'Astronomy')
    monkeypatch.setattr(webagent, 'get_subscription_dashboard_evidence', lambda record: [
        {'title': 'Source headline', 'url': 'https://example.com', 'content': 'An actual source excerpt.'},
    ])
    before = list(webagent.context.assistant_convo)
    gui._refresh_interest_updates()
    worker = gui._dashboard_worker
    assert worker.wait(1000)
    qapp.processEvents()
    assert gui._dashboard_worker is None
    assert not gui.interest_dashboard.busy
    assert 'actual source excerpt' in gui.interest_dashboard.cards[record['id']][1].text()
    assert webagent.context.assistant_convo == before
    assert gui.chat_display.document().isEmpty()


def test_worker_cancellation_and_per_source_failures(qapp):
    records = [{'id': '1'}, {'id': '2'}]
    visited, updates = [], []
    def lookup(record):
        visited.append(record['id'])
        worker.cancel()
        return []
    worker = DashboardUpdateWorker(records, lookup)
    worker.updated.connect(lambda key, data: updates.append((key, data)))
    worker.run()
    assert visited == ['1']
    assert updates == []
    def broken_lookup(record):
        raise RuntimeError('source unavailable')
    worker = DashboardUpdateWorker(records, broken_lookup)
    worker.updated.connect(lambda key, data: updates.append((key, data)))
    worker.run()
    assert updates == [('1', []), ('2', [])]


def test_dashboard_topic_lookup_uses_provider_without_chat_status_or_archiving(monkeypatch):
    result = [{'title': 'Headline', 'url': 'https://example.com', 'content': 'Evidence'}]
    calls = []
    monkeypatch.setattr(webagent, 'search_searx', lambda query: calls.append(query) or result)
    monkeypatch.setattr(webagent, '_emit_status', lambda *args: pytest.fail('Dashboard touched chat status'))
    monkeypatch.setattr(webagent, 'save_web_evidence', lambda *args: pytest.fail('Dashboard archived a chat turn'))
    assert webagent.get_subscription_dashboard_evidence({'type': 'topic', 'name': 'Astronomy'}) == result
    assert calls == ['Astronomy latest news']


def test_custom_interests_follow_category_aliases_and_unfollow(gui):
    from core.interest_catalog import category_for
    gui.interest_category_combo.setCurrentIndex(gui.interest_category_combo.findData('entertainment'))
    gui.interest_name_input.setText('Radiohead')
    gui.interest_keywords_input.setText('Thom Yorke,  ')
    gui.interest_add_button.click()
    record = next(record for record in subscriptions.list_subscriptions() if record['name'] == 'Radiohead')
    assert category_for(record) == 'entertainment'
    assert record['metadata']['keywords'] == ['Thom Yorke']
    assert webagent._matching_subscription('What is new with Thom Yorke?')['id'] == record['id']
    assert record['id'] in gui.interest_dashboard.cards
    assert not gui.interest_name_input.text()
    gui._remove_followed_interest(record['id'])
    assert subscriptions.get_subscription(record['id']) is None
    assert record['id'] not in gui.interest_dashboard.cards


def test_topic_preset_can_be_followed_and_removed(gui):
    button = gui.subscription_catalog_buttons[('topic', 'Music')]
    button.setChecked(True)
    record = next(record for record in subscriptions.list_subscriptions() if record['name'] == 'Music')
    assert record['metadata']['category'] == 'entertainment'
    assert gui.followed_interest_grid.count() == 1
    button.setChecked(False)
    assert subscriptions.get_subscription(record['id']) is None


def test_custom_website_validates_in_worker_and_preserves_category(gui, qapp, monkeypatch):
    monkeypatch.setattr(webagent, 'fetch_page_content', lambda url: 'Source content')
    gui.interest_category_combo.setCurrentIndex(gui.interest_category_combo.findData('news'))
    gui.interest_name_input.setText('My local paper')
    gui.interest_url_input.setText('https://example.org/news')
    gui.interest_add_button.click()
    worker = gui._subscription_workers[-1]
    assert not gui.interest_add_button.isEnabled()
    assert worker.wait(2000)
    qapp.processEvents()
    record = next(record for record in subscriptions.list_subscriptions() if record['name'] == 'My local paper')
    assert record['type'] == 'website'
    assert record['metadata']['category'] == 'news'
    assert record['metadata']['url'] == 'https://example.org/news'
    assert gui.interest_add_button.isEnabled()
    assert not gui._subscription_workers


def test_legacy_categories_are_inferred_without_rewriting_records(gui):
    from core.interest_catalog import category_for
    record = subscriptions.add_subscription('website', 'BBC News', {'url': 'https://www.bbc.com/news'})
    original = subscriptions.get_subscription(record['id'])
    assert category_for(record) == 'news'
    gui._refresh_subscription_buttons()
    assert subscriptions.get_subscription(record['id']) == original
    labels = [label.text() for label in gui.interest_dashboard.cards[record['id']][0].findChildren(webagent_gui.QLabel)]
    assert 'NEWS' in labels


def test_sports_has_one_category_with_team_picker(gui):
    toggles = [button.text() for button in gui.findChildren(QPushButton) if button.objectName() == 'categoryToggle']
    assert sum(text.endswith('  Sports') for text in toggles) == 1
    assert gui.sports_league_combo.count() >= 7
    assert 'sports' == gui.interest_category_combo.itemData(gui.interest_category_combo.findData('sports'))


def test_custom_interest_name_required(gui):
    before = subscriptions.list_subscriptions()
    gui.interest_add_button.click()
    assert 'Enter an interest name' in gui.subscription_status_label.text()
    assert subscriptions.list_subscriptions() == before
