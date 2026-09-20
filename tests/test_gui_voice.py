"""Voice turns flow through the same transcript/backend as typed chat."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PyQt6')
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QPushButton, QLineEdit, QSpinBox
import webagent
import webagent_gui
from voice import runtime
from voice_fakes import FakeListener, FakeSpeaker


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def gui(qapp, monkeypatch, fake_ollama_chat, tmp_path):
    monkeypatch.setattr(runtime, 'ListeningWorker', FakeListener)
    monkeypatch.setattr(runtime, 'SpeechWorker', FakeSpeaker)
    monkeypatch.setattr(webagent_gui.core_models, 'list_installed', lambda: ['qwen3.5:4b'])
    monkeypatch.setattr(webagent_gui.ResponseWorker, 'start', lambda self: None)
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    window = webagent_gui.WebAgentGUI()
    model = tmp_path / 'model'
    (model / 'am').mkdir(parents=True)
    (model / 'am' / 'final.mdl').touch()
    window.voice_session.model_path = str(model)
    yield window
    if window._response_active:
        window.response_worker.cancel()
        window.response_worker.run()
    window.voice_session.shutdown()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_voice_to_voice_updates_transcript_and_preserves_typed_draft(gui, fake_ollama_chat):
    fake_ollama_chat.reply = 'Hello. This is a spoken reply.'
    gui.input_text.setPlainText('My unsent draft')
    gui.voice_check.setChecked(True)
    session = gui.voice_session
    assert session.enabled
    assert session.listener.args[0] == 'vosk'
    assert not gui.voice_panel.isHidden()
    listener = session.listener
    listener.recognized.emit('hello', 250)
    assert gui._voice_turn
    assert gui.response_worker.user_input == 'hello'
    assert gui.input_text.toPlainText() == 'My unsent draft'
    listener.finished.emit()
    gui.response_worker.run()
    assert gui._last_reply == fake_ollama_chat.reply
    speaker = session.speaker
    assert speaker.started
    assert speaker.items == ['Hello.', 'This is a spoken reply.', None]
    transcript = gui.chat_display.toPlainText()
    assert 'hello' in transcript
    assert fake_ollama_chat.reply in transcript
    assert webagent.context.assistant_convo[-1]['content'] == fake_ollama_chat.reply
    assert session.listener is None
    speaker.finished.emit()
    session._restart_timer.stop()
    session._maybe_listen()
    assert session.listener.started
    assert gui.voice_check.isChecked()


def test_first_sentence_starts_audio_before_model_finishes(gui, monkeypatch):
    gui.voice_check.setChecked(True)
    listener = gui.voice_session.listener
    listener.recognized.emit('hello', 250)
    listener.finished.emit()
    def chat(**kwargs):
        def stream():
            yield {'message': {'content': 'First sentence. '}}
            assert gui.voice_session.speaker.started
            assert gui._response_active
            yield {'message': {'content': 'Second sentence.'}}
        return stream()
    monkeypatch.setattr(webagent.ollama, 'chat', chat)
    gui.response_worker.run()
    assert gui.voice_session.speaker.items == ['First sentence.', 'Second sentence.', None]


def test_interrupt_stops_speech_and_request_then_resumes_listening(gui):
    gui.voice_check.setChecked(True)
    listener = gui.voice_session.listener
    listener.recognized.emit('hello', 250)
    listener.finished.emit()
    gui.on_response_chunk('Partial reply. ')
    speaker = gui.voice_session.speaker
    gui.voice_panel.interrupt_button.click()
    assert speaker.backend.cancelled.is_set()
    assert gui.response_worker._cancel_requested
    gui.response_worker.run()
    assert gui.chat_status_label.text().startswith('Stopped')
    speaker.finished.emit()
    gui.voice_session._restart_timer.stop()
    gui.voice_session._maybe_listen()
    assert gui.voice_session.listener.started
    assert gui.voice_check.isChecked()


def test_mute_end_and_error_can_restart(gui):
    gui.voice_check.setChecked(True)
    listener = gui.voice_session.listener
    gui.voice_panel.mute_button.click()
    assert gui.voice_session.muted
    assert listener.cancelled.is_set()
    listener.finished.emit()
    gui.voice_panel.mute_button.click()
    assert gui.voice_session.listener.started
    listener = gui.voice_session.listener
    listener.error.emit('Microphone permission denied')
    listener.finished.emit()
    assert not gui.voice_check.isChecked()
    assert not gui.voice_panel.isHidden()
    assert 'permission denied' in gui.voice_panel.status.text()
    gui.voice_check.setChecked(True)
    assert gui.voice_session.enabled
    gui.voice_panel.end_button.click()
    assert not gui.voice_session.enabled
    assert gui.voice_panel.isHidden()


def test_voice_settings_are_local_and_applied(gui, qapp, monkeypatch):
    monkeypatch.setattr(webagent_gui.webagent.subprocess, 'check_output', lambda *a, **kw: 'Samantha en_US # hello')
    def fill():
        dialog = qapp.activeModalWidget()
        assert 'Voice settings' in dialog.windowTitle()
        dialog.findChild(QSpinBox).setValue(220)
        next(b for b in dialog.findChildren(QPushButton) if b.text() == 'Save').click()
    QTimer.singleShot(0, fill)
    gui.open_voice_settings()
    assert gui.voice_session.rate == 220


def test_stop_button_and_close_cancel_voice_request(gui, qapp):
    gui.voice_check.setChecked(True)
    listener = gui.voice_session.listener
    listener.recognized.emit('hello', 250)
    listener.finished.emit()
    gui.on_response_chunk('Partial speech. ')
    speaker = gui.voice_session.speaker
    gui.on_send_button_clicked()
    assert speaker.backend.cancelled.is_set()
    gui.close()
    assert gui._close_requested
    assert not gui.voice_session.enabled
    gui.response_worker.run()
    qapp.processEvents()


def test_tts_and_voice_can_stay_enabled_together(gui):
    gui.tts_check.setChecked(True)
    gui.voice_check.setChecked(True)
    assert gui.voice_session.enabled
    assert gui.tts_check.isChecked()
    gui.tts_check.setChecked(False)
    gui.tts_check.setChecked(True)
    assert gui.voice_session.enabled
    assert gui.voice_check.isChecked()


def test_preview_uses_unsaved_voice_and_speed_and_cancel_stops_it(gui, qapp, monkeypatch):
    from PyQt6.QtWidgets import QComboBox
    workers = []
    class PreviewSpeaker(FakeSpeaker):
        def __init__(self, *args):
            super().__init__(*args)
            self.args = args
            workers.append(self)
    monkeypatch.setattr(runtime, 'SpeechWorker', PreviewSpeaker)
    saved = (gui.voice_session.output_voice, gui.voice_session.rate)
    def preview_and_cancel():
        dialog = qapp.activeModalWidget()
        combo = dialog.findChild(QComboBox)
        combo.setCurrentIndex(combo.findData('neural:en-US-AriaNeural'))
        dialog.findChild(QSpinBox).setValue(180)
        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == 'Preview voice')
        button.click()
        worker = workers[-1]
        assert worker.args == ('neural:en-US-AriaNeural', 180)
        assert worker.started
        assert worker.items[-1] is None
        assert 'This is how I sound.' in worker.items[0]
        assert button.text() == 'Stop preview'
        button.click()
        assert worker.backend.cancelled.is_set()
        worker.finished.emit()
        assert button.text() == 'Preview voice'
        button.click()
        dialog.reject()
    QTimer.singleShot(0, preview_and_cancel)
    gui.open_voice_settings()
    assert workers[-1].backend.cancelled.is_set()
    assert (gui.voice_session.output_voice, gui.voice_session.rate) == saved
    workers[-1].finished.emit()
