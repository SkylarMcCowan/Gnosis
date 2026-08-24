"""Regression tests for /tts and /stopvoice (webagent.py:519-568).

stop_voice() shells out to real system commands (pkill afplay / taskkill /
pkill mpg123) and plays a real sound effect - those side effects are mocked
out here so running this suite never touches other audio on the machine.
"""
import webagent


def test_stop_tts_is_safe_with_no_active_engine():
    """No TTS in flight - must be a no-op, not an exception."""
    webagent.stop_tts()


def test_stop_voice_disables_voice_mode(monkeypatch):
    monkeypatch.setattr(webagent.context, "voice_mode", True)
    monkeypatch.setattr(webagent, "play_audio_effect", lambda effect_name: None)
    monkeypatch.setattr(webagent.os, "system", lambda cmd: 0)

    webagent.stop_voice()

    assert webagent.context.voice_mode is False
