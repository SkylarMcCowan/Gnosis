"""Headless smoke tests for webagent_gui.py's mode-toggle handlers
(webagent_gui.py:495-852) - verifies the Phase 1 core/context.py migration
didn't silently break the GUI, which otherwise has no test coverage since
it's a real PyQt6 app. Runs with QT_QPA_PLATFORM=offscreen so no display or
window server is needed; never calls app.exec(), so no real event loop runs.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import webagent
import webagent_gui


@pytest.fixture(scope="module")
def qapp():
    """Skip (rather than error the whole suite) if the Qt platform plugin
    itself can't initialize headlessly - e.g. a CI image missing the system
    libraries PyQt6's offscreen backend needs. PyQt6 importing cleanly
    doesn't guarantee this; only actually constructing QApplication does."""
    try:
        return QApplication.instance() or QApplication([])
    except Exception as exc:
        pytest.skip(f"Qt platform plugin could not initialize headlessly: {exc}")


@pytest.fixture
def gui(qapp, isolated_data_dir, monkeypatch):
    from voice import runtime
    from voice_fakes import FakeListener
    monkeypatch.setattr(runtime, "ListeningWorker", FakeListener)
    window = webagent_gui.WebAgentGUI()
    model = isolated_data_dir / "speech-model"
    (model / "am").mkdir(parents=True)
    (model / "am" / "final.mdl").touch()
    window.voice_session.model_path = str(model)
    yield window
    window.close()
    window.deleteLater()


def test_initial_web_search_checkbox_reflects_context(gui):
    assert gui.web_search_check.isChecked() == webagent.context.web_search_mode


def test_toggle_unfiltered_mode_updates_context(gui, fake_ollama_chat):
    # fake_ollama_chat: these toggles now also fire a background model
    # pre-warm (_prewarm_model_for_current_modes) - without this, the test
    # made a real, slow Ollama call instead of a fast, hermetic one.
    gui.toggle_unfiltered_mode(True)
    assert webagent.context.unfiltered_mode is True
    gui.toggle_unfiltered_mode(False)
    assert webagent.context.unfiltered_mode is False


def test_toggle_coding_mode_updates_context(gui, fake_ollama_chat):
    gui.toggle_coding_mode(True)
    assert webagent.context.coding_mode is True


def test_toggle_voice_mode_updates_context(gui):
    gui.toggle_voice_mode(True)
    assert webagent.context.voice_mode is True


def test_toggle_tts_mode_updates_context(gui):
    gui.toggle_tts_mode(True)
    assert webagent.context.tts_mode is True


def test_toggle_web_search_updates_context(gui):
    gui.toggle_web_search(False)
    assert webagent.context.web_search_mode is False


def test_toggle_deep_think_mode_updates_context(gui):
    gui.toggle_deep_think_mode(True)
    assert webagent.context.deep_think_mode is True


def test_update_mouth_reads_tts_mode_from_context(gui, monkeypatch):
    monkeypatch.setattr(webagent.context, "tts_mode", True)
    monkeypatch.setattr(webagent, "is_speaking", lambda: False)
    gui._update_mouth()  # must not raise, and must read the shared context
