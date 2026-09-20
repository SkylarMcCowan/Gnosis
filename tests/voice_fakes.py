"""Device-free workers for GUI voice lifecycle tests."""
import threading
from types import SimpleNamespace
from PyQt6.QtCore import QObject, pyqtSignal


class FakeListener(QObject):
    recognized = pyqtSignal(str, float)
    phase = pyqtSignal(str)
    level = pyqtSignal(float)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    def __init__(self, *args):
        super().__init__()
        self.args = args
        self.cancelled = threading.Event()
        self.started = False
    def start(self):
        self.started = True
    def cancel(self):
        self.cancelled.set()
    def wait(self, *args):
        return True


class FakeSpeaker(QObject):
    speaking = pyqtSignal(bool)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    def __init__(self, *args):
        super().__init__()
        self.items = []
        self.started = False
        self.backend = SimpleNamespace(cancelled=threading.Event())
    def enqueue(self, text):
        self.items.append(text)
    def start(self):
        self.started = True
    def finish_input(self):
        self.items.append(None)
    def cancel(self):
        self.backend.cancelled.set()
    def wait(self, *args):
        return True


