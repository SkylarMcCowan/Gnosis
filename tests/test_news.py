"""Regression tests for /news (news_command, news.py:320-378).

news.py fetches real headline pages over the network via _refresh_headlines -
that boundary is mocked out (along with its on-disk cache) so this suite
never makes a real HTTP request.
"""
import news


def test_news_command_reports_no_match_without_prompting(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(news, "CACHE_FILE", str(tmp_path / "news_cache.json"))
    monkeypatch.setattr(news, "_refresh_headlines", lambda: [])

    news.news_command("a topic that will not match anything in an empty cache")

    assert "No headlines matched" in capsys.readouterr().out


def test_news_command_resolves_a_direct_url_argument(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(news, "CACHE_FILE", str(tmp_path / "news_cache.json"))
    monkeypatch.setattr(news, "_refresh_headlines", lambda: [])
    monkeypatch.setattr(news, "_format_article_detail", lambda url, title=None: print(f"DETAIL:{url}"))

    news.news_command("https://example.com/some-article")

    assert "DETAIL:https://example.com/some-article" in capsys.readouterr().out


def test_news_command_resolves_a_cached_item_by_number(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(news, "CACHE_FILE", str(tmp_path / "news_cache.json"))
    monkeypatch.setattr(news, "_refresh_headlines", lambda: [])
    monkeypatch.setattr(news, "_load_cache", lambda: {"timestamp": "2026-01-01T00:00:00Z", "items": [
        {"source": "BBC News", "source_url": "https://www.bbc.com/news",
         "title": "A sufficiently long headline title for validation purposes",
         "url": "https://www.bbc.com/news/article-1", "scraped_at": "2026-01-01T00:00:00Z"},
    ]})
    monkeypatch.setattr(news, "_format_article_detail", lambda url, title=None: print(f"DETAIL:{url}"))

    news.news_command("1")

    assert "DETAIL:https://www.bbc.com/news/article-1" in capsys.readouterr().out
