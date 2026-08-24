"""Smoke test for /tarot (tarot.py:61-137). Declines the AI interpretation
step so the test never touches Ollama - tarot.py binds `assistant_convo` from
webagent at import time (a stale reference once webagent's global is later
reassigned elsewhere), which is a real latent bug logged in TODO.md Phase 1;
exercising the interpretation path isn't practical until that's fixed.
"""
import time

import tarot


def test_tarot_reading_declines_interpretation(monkeypatch, capsys):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    answers = iter(["What does the future hold?", "no"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    result = tarot.tarot_reading()

    assert result is None
    out = capsys.readouterr().out
    assert "What does the future hold?" in out
    assert "Tree of Life" in out
