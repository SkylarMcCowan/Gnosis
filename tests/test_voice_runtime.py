"""Voice lifecycle tests use fake microphones and speakers, never real devices."""
import os
import threading
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PyQt6')
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from voice import runtime


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


from voice_fakes import FakeListener, FakeSpeaker


@pytest.fixture
def session(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'ListeningWorker', FakeListener)
    monkeypatch.setattr(runtime, 'SpeechWorker', FakeSpeaker)
    model = tmp_path / 'model'
    (model / 'am').mkdir(parents=True)
    (model / 'am' / 'final.mdl').touch()
    voice = runtime.VoiceSession()
    voice.model_path = str(model)
    yield voice
    voice.shutdown()
    voice.deleteLater()
    qapp.processEvents()


def test_hands_free_turn_releases_mic_before_streamed_speech(session):
    heard = []
    session.heard.connect(heard.append)
    session.start()
    listener = session.listener
    listener.recognized.emit('Hello there', 250)
    assert heard == ['Hello there']
    session.begin_reply()
    session.feed('Hello. How are ')
    speaker = session.speaker
    assert speaker.items == ['Hello.']
    assert not speaker.started  # microphone thread hasn't closed yet
    listener.finished.emit()
    assert speaker.started
    assert session.listener is None
    session.feed('you? ')
    session.finish_reply()
    assert speaker.items == ['Hello.', 'How are you?', None]
    assert session.listener is None  # playback still running
    speaker.finished.emit()
    assert session.listener is None  # echo cooldown
    session._restart_timer.stop()
    session._maybe_listen()
    assert session.listener.started
    assert session.listener.args[-1] == 250  # reuse calibration


def test_mute_end_and_stale_transcripts(session):
    heard = []
    session.heard.connect(heard.append)
    session.start()
    listener = session.listener
    session.mute(True)
    assert listener.cancelled.is_set()
    listener.recognized.emit('ignore me', 200)
    assert heard == []
    listener.finished.emit()
    assert session.listener is None
    session.mute(False)
    listener = session.listener
    session.stop()
    listener.recognized.emit('also ignore me', 200)
    assert heard == []
    listener.finished.emit()
    assert session.listener is None


def test_interrupt_cancels_generation_and_discards_queued_speech(session):
    requested = []
    session.interrupt_requested.connect(lambda: requested.append(True))
    session.start()
    listener = session.listener
    session.begin_reply()
    listener.finished.emit()
    session.feed('First sentence. ')
    speaker = session.speaker
    session.interrupt()
    assert requested == [True]
    assert speaker.backend.cancelled.is_set()
    session.feed('Never speak this. ')
    session.finish_reply(success=False)
    assert 'Never speak this.' not in speaker.items
    speaker.finished.emit()
    session._restart_timer.stop()
    session._maybe_listen()
    assert session.listener.started


def test_typed_prompt_during_playback_waits_for_old_speaker(session):
    session.start()
    listener = session.listener
    session.begin_reply()
    listener.finished.emit()
    session.feed('Old answer. ')
    old = session.speaker
    session.finish_reply()
    session.begin_reply()
    session.feed('New answer. ')
    new = session.speaker
    assert old.backend.cancelled.is_set()
    assert not new.started
    old.finished.emit()
    assert new.started
    session.finish_reply()
    assert new.items == ['New answer.', None]


def test_spoken_end_command_is_exact(session):
    session.start()
    listener = session.listener
    listener.recognized.emit('End voice mode.', 250)
    assert not session.enabled
    listener.finished.emit()
    session.start()
    heard = []
    session.heard.connect(heard.append)
    session.listener.recognized.emit('How do I end voice mode?', 250)
    assert heard == ['How do I end voice mode?']


def test_worker_fault_stops_session_without_restarting_mic(session):
    errors = []
    session.error.connect(errors.append)
    session.start()
    listener = session.listener
    listener.error.emit('Permission denied')
    listener.finished.emit()
    assert errors == ['Permission denied']
    assert not session.enabled
    assert session.listener is None


def test_settings_persist_locally(session, isolated_data_dir):
    session.save_settings(session.model_path, 'Samantha', 210)
    restored = runtime.VoiceSession()
    assert restored.model_path == session.model_path
    assert restored.output_voice == 'Samantha'
    assert restored.rate == 210
    assert (isolated_data_dir / 'voice_settings.json').exists()
    with pytest.raises(ValueError):
        session.save_settings('/missing-model', '', 190)


def test_sentence_streaming_skips_code_and_urls():
    buffer = runtime.SentenceBuffer()
    assert buffer.feed('Hello') == []
    assert buffer.feed('. Visit https://example.com. ') == ['Hello.', 'Visit']
    assert buffer.feed('```python\nprint("hidden")\n```\n') == []
    assert buffer.feed('Back to speaking. ') == ['Back to speaking.']
    buffer.feed('Final sentence without punctuation')
    assert buffer.flush() == ['Final sentence without punctuation']


def test_local_transcription_cannot_fall_back_to_google(tmp_path):
    with pytest.raises(ValueError):
        runtime.transcribe(None, None, 'google', '', str(tmp_path))


def test_capture_closes_microphone_before_transcription(monkeypatch):
    closed, recognized = [], []
    class Stream:
        def read(self, size):
            return b'\0' * (size * 2)
        def close(self):
            closed.append(True)
    class Microphone:
        SAMPLE_WIDTH = 2
        def __enter__(self):
            self.stream = Stream()
            return self
        def __exit__(self, *args):
            self.stream.close()
    class Recognizer:
        energy_threshold = 300
        def adjust_for_ambient_noise(self, source, duration):
            source.stream.read(64)
        def listen(self, *args, **kwargs):
            return 'audio'
    class UnknownValueError(Exception):
        pass
    sr = SimpleNamespace(Recognizer=Recognizer, Microphone=Microphone,
                         WaitTimeoutError=TimeoutError, UnknownValueError=UnknownValueError, RequestError=ConnectionError)
    monkeypatch.setattr(runtime.webagent, 'sr', sr)
    def transcribe(*args):
        assert closed == [True]
        return 'Keep My Casing'
    monkeypatch.setattr(runtime, 'transcribe', transcribe)
    worker = runtime.ListeningWorker('vosk')
    worker.recognized.connect(lambda text, energy: recognized.append(text))
    worker.run()
    assert recognized == ['Keep My Casing']
    worker.cancel()
    worker.run()
    assert recognized == ['Keep My Casing']


def test_local_decoder_collects_endpoint_results(monkeypatch, tmp_path):
    import sys
    class Decoder:
        def __init__(self, model, sample_rate):
            self.calls = 0
        def AcceptWaveform(self, chunk):
            self.calls += 1
            return self.calls == 1
        def Result(self):
            return '{"text":"first phrase"}'
        def FinalResult(self):
            return '{"text":"last phrase"}'
    monkeypatch.setitem(sys.modules, 'vosk', SimpleNamespace(Model=lambda path: 'model', KaldiRecognizer=Decoder))
    monkeypatch.setattr(runtime, '_vosk_models', {})
    audio = SimpleNamespace(get_raw_data=lambda **kwargs: b'\0' * 8000)
    assert runtime.transcribe(None, audio, 'vosk', '', str(tmp_path)) == 'first phrase last phrase'


def test_streamed_source_section_is_never_spoken():
    buffer = runtime.SentenceBuffer()
    spoken = []
    for chunk in ['Here is the answer [', '1].\n', '**Sou', 'rces:**\n', '[1] A publication.\n', 'Another reference']:
        spoken.extend(buffer.feed(chunk))
    spoken.extend(buffer.flush())
    assert spoken == ['Here is the answer .']


def test_neural_speech_uses_selected_voice_rate_and_cleans_files(monkeypatch):
    from pathlib import Path
    backend = runtime.SystemSpeech('neural:en-US-AriaNeural', 175)
    calls = []
    def run(command, timeout=30):
        calls.append(command)
        if '--file' in command:
            source = Path(command[command.index('--file') + 1])
            assert source.read_text() == 'Hello, how are you?'
            assert '--rate=+0%' in command
            assert command[command.index('--voice') + 1] == 'en-US-AriaNeural'
        return True
    monkeypatch.setattr(backend, '_run_process', run)
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Darwin')
    backend.speak('Hello, how are you?')
    assert calls[1][0] == 'afplay'
    assert not Path(calls[1][1]).parent.exists()


def test_cancelled_neural_synthesis_does_not_start_playback(monkeypatch):
    backend = runtime.SystemSpeech('neural:en-US-GuyNeural')
    calls = []
    monkeypatch.setattr(backend, '_run_process', lambda command, **kw: calls.append(command) or False)
    backend.speak('Hello')
    assert len(calls) == 1
