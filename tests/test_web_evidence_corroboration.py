"""Regression tests for apply_corroboration/_extract_fact_tokens
(webagent.py) - the Phase 6 "same-entity across searches" fix.

The bug: corroboration used to fire whenever two sources shared any
proper-noun phrase or number, including the query's own subject name -
which every result for that query mentions regardless of what it actually
says. Two sources about a *different* book/person that merely shares a
title/name with the query would "corroborate" each other on that basis
alone. The fix excludes each item's own query-derived tokens before
comparing, so corroboration now requires an *additional* shared fact
(author, date, number) beyond the query subject itself.
"""
import webagent


def _evidence(url, query, content):
    return {
        "url": url,
        "query": query,
        "content": content,
        "source_quality_confidence": 50,
        "truthfulness_confidence": 50,
    }


def test_extract_fact_tokens_finds_numbers_and_entity_phrases():
    tokens = webagent._extract_fact_tokens("Richard Bach wrote it in 1977, selling 1,200,000 copies.")
    assert "richard bach" in tokens
    assert "1977" in tokens
    assert "1,200,000" in tokens


def test_extract_fact_tokens_ignores_short_numbers():
    assert webagent._extract_fact_tokens("chapter 12") == set()


def test_corroboration_does_not_fire_on_the_query_subject_alone():
    """Both sources only ever mention the query's own title - no other
    shared fact - so they must not corroborate each other."""
    evidence = [
        _evidence("https://a.example.com", "The Reluctant Messenger",
                  "The Reluctant Messenger is a short book."),
        _evidence("https://b.example.com", "The Reluctant Messenger",
                  "The Reluctant Messenger appears on this reading list."),
    ]
    result = webagent.apply_corroboration(evidence)
    assert result[0]["corroborating_domains"] == []
    assert result[1]["corroborating_domains"] == []


def test_different_entities_sharing_a_title_do_not_corroborate():
    """The actual bug scenario: two different books that happen to share a
    title, distinguished by their real, non-overlapping details (author)."""
    evidence = [
        _evidence("https://a.example.com", "The Reluctant Messenger",
                  "The Reluctant Messenger, by Richard Bach, is about a pilot."),
        _evidence("https://b.example.com", "The Reluctant Messenger",
                  "The Reluctant Messenger, by Jane Smith, is a self-help guide."),
    ]
    result = webagent.apply_corroboration(evidence)
    assert result[0]["corroborating_domains"] == []
    assert result[1]["corroborating_domains"] == []


def test_corroboration_fires_on_a_fact_shared_beyond_the_query_subject():
    evidence = [
        _evidence("https://a.example.com", "The Reluctant Messenger",
                  "The Reluctant Messenger was written by Richard Bach."),
        _evidence("https://b.example.com", "The Reluctant Messenger",
                  "Richard Bach's The Reluctant Messenger remains popular."),
    ]
    result = webagent.apply_corroboration(evidence)
    assert result[0]["corroborating_domains"] == ["b.example.com"]
    assert result[1]["corroborating_domains"] == ["a.example.com"]
    assert result[0]["truthfulness_confidence"] > 50 * 0.4  # corroboration actually raised the score


def test_same_hostname_never_corroborates_itself():
    evidence = [
        _evidence("https://a.example.com/1", "The Reluctant Messenger",
                  "The Reluctant Messenger was written by Richard Bach."),
        _evidence("https://a.example.com/2", "The Reluctant Messenger",
                  "Richard Bach's The Reluctant Messenger remains popular."),
    ]
    result = webagent.apply_corroboration(evidence)
    assert result[0]["corroborating_domains"] == []
    assert result[1]["corroborating_domains"] == []
