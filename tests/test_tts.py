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


def test_spoken_reply_omits_citations_and_source_list():
    reply = 'The answer is forty-two [1, 2]. See [this guide](https://example.com).\n\n**Sources:**\n[1] Example publication\n[2] Another source'
    assert webagent._clean_tts_text(reply) == 'The answer is forty-two . See this guide.'


def test_tts_toggle_preserves_voice_chat(monkeypatch):
    monkeypatch.setattr(webagent, 'has_tts_backend', lambda: True)
    monkeypatch.setattr(webagent.context, 'voice_mode', True)
    monkeypatch.setattr(webagent.context, 'tts_mode', False)
    webagent._cmd_tts('/tts')
    assert webagent.context.voice_mode
    assert webagent.context.tts_mode
