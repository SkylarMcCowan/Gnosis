"""Regression tests for /ytdl (ytdl_command, webagent.py:4489-4541).

webagent.yt_dlp is replaced with a fake module so no real download or network
call ever happens.
"""
import webagent


class _FakeYDL:
    def __init__(self, calls, opts, fail_with=None):
        self.calls = calls
        self.opts = opts
        self.fail_with = fail_with

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls):
        self.calls.append({"opts": dict(self.opts), "urls": list(urls)})
        if self.fail_with:
            raise self.fail_with


def test_ytdl_command_requires_a_url(monkeypatch, capsys):
    monkeypatch.setattr(webagent, "yt_dlp", object())

    webagent.ytdl_command(None)

    assert "provide a YouTube URL" in capsys.readouterr().out


def test_ytdl_command_downloads_the_given_url(monkeypatch, capsys):
    calls = []

    class FakeModule:
        YoutubeDL = staticmethod(lambda opts: _FakeYDL(calls, opts))

    monkeypatch.setattr(webagent, "yt_dlp", FakeModule)

    webagent.ytdl_command("https://youtu.be/abc123")

    assert len(calls) == 1
    assert calls[0]["urls"] == ["https://youtu.be/abc123"]
    assert "Download completed" in capsys.readouterr().out


def test_ytdl_command_falls_back_on_bot_detection(monkeypatch, capsys):
    calls = []
    attempt = {"n": 0}

    def _make_ydl(opts):
        attempt["n"] += 1
        if attempt["n"] == 1:
            return _FakeYDL(calls, opts, fail_with=Exception("Sign in to confirm you're not a bot"))
        return _FakeYDL(calls, opts)

    class FakeModule:
        YoutubeDL = staticmethod(_make_ydl)

    monkeypatch.setattr(webagent, "yt_dlp", FakeModule)

    webagent.ytdl_command("https://youtu.be/abc123")

    out = capsys.readouterr().out
    assert "bot detection" in out
    assert len(calls) == 2
