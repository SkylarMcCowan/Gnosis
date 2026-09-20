"""Exercise transcript actions and scrolling with real Qt widgets, without network."""
import copy
import os
import re
import time
from datetime import datetime

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PyQt6')
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QTextCursor

import webagent
import webagent_gui


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def gui(qapp, monkeypatch, fake_ollama_chat):
    monkeypatch.setattr(webagent_gui.core_models, 'list_installed', lambda: ['qwen3.5:4b'])
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    # Drive the actual worker synchronously so tests control chunk/status ordering.
    monkeypatch.setattr(webagent_gui.ResponseWorker, 'start', lambda self: None)
    window = webagent_gui.WebAgentGUI()
    yield window
    window.activity_timer.stop()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def complete(gui, prompt='hello'):
    gui.input_text.setPlainText(prompt)
    gui.send_message()
    gui.response_worker.run()


def test_activity_and_busy_controls(gui):
    assert not gui.copy_reply_button.isEnabled()
    gui.input_text.setPlainText('hello')
    gui.send_message()
    worker = gui.response_worker
    assert gui.activity_timer.isActive()
    assert 'Preparing response ·' in gui.chat_status_label.text()
    assert gui.send_button.text() == 'Stop'
    assert not gui.retry_reply_button.isEnabled()
    gui._activity_started = time.perf_counter() - 3
    gui.on_chat_status('Writing a response...')
    assert 'Waiting for model · 3.' in gui.chat_status_label.text()
    gui.on_chat_status('Thinking...')
    assert gui.chat_status_label.text().startswith('Thinking ·')
    gui.send_message('second request')
    assert gui.response_worker is worker
    worker.run()
    assert not gui.activity_timer.isActive()
    assert gui.chat_status_label.text().startswith('Finished ·')
    assert gui.send_button.text() == 'Send'
    assert gui.input_text.isEnabled()
    assert gui.copy_reply_button.isEnabled()


def test_copy_plain_reply(gui, fake_ollama_chat, qapp):
    fake_ollama_chat.reply = 'Reply with <tags> and\na new line'
    complete(gui)
    gui._render_sources([{'title': 'Reference', 'url': 'https://example.com'}])
    gui.copy_reply_button.click()
    assert QApplication.clipboard().text() == fake_ollama_chat.reply


def test_sources_start_on_separate_paragraph(gui, fake_ollama_chat):
    fake_ollama_chat.reply = 'A short factual answer.'
    complete(gui)
    gui._render_sources([{'title': 'Reference', 'url': 'https://example.com'}])
    text = gui.chat_display.toPlainText()
    assert 'answer.Sources:' not in text
    assert re.search(r'answer\.\n+Sources:', text)


def test_retry_replaces_exchange_and_keeps_draft(gui, fake_ollama_chat):
    fake_ollama_chat.reply = 'Original answer'
    complete(gui)
    gui.conversation_saved_length = len(webagent.context.assistant_convo)
    assert not gui._has_unsaved_messages()
    gui.input_text.setPlainText('Unsent next prompt')
    fake_ollama_chat.reply = 'Replacement answer'
    gui.retry_reply_button.click()
    assert gui.response_worker.user_input == 'hello'
    gui.response_worker.run()
    turns = [m for m in webagent.context.assistant_convo if m['role'] in ('user', 'assistant')]
    assert [(m['role'], m['content']) for m in turns] == [('user', 'hello'), ('assistant', 'Replacement answer')]
    assert 'Original answer' not in gui.chat_display.toPlainText()
    assert 'Replacement answer' in gui.chat_display.toPlainText()
    assert gui.input_text.toPlainText() == 'Unsent next prompt'
    assert gui._has_unsaved_messages()


def test_edit_is_reversible_then_replaces_last_prompt(gui, fake_ollama_chat):
    complete(gui, 'hello')
    before = copy.deepcopy(webagent.context.assistant_convo)
    gui.input_text.setPlainText('Existing draft')
    gui.edit_prompt_button.click()
    assert gui.input_text.toPlainText() == 'hello'
    assert gui.edit_prompt_button.text() == 'Cancel edit'
    assert webagent.context.assistant_convo == before
    gui.edit_prompt_button.click()
    assert gui.input_text.toPlainText() == 'Existing draft'
    gui.edit_prompt_button.click()
    gui.input_text.setPlainText('2+2')
    gui.send_message()
    gui.response_worker.run()
    users = [m['content'] for m in webagent.context.assistant_convo if m['role'] == 'user']
    assert users == ['2+2']
    assert gui.edit_prompt_button.text() == 'Edit last prompt'


def test_retry_keeps_earlier_exchange(gui, fake_ollama_chat):
    complete(gui, 'hello')
    complete(gui, '2+2')
    gui.retry_reply_button.click()
    gui.response_worker.run()
    assert [m['content'] for m in webagent.context.assistant_convo if m['role'] == 'user'] == ['hello', '2+2']
    assert gui.chat_display.toPlainText().count('hello') == 1


def test_scroll_up_keeps_position_during_chunks_and_sources(gui, qapp):
    gui.show()
    qapp.processEvents()
    gui.display_message('\n'.join(f'Line {i}' for i in range(150)))
    qapp.processEvents()
    bar = gui.chat_display.verticalScrollBar()
    assert bar.maximum() > 100
    gui.jump_to_latest()
    bar.setValue(100)
    assert not gui._follow_latest
    assert not gui.jump_latest_button.isHidden()
    selection = QTextCursor(gui.chat_display.document())
    selection.setPosition(0)
    selection.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
    gui.chat_display.setTextCursor(selection)
    bar.setValue(100)
    selected = gui.chat_display.textCursor().selectedText()
    gui.response_start_time = datetime.now()
    gui.on_response_chunk('New streamed text\n' * 20)
    gui.on_sources([{'title': 'Source', 'url': 'https://example.com'}])
    gui.on_response_ready('New streamed text\n' * 20)
    qapp.processEvents()
    assert bar.value() == 100
    assert gui.chat_display.textCursor().selectedText() == selected
    gui.jump_latest_button.click()
    assert bar.value() == bar.maximum()
    assert gui._follow_latest
    gui.on_response_chunk('More text\n' * 5)
    qapp.processEvents()
    assert bar.value() == bar.maximum()


def test_cancel_and_error_restore_actions(gui, monkeypatch):
    gui.input_text.setPlainText('hello')
    gui.send_message()
    gui.on_response_chunk('Partial reply')
    gui.on_send_button_clicked()
    assert gui.chat_status_label.text().startswith('Stopping ·')
    gui.on_chat_status('Researching...')
    assert gui.chat_status_label.text().startswith('Stopping ·')
    gui.response_worker.run()
    assert gui.chat_status_label.text().startswith('Stopped ·')
    assert gui._last_reply == 'Partial reply'
    assert gui.retry_reply_button.isEnabled()
    gui.retry_reply_button.click()
    monkeypatch.setattr(webagent, 'chat_response', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a: None)
    gui.response_worker.run()
    assert gui.chat_status_label.text().startswith('Failed ·')
    assert gui.retry_reply_button.isEnabled()
    assert gui.send_button.text() == 'Send'


def test_loaded_history_has_latest_actions(gui):
    webagent.context.assistant_convo += [
        {'role': 'user', 'content': 'Old prompt'}, {'role': 'assistant', 'content': 'Old reply'},
        {'role': 'user', 'content': 'Latest prompt'}, {'role': 'assistant', 'content': 'Latest reply'},
    ]
    gui._repaint_chat_from_history()
    assert gui._last_prompt == 'Latest prompt'
    assert gui._last_reply == 'Latest reply'
    assert gui.retry_reply_button.isEnabled()
    gui.retry_reply_button.click()
    assert gui.response_worker.user_input == 'Latest prompt'
    assert 'Latest reply' not in gui.chat_display.toPlainText()
    assert 'Old reply' in gui.chat_display.toPlainText()
    gui.response_worker.run()


def test_conversation_reset_and_busy_navigation(gui, monkeypatch):
    complete(gui)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    gui.clear_chat()
    assert not gui.retry_reply_button.isEnabled()
    assert not gui.copy_reply_button.isEnabled()
    gui.input_text.setPlainText('hello')
    gui.send_message()
    before = gui.chat_display.toPlainText()
    gui.clear_chat()
    gui.new_conversation_action()
    assert gui.chat_display.toPlainText() == before
    gui.response_worker.run()


def test_scheduler_actions_arent_replayed(gui, monkeypatch):
    monkeypatch.setattr(webagent.context, 'current_agent', 'scheduler')
    monkeypatch.setattr(webagent, 'run_scheduler_agent_step', lambda prompt: 'Scheduled task created')
    complete(gui, 'schedule something')
    assert gui.copy_reply_button.isEnabled()
    assert not gui.retry_reply_button.isEnabled()
    assert not gui.edit_prompt_button.isEnabled()


def test_actual_worker_signals_complete_on_gui_thread(gui, qapp, monkeypatch):
    from PyQt6.QtCore import QThread, QEventLoop, QTimer
    monkeypatch.setattr(webagent_gui.ResponseWorker, 'start', lambda self: QThread.start(self))
    gui.input_text.setPlainText('hello')
    gui.send_message()
    worker = gui.response_worker
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(3000)
    loop.exec()
    timeout.stop()
    assert worker.wait(1000)
    qapp.processEvents()
    assert not gui._response_active
    assert gui.chat_status_label.text().startswith('Finished ·')
    assert gui.copy_reply_button.isEnabled()
    assert gui.conversation_list.isEnabled()
    assert gui.agent_combo.isEnabled()


def test_evidence_inspector_shows_passage_and_provenance(gui, monkeypatch):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QDialog, QTextBrowser
    source = {'title': 'Saved census', 'url': 'knowledge_base://census.md',
              'content': 'Population was 331 million. <unsafe>', 'captured_at': '2020-01-01',
              'provenance': {'origin': 'saved-web', 'url': 'https://example.org/census',
                             'matched_terms': ['population'], 'date_basis': 'capture'}}
    gui._render_sources([source])
    assert 'Inspect evidence' in gui.chat_display.toPlainText()
    seen = []
    def inspect(dialog):
        seen.append(dialog.findChild(QTextBrowser).toPlainText())
        return 0
    monkeypatch.setattr(QDialog, 'exec', inspect)
    key = next(reversed(gui._source_inspections))
    gui._open_chat_source(QUrl('evidence:' + key))
    assert '331 million. <unsafe>' in seen[0]
    assert '2020-01-01' in seen[0]
    assert 'https://example.org/census' in seen[0]


def test_cancelled_worker_reports_cancel_when_blocked_request_times_out(gui, monkeypatch):
    worker = webagent_gui.ResponseWorker('hello')
    def timeout(*args, **kwargs):
        worker.cancel()
        raise TimeoutError('model stalled')
    monkeypatch.setattr(webagent, 'chat_response', timeout)
    cancelled, errors = [], []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error_occurred.connect(errors.append)
    worker.run()
    assert cancelled == [True] and errors == []


def test_memory_dialog_edits_pins_and_forgets(gui, isolated_data_dir, monkeypatch):
    from PyQt6.QtWidgets import QDialog, QTextEdit, QPushButton
    webagent.save_agent_memory('default', 'Original note')
    def interact(dialog):
        editor = dialog.findChild(QTextEdit)
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        editor.setPlainText('Corrected note')
        buttons['Save edit'].click()
        buttons['Pin / unpin'].click()
        entry = webagent.load_agent_memory('default')[0]
        assert entry['summary'] == 'Corrected note' and entry['pinned']
        buttons['Forget entry'].click()
        assert webagent.load_agent_memory('default') == []
        return 0
    monkeypatch.setattr(QDialog, 'exec', interact)
    gui.open_chat_memory()


def test_knowledge_settings_saves_local_embedding_preference(gui, isolated_data_dir, monkeypatch):
    from PyQt6.QtWidgets import QDialog, QComboBox, QPushButton
    from core.knowledge_retrieval import embedding_model
    monkeypatch.delenv('GNOSIS_EMBEDDING_MODEL', raising=False)
    def interact(dialog):
        combo = dialog.findChild(QComboBox)
        combo.setCurrentText('nomic-embed-text')
        next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Save').click()
        return 0
    monkeypatch.setattr(QDialog, 'exec', interact)
    gui.open_knowledge_settings()
    assert embedding_model(isolated_data_dir) == 'nomic-embed-text'

