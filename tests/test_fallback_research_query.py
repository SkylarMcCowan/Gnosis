"""Regression tests for _resolve_correction_entity, _first_clean_line, and
_fallback_research_query (webagent.py:1009+) - the Phase 6 entity-resolution
fix. This is the deterministic-fallback path _research_action drops into
when the planner's own LLM call doesn't produce a usable action; it used to
search the user's raw correction text verbatim (or, at best, reuse the
previous question), with no attempt to resolve what the correction actually
refers to.

_first_clean_line's shape (first line only, label-stripping, a plausible
word-count window) came from tuning this live against all three local
models - see _resolve_correction_entity's docstring for the two designs
that didn't work before this one did: an "UNKNOWN" escape hatch the models
reached for far too readily, and a plain rewrite instruction whose replies
sometimes buried the real answer in a paragraph of rambling.
"""
import webagent


def test_resolve_correction_entity_returns_none_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(webagent, "ollama", None)
    assert webagent._resolve_correction_entity("no, it's the reluctant messenger") is None


def test_resolve_correction_entity_returns_the_resolved_query(fake_ollama_chat):
    fake_ollama_chat.reply = "Illusions The Adventures of a Reluctant Messiah Richard Bach"
    result = webagent._resolve_correction_entity("no, it's the reluctant messenger")
    assert result == "Illusions The Adventures of a Reluctant Messiah Richard Bach"


def test_first_clean_line_rejects_a_too_short_reply():
    """The actual failure mode found live: "no, Sinema isn't my senator
    anymore" once came back the single word "Yes" - not a query at all."""
    assert webagent._first_clean_line("Yes") is None
    assert webagent._first_clean_line("No.") is None


def test_first_clean_line_rejects_a_too_long_first_line():
    rambling = " ".join(["word"] * 25)
    assert webagent._first_clean_line(rambling) is None


def test_first_clean_line_accepts_a_plausible_query():
    line = "Norwegian Wood book by Haruki Murakami"
    assert webagent._first_clean_line(line) == line


def test_first_clean_line_only_considers_the_first_line():
    """Found live: models sometimes bury the real query inside a longer
    reply. Only the first line is ever trusted - if it's garbage, later
    lines (even a good one) don't rescue it."""
    raw = "Yes\nNorwegian Wood book by Haruki Murakami"
    assert webagent._first_clean_line(raw) is None


def test_first_clean_line_strips_a_leading_label():
    assert webagent._first_clean_line("Query: Norwegian Wood by Haruki Murakami") == "Norwegian Wood by Haruki Murakami"


def test_first_clean_line_strips_a_trailing_chat_template_token():
    """Real bug found live: small local models sometimes trail a stray
    chat-template token instead of stopping cleanly."""
    result = webagent._first_clean_line("norwegian wood book<|/im_start|>")
    assert result == "norwegian wood book"


def test_first_clean_line_strips_surrounding_quotes():
    assert webagent._first_clean_line('"Illusions Richard Bach book"') == "Illusions Richard Bach book"


def test_first_clean_line_returns_none_for_empty_input():
    assert webagent._first_clean_line("") is None
    assert webagent._first_clean_line("\n\n") is None


def test_fallback_query_leaves_a_non_correction_prompt_unchanged():
    query = webagent._fallback_research_query("who is the current mayor of Boston?", evidence=[])
    assert query == "who is the current mayor of Boston?"


def test_fallback_query_appends_official_source_when_evidence_exists():
    query = webagent._fallback_research_query("who is the current mayor of Boston?", evidence=[{"url": "x"}])
    assert query == "who is the current mayor of Boston? official source"


def test_fallback_query_uses_the_resolved_entity_when_available(monkeypatch):
    monkeypatch.setattr(
        webagent, "_resolve_correction_entity",
        lambda prompt: "Illusions: The Adventures of a Reluctant Messiah Richard Bach",
    )
    query = webagent._fallback_research_query("that's wrong, it's the reluctant messenger", evidence=[])
    assert query == "Illusions: The Adventures of a Reluctant Messiah Richard Bach"


def test_fallback_query_falls_back_to_last_question_when_resolution_fails(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_correction_entity", lambda prompt: None)
    webagent.context.assistant_convo = [
        webagent.sys_msgs.assistant_msg,
        {"role": "user", "content": "who is the current mayor of Boston?"},
        {"role": "assistant", "content": "Michelle Wu."},
    ]
    query = webagent._fallback_research_query("no, that's wrong", evidence=[])
    assert query == "who is the current mayor of Boston?"


def test_fallback_query_uses_raw_text_when_resolution_and_history_both_fail(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_correction_entity", lambda prompt: None)
    webagent.context.assistant_convo = [webagent.sys_msgs.assistant_msg]
    query = webagent._fallback_research_query("no, that's wrong", evidence=[])
    assert query == "no, that's wrong"
