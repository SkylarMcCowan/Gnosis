"""Cancellable microphone capture, sentence buffering, and system speech.

Audio capture ends before playback starts, so speakers can't become new prompts.
Speech recognition runs locally with Vosk and an extracted model folder.
"""
import json
import os
import platform
import queue
import re
import subprocess
import threading
import time
import sys
import tempfile
import shutil

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from core import config

import webagent


class _ListeningCancelled(Exception):
    pass


class SentenceBuffer:
    """Speak completed sentences promptly, with bounded chunks for long prose."""
    def __init__(self):
        self.text = ''
        self.in_code = False
        self.in_sources = False

    def feed(self, chunk):
        self.text += chunk
        ready = []
        while self.text:
            match = re.search(r'[.!?](?:["\u201d\u2019])?(?=\s)|\n', self.text)
            end = match.end() if match else 0
            if not end and len(self.text) > 240:
                end = self.text.rfind(' ', 0, 240)
            if not end:
                break
            ready.extend(self._clean(self.text[:end]))
            self.text = self.text[end:].lstrip()
        return ready

    def flush(self):
        text, self.text = self.text, ''
        return self._clean(text)

    def _clean(self, text):
        if self.in_sources:
            return []
        if not self.in_code and webagent._is_tts_source_heading(text):
            self.in_sources = True
            return []
        # Don't read fenced source code aloud; leave it in the transcript.
        pieces = text.split('```')
        spoken = []
        for index, piece in enumerate(pieces):
            if index:
                self.in_code = not self.in_code
            if not self.in_code:
                cleaned = webagent._clean_tts_text(piece)
                if cleaned:
                    spoken.append(cleaned)
        return spoken


class _MeteredStream:
    def __init__(self, stream, cancelled, level, width):
        self.stream, self.cancelled, self.level, self.width = stream, cancelled, level, width
        self.last_level = 0

    def read(self, size):
        if self.cancelled.is_set():
            raise _ListeningCancelled()
        data = self.stream.read(size)
        if time.monotonic() - self.last_level > 0.06:
            # SpeechRecognition already depends on audioop (audioop-lts on 3.13+).
            import audioop
            self.level(min(1.0, audioop.rms(data, self.width) / 3000))
            self.last_level = time.monotonic()
        return data

    def close(self):
        self.stream.close()


_vosk_models = {}


def transcribe(recognizer, audio, provider, language, model_path):
    if provider != 'vosk':
        raise ValueError('Unknown speech recognition provider.')
    if not os.path.isdir(model_path):
        raise RuntimeError('Choose an extracted Vosk speech model folder in Voice settings.')
    try:
        from vosk import Model, KaldiRecognizer
    except ImportError:
        raise RuntimeError('Local recognition needs Vosk. Install it with pip install -r requirements.txt.') from None
    if model_path not in _vosk_models:
        _vosk_models[model_path] = Model(model_path)
    decoder = KaldiRecognizer(_vosk_models[model_path], 16000)
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    parts = []
    for offset in range(0, len(raw), 4000):
        if decoder.AcceptWaveform(raw[offset:offset + 4000]):
            parts.append(json.loads(decoder.Result()).get('text', ''))
    parts.append(json.loads(decoder.FinalResult()).get('text', ''))
    return ' '.join(part for part in parts if part)


class ListeningWorker(QThread):
    recognized = pyqtSignal(str, float)
    phase = pyqtSignal(str)
    level = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self, provider='vosk', language='en-US', model_path='', energy=None):
        super().__init__()
        self.provider, self.language, self.model_path, self.energy = provider, language, model_path, energy
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        sr = webagent.sr
        if sr is None:
            self.error.emit('Install SpeechRecognition and PyAudio to use the microphone.')
            return
        try:
            recognizer = sr.Recognizer()
            recognizer.operation_timeout = 12
            recognizer.pause_threshold = 0.8
            with sr.Microphone() as source:
                source.stream = _MeteredStream(source.stream, self.cancelled, self.level.emit, source.SAMPLE_WIDTH)
                if self.energy is None:
                    self.phase.emit('Calibrating microphone')
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                else:
                    recognizer.energy_threshold = self.energy
                self.phase.emit('Listening')
                while not self.cancelled.is_set():
                    try:
                        audio = recognizer.listen(source, timeout=1, phrase_time_limit=30)
                        break
                    except sr.WaitTimeoutError:
                        continue
                else:
                    return
            # The microphone is closed before transcription or any response audio.
            if self.cancelled.is_set():
                return
            self.phase.emit('Transcribing')
            text = transcribe(recognizer, audio, self.provider, self.language, self.model_path).strip()
            if text and not self.cancelled.is_set():
                self.recognized.emit(text, recognizer.energy_threshold)
        except _ListeningCancelled:
            pass
        except sr.UnknownValueError:
            if not self.cancelled.is_set():
                self.phase.emit("Didn't catch that — try again")
        except Exception as exc:
            if not self.cancelled.is_set():
                if isinstance(exc, sr.RequestError):
                    message = 'Local speech recognition is unavailable. Check your downloaded model folder.'
                else:
                    message = f'Microphone / recognition error: {exc}'
                self.error.emit(message)
        finally:
            self.level.emit(0)


class SystemSpeech:
    """Own the playback process, so interruption affects only this session."""
    def __init__(self, voice="", rate=175):
        self.voice, self.rate = voice, rate
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.engine = None

    def _run_process(self, command, timeout=30):
        with self.lock:
            if self.cancelled.is_set():
                return False
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.process = process
        try:
            result = process.wait(timeout=timeout)
            if result and not self.cancelled.is_set():
                raise RuntimeError('Neural speech failed. Check your connection or select a local voice.')
            return not self.cancelled.is_set()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            with self.lock:
                if self.process is process:
                    self.process = None

    def _speak_neural(self, text):
        # A child process makes synthesis cancellable, including network waits.
        with tempfile.TemporaryDirectory(prefix='gnosis-speech-') as folder:
            source = os.path.join(folder, 'reply.txt')
            audio = os.path.join(folder, 'reply.mp3')
            with open(source, 'w', encoding='utf-8') as handle:
                handle.write(text)
            percent = round((self.rate / 175 - 1) * 100)
            command = [sys.executable, '-m', 'edge_tts', '--voice', self.voice.removeprefix('neural:'),
                       '--file', source, f'--rate={percent:+d}%', '--write-media', audio]
            if self._run_process(command):
                if platform.system() == 'Darwin':
                    player = ['afplay', audio]
                elif shutil.which('mpv'):
                    player = ['mpv', '--no-video', '--really-quiet', audio]
                else:
                    raise RuntimeError('Neural speech playback needs mpv on this platform.')
                self._run_process(player, timeout=180)

    def speak(self, text):
        if self.voice.startswith('neural:'):
            self._speak_neural(text)
            return
        if platform.system() == 'Darwin':
            with self.lock:
                if self.cancelled.is_set():
                    return
                command = ['say', '-r', str(self.rate)]
                if self.voice:
                    command += ['-v', self.voice]
                process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True)
                self.process = process
            process.communicate(text)
            result = process.returncode
            with self.lock:
                self.process = None
            if result and not self.cancelled.is_set():
                raise RuntimeError('System speech playback failed.')
        else:
            if not webagent.has_pyttsx3:
                raise RuntimeError('Install pyttsx3 to enable spoken replies.')
            with webagent.pyttsx3_speech_lock:
                engine = webagent._init_pyttsx3_engine()
                engine.setProperty('rate', self.rate)
                if self.voice:
                    engine.setProperty('voice', self.voice)
                with self.lock:
                    if self.cancelled.is_set():
                        engine.stop()
                        return
                    self.engine = engine
                try:
                    engine.say(text)
                    engine.runAndWait()
                finally:
                    engine.stop()
                    with self.lock:
                        self.engine = None

    def cancel(self):
        with self.lock:
            self.cancelled.set()
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
            if self.engine is not None:
                try:
                    self.engine.stop()
                except Exception:
                    pass


class SpeechWorker(QThread):
    speaking = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, voice="", rate=175):
        super().__init__()
        self.items = queue.Queue()
        self.backend = SystemSpeech(voice, rate)

    def enqueue(self, text):
        self.items.put(text)

    def finish_input(self):
        self.items.put(None)

    def cancel(self):
        self.backend.cancel()
        self.items.put(None)

    def run(self):
        try:
            while not self.backend.cancelled.is_set():
                text = self.items.get()
                if text is None or self.backend.cancelled.is_set():
                    break
                self.speaking.emit(True)
                self.backend.speak(text)
                self.speaking.emit(False)
        except Exception as exc:
            if not self.backend.cancelled.is_set():
                self.error.emit(f'Speech playback error: {exc}')
        finally:
            self.speaking.emit(False)


class VoicePreview(QObject):
    """One cancellable sample, independent of saved settings and recognition."""
    active_changed = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

    def start(self, voice, rate):
        if self.worker is not None:
            return
        worker = SpeechWorker(voice, rate)
        self.worker = worker
        worker.error.connect(self.error.emit)
        worker.finished.connect(self._finished)
        worker.enqueue("Hi there. This is how I sound. What would you like to talk about today?")
        worker.finish_input()
        self.active_changed.emit(True)
        worker.start()

    def stop(self):
        if self.worker is not None:
            self.worker.cancel()

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.active_changed.emit(False)

    def shutdown(self):
        self.stop()
        return self.worker is None or self.worker.wait(1000)


class VoiceSession(QObject):
    phase = pyqtSignal(str)
    level = pyqtSignal(float)
    heard = pyqtSignal(str)
    enabled_changed = pyqtSignal(bool)
    speaking = pyqtSignal(bool)
    error = pyqtSignal(str)
    interrupt_requested = pyqtSignal()
    idle = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.muted = False
        self.provider = 'vosk'
        self.language = os.getenv('GNOSIS_SPEECH_LANGUAGE', 'en-US')
        self.model_path = os.getenv('GNOSIS_VOSK_MODEL', os.path.join(os.path.dirname(__file__), 'models', 'vosk-model-small-en-us-0.15'))
        self.output_voice = 'Samantha' if platform.system() == 'Darwin' else ''
        self.rate = 175
        try:
            with open(config.path('voice_settings.json'), encoding='utf-8') as handle:
                saved = json.load(handle)
            self.model_path = os.getenv('GNOSIS_VOSK_MODEL') or saved.get('model_path') or self.model_path
            self.output_voice = str(saved.get('output_voice') or self.output_voice)
            self.rate = max(80, min(300, int(saved.get('rate', 175))))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.listener = None
        self.speaker = None
        self.retiring_speaker = None
        self.speaker_started = False
        self.reply_pending = False
        self.discard_reply = False
        self.energy = None
        self.buffer = SentenceBuffer()
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._maybe_listen)

    def start(self):
        if self.enabled:
            return
        if not webagent.has_speech_recognition or not webagent.has_tts_backend():
            self.error.emit('Voice chat needs microphone recognition and a system speech voice.')
            return
        if not os.path.isfile(os.path.join(self.model_path, 'am', 'final.mdl')):
            self.error.emit('Choose a downloaded Vosk speech model folder in Voice settings.')
            return
        self.enabled = True
        self.muted = False
        self.discard_reply = False
        self.enabled_changed.emit(True)
        self._maybe_listen()

    def save_settings(self, model_path, output_voice, rate):
        if not os.path.isfile(os.path.join(model_path, 'am', 'final.mdl')):
            raise ValueError('Select an extracted Vosk model folder containing am/final.mdl.')
        self.model_path, self.output_voice = model_path, output_voice
        self.rate = max(80, min(300, rate))
        self.energy = None
        path = config.path('voice_settings.json')
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(path), delete=False) as handle:
            json.dump({'model_path': model_path, 'output_voice': output_voice, 'rate': self.rate}, handle)
            temporary = handle.name
        os.replace(temporary, path)

    def stop(self):
        self.enabled = False
        self._restart_timer.stop()
        self.discard_reply = True
        if self.retiring_speaker is not None:
            self.retiring_speaker.cancel()
        if self.listener is not None:
            self.listener.cancel()
        if self.speaker is not None:
            self.speaker.cancel()
            if not self.speaker_started:
                self.speaker.deleteLater()
                self.speaker = None
        self.enabled_changed.emit(False)
        self.level.emit(0)
        self.phase.emit('Voice conversation ended')

    def mute(self, muted):
        self.muted = muted
        if muted:
            self.level.emit(0)
        if muted and self.listener is not None:
            self.listener.cancel()
        if not self.reply_pending and self.speaker is None:
            self.phase.emit('Microphone muted' if muted else 'Listening')
        self._maybe_listen()

    def cancel_audio(self):
        self.discard_reply = True
        if self.speaker is not None:
            self.speaker.cancel()

    def interrupt(self):
        if not self.enabled:
            return
        self.cancel_audio()
        self.phase.emit('Interrupting')
        if self.reply_pending:
            self.interrupt_requested.emit()
        else:
            self._maybe_listen()

    def begin_reply(self):
        if self.speaker is not None:
            self.speaker.cancel()
            if self.speaker_started:
                self.retiring_speaker = self.speaker
            else:
                self.speaker.deleteLater()
            self.speaker = None
            self.speaker_started = False
        self.reply_pending = True
        self.discard_reply = False
        self.buffer = SentenceBuffer()
        if self.listener is not None:
            self.listener.cancel()
        if self.enabled:
            self.phase.emit('Thinking')

    def feed(self, text):
        if self.enabled and not self.discard_reply:
            for sentence in self.buffer.feed(text):
                self._enqueue(sentence)

    def finish_reply(self, success=True):
        if success and self.enabled and not self.discard_reply:
            for sentence in self.buffer.flush():
                self._enqueue(sentence)
            if self.speaker is not None:
                self.speaker.finish_input()
        else:
            if self.speaker is not None:
                self.speaker.cancel()
        self.reply_pending = False
        self._maybe_listen()

    def _enqueue(self, text):
        if self.speaker is None:
            worker = SpeechWorker(self.output_voice, self.rate)
            self.speaker = worker
            self.speaker_started = False
            worker.speaking.connect(lambda talking: self._on_speaking(worker, talking))
            worker.error.connect(lambda message: self._worker_fault(worker, message))
            worker.finished.connect(lambda: self._speaker_finished(worker))
        self.speaker.enqueue(text)
        self._maybe_start_speaker()

    def _maybe_start_speaker(self):
        if self.enabled and self.listener is None and self.retiring_speaker is None and self.speaker is not None and not self.speaker_started:
            self.speaker_started = True
            self.speaker.start()

    def _maybe_listen(self):
        if not self.enabled or self.muted or self.reply_pending or self.listener is not None or self.speaker is not None or self.retiring_speaker is not None or self._restart_timer.isActive():
            return
        worker = ListeningWorker(self.provider, self.language, self.model_path, self.energy)
        self.listener = worker
        worker.recognized.connect(lambda text, energy: self._on_heard(worker, text, energy))
        worker.phase.connect(lambda phase: self._on_listener_phase(worker, phase))
        worker.level.connect(lambda level: self.level.emit(level) if self.enabled and worker is self.listener and not self.muted else None)
        worker.error.connect(lambda message: self._worker_fault(worker, message))
        worker.finished.connect(lambda: self._listener_finished(worker))
        self.phase.emit('Listening')
        worker.start()

    def _on_heard(self, worker, text, energy):
        if worker is not self.listener or worker.cancelled.is_set():
            return
        if not self.enabled or self.muted or self.reply_pending:
            return
        self.energy = energy
        if text.casefold().strip(' .!?') in {'end voice mode', 'stop voice', 'voice stop', 'end conversation'}:
            self.stop()
            return
        self.reply_pending = True
        self.phase.emit('Thinking')
        self.heard.emit(text)

    def _on_listener_phase(self, worker, phase):
        if worker is self.listener and not worker.cancelled.is_set() and self.enabled and not self.muted and not self.reply_pending:
            self.phase.emit(phase)

    def _on_speaking(self, worker, talking):
        if worker is not self.speaker:
            return
        self.speaking.emit(talking)
        if self.enabled and not self.discard_reply:
            self.phase.emit('Speaking' if talking else ('Thinking' if self.reply_pending else 'Finishing reply'))

    def _listener_finished(self, worker):
        if self.listener is worker:
            self.listener = None
        worker.deleteLater()
        self._maybe_start_speaker()
        self._maybe_listen()
        if not self.enabled and self.speaker is None and self.retiring_speaker is None:
            self.idle.emit()

    def _speaker_finished(self, worker):
        if self.retiring_speaker is worker:
            self.retiring_speaker = None
        if self.speaker is worker:
            self.speaker = None
            self.speaker_started = False
        worker.deleteLater()
        self.speaking.emit(False)
        self._maybe_start_speaker()
        if not self.enabled and self.listener is None and self.retiring_speaker is None:
            self.idle.emit()
        # Give the speaker's last syllable time to fade before opening the mic.
        if self.enabled:
            self._restart_timer.start(250)

    def _worker_fault(self, worker, message):
        if not self.enabled or worker not in (self.listener, self.speaker):
            return
        cancelled = worker.cancelled if isinstance(worker, ListeningWorker) else worker.backend.cancelled
        if not cancelled.is_set():
            self._fault(message)

    def _fault(self, message):
        self.stop()
        self.error.emit(message)

    def shutdown(self):
        self.stop()
        # Keep Qt worker objects alive through native thread shutdown.
        workers = [w for w in (self.listener, self.speaker, self.retiring_speaker) if w is not None]
        results = [worker.wait(1000) for worker in workers]
        return all(results)
