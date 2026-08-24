"""Regression tests for fact_check_answer (webagent.py:2180), the Phase 6
accuracy fix: corroboration must now also require the sources to be about
the entity the user actually asked about, not just agreement with each
other. See TODO.md Phase 6's "Concrete accuracy/hallucination bugs".
"""
import json
import os

import webagent


def _saved_fact_check_records(isolated_data_dir):
    fact_check_dir = os.path.join(isolated_data_dir, "knowledge_base", "fact_checks")
    if not os.path.isdir(fact_check_dir):
        return []
    records = []
    for filename in os.listdir(fact_check_dir):
        with open(os.path.join(fact_check_dir, filename), encoding="utf-8") as handle:
            records.append(json.load(handle))
    return records


def test_returns_empty_string_with_no_evidence(fake_ollama_chat):
    assert webagent.fact_check_answer("Some answer.", [], user_prompt="a question") == ""
    assert fake_ollama_chat.calls == []


def test_returns_empty_string_with_blank_answer(fake_ollama_chat):
    evidence = [{"url": "https://example.com", "content": "..."}]
    assert webagent.fact_check_answer("   ", evidence, user_prompt="a question") == ""
    assert fake_ollama_chat.calls == []


def test_returns_empty_string_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(webagent, "ollama", None)
    evidence = [{"url": "https://example.com", "content": "..."}]
    assert webagent.fact_check_answer("Some answer.", evidence, user_prompt="a question") == ""


def test_returns_empty_string_when_model_reports_no_claims(fake_ollama_chat):
    fake_ollama_chat.reply = "No factual claims to check."
    evidence = [{"url": "https://example.com", "content": "..."}]
    assert webagent.fact_check_answer("Just an opinion.", evidence, user_prompt="what do you think?") == ""


def test_forwards_user_prompt_into_the_checker_prompt_so_it_can_catch_wrong_entities(fake_ollama_chat):
    """The actual bug: without the user's request in view, the checker could
    only see whether sources agreed with each other, not whether they were
    about the right book/person. Confirms the fix's whole mechanism - the
    user's correction reaching the model - is wired up."""
    evidence = [
        {"url": "https://a.example.com", "content": "The Reluctant Messenger is a 1990s self-help book."},
        {"url": "https://b.example.com", "content": "The Reluctant Messenger, a different unrelated book."},
    ]
    webagent.fact_check_answer(
        "The Reluctant Messenger was written in the 1990s.",
        evidence,
        user_prompt="Actually I meant Illusions: The Adventures of a Reluctant Messiah by Richard Bach",
    )

    assert len(fake_ollama_chat.calls) == 1
    sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
    assert "Illusions: The Adventures of a Reluctant Messiah by Richard Bach" in sent_prompt
    assert "Wrong entity" in sent_prompt


def test_checker_prompt_instructs_flagging_unverified_titles(fake_ollama_chat):
    """Phase 6's titles/authors sanity check: the checker prompt must
    explicitly instruct flagging a named work/author with no source behind
    it at all, distinct from the general [Unverified] bucket."""
    evidence = [{"url": "https://a.example.com", "content": "Illusions by Richard Bach, 1977."}]
    webagent.fact_check_answer("Illusions was written by Richard Bach.", evidence, user_prompt="q")

    sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
    assert "Unverified title" in sent_prompt
    assert "zero sources means [Unverified title]" in sent_prompt


def test_returns_the_model_reply_when_it_has_real_findings(fake_ollama_chat):
    fake_ollama_chat.reply = "- The book was published in 1990s. [Wrong entity]"
    evidence = [{"url": "https://example.com", "content": "..."}]

    result = webagent.fact_check_answer("The book was published in the 1990s.", evidence, user_prompt="when was it published?")

    assert result == fake_ollama_chat.reply


def test_save_fact_check_record_returns_none_for_empty_text(isolated_data_dir):
    assert webagent.save_fact_check_record("q", "answer", "", []) is None
    assert _saved_fact_check_records(isolated_data_dir) == []


def test_save_fact_check_record_writes_the_expected_fields(isolated_data_dir):
    evidence = [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}, {"no_url": True}]
    record = webagent.save_fact_check_record("q", "answer text", "[Corroborated] a claim.", evidence)

    assert record["query"] == "q"
    assert record["answer_text"] == "answer text"
    assert record["fact_check"] == "[Corroborated] a claim."
    assert record["evidence_urls"] == ["https://example.com/a", "https://example.com/b"]

    saved = _saved_fact_check_records(isolated_data_dir)
    assert saved == [record]


def test_chat_response_persists_fact_check_instead_of_displaying_it(isolated_data_dir, fake_ollama_chat, monkeypatch):
    """The fact-check text used to be appended directly onto the displayed
    answer and folded into conversation history. Two problems: it made a
    normal reply read like a research report, and a few turns into a
    session the model started imitating that "---\n**Fact-check**\n[Tag]
    ..." formatting inside its own drafted answers (even inventing its own
    "**Correction**" section), because it was reading its past output with
    fact-check text attached as if that were normal assistant speech. The
    fix: fact-check results are persisted to disk as historical/audit data
    (save_fact_check_record) and never shown to the user or fed back into
    context.assistant_convo.
    """
    webagent.context.web_search_mode = True
    monkeypatch.setattr(
        webagent, "model_directed_web_research",
        lambda prompt: [{"url": "https://example.com", "content": "..."}],
    )
    monkeypatch.setattr(webagent, "fact_check_answer", lambda answer, evidence, user_prompt="": "[Corroborated] a claim.")
    fake_ollama_chat.reply = "A drafted answer."

    result = webagent.chat_response("what is the overview effect?")

    assert result == "A drafted answer."
    assert "Fact-check" not in result
    stored = webagent.context.assistant_convo[-1]
    assert stored["role"] == "assistant"
    assert stored["content"] == "A drafted answer."

    records = _saved_fact_check_records(isolated_data_dir)
    assert len(records) == 1
    assert records[0]["fact_check"] == "[Corroborated] a claim."
    assert records[0]["query"] == "what is the overview effect?"
    assert records[0]["answer_text"] == "A drafted answer."


def test_unmatched_prompt_handler_persists_fact_check_instead_of_displaying_it(isolated_data_dir, fake_ollama_chat, monkeypatch):
    """Same bug, same fix, in the CLI's _handle_unmatched_prompt path - it
    used to print the fact-check text straight to the terminal and never
    touched context.assistant_convo for it (already correct there); now it
    persists via save_fact_check_record instead of printing at all."""
    webagent.context.web_search_mode = True
    monkeypatch.setattr(
        webagent, "model_directed_web_research",
        lambda prompt: [{"url": "https://example.com", "content": "..."}],
    )
    monkeypatch.setattr(webagent, "fact_check_answer", lambda answer, evidence, user_prompt="": "[Corroborated] a claim.")
    monkeypatch.setattr(webagent, "stream_response", lambda: (
        webagent.context.assistant_convo.append({"role": "assistant", "content": "A drafted answer."}),
        "A drafted answer.",
    )[1])

    webagent._handle_unmatched_prompt("what is the overview effect?")

    stored = webagent.context.assistant_convo[-1]
    assert stored["role"] == "assistant"
    assert stored["content"] == "A drafted answer."

    records = _saved_fact_check_records(isolated_data_dir)
    assert len(records) == 1
    assert records[0]["fact_check"] == "[Corroborated] a claim."
    assert records[0]["query"] == "what is the overview effect?"


def test_chat_response_forwards_the_users_prompt_to_fact_check(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = True
    monkeypatch.setattr(
        webagent, "model_directed_web_research",
        lambda prompt: [{"url": "https://example.com", "content": "..."}],
    )
    calls = []
    monkeypatch.setattr(
        webagent, "fact_check_answer",
        lambda answer, evidence, user_prompt="": calls.append(user_prompt) or "",
    )

    webagent.chat_response("what is the overview effect?")

    assert calls == ["what is the overview effect?"]


def test_unmatched_prompt_handler_forwards_the_users_prompt_to_fact_check(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = True
    monkeypatch.setattr(
        webagent, "model_directed_web_research",
        lambda prompt: [{"url": "https://example.com", "content": "..."}],
    )
    calls = []
    monkeypatch.setattr(
        webagent, "fact_check_answer",
        lambda answer, evidence, user_prompt="": calls.append(user_prompt) or "",
    )
    monkeypatch.setattr(webagent, "stream_response", lambda: "a real answer")

    webagent._handle_unmatched_prompt("what is the overview effect?")

    assert calls == ["what is the overview effect?"]


class TestFlagUnverifiedDollarFigures:
    """Regression tests for the deterministic dollar-figure check bolted onto
    fact_check_answer's output. Real bug: asked for Microsoft's stock price,
    every evidence item saved by an actual SearxNG search was a page's static
    meta description with zero digits in it at all (Google/Yahoo/
    stockanalysis all render the live price client-side with JS). The model
    still answered "$308.67" and attributed it to Yahoo Finance.

    An LLM-based tag for this ([Unverified figure], mirroring [Unverified
    title]) was tried first and rejected: live-tested against yi:6b with
    this exact evidence/answer pair, it tagged the identical "$308.67"
    figure both [Corroborated] and [Unverified figure] in adjacent bullets
    of the same response. Exact substring/number matching is done in plain
    code instead, appended to whatever the LLM pass returns.
    """

    def test_flags_a_price_absent_from_every_evidence_item(self):
        evidence = [
            {"content": "Find the latest Microsoft Corporation (MSFT) stock quote, history, news."},
            {"content": "Get real-time stock quotes, news, financial details for Microsoft Corp."},
        ]
        flags = webagent._flag_unverified_dollar_figures(
            "The closing stock price for MSFT was around $308.67, per Yahoo Finance.", evidence,
        )
        assert len(flags) == 1
        assert "$308.67" in flags[0]
        assert flags[0].startswith("[Unverified figure]")

    def test_does_not_flag_a_price_present_in_evidence_without_a_dollar_sign(self):
        """The live-quote evidence item (_stock_evidence_item) writes prices
        as "487.31 USD", no "$" - this must not be treated as unsupported."""
        evidence = [{"content": "Live quote for Microsoft Corporation (MSFT): 487.31 USD (previous close 483.24 USD)."}]
        flags = webagent._flag_unverified_dollar_figures("Microsoft (MSFT) is currently trading at $487.31.", evidence)
        assert flags == []

    def test_does_not_flag_a_price_rounded_from_an_evidence_figure(self):
        """A model saying "$487" when evidence says "487.31" is reformatting
        a real figure, not fabricating one."""
        evidence = [{"content": "Live quote for MSFT: 487.31 USD."}]
        flags = webagent._flag_unverified_dollar_figures("MSFT is trading around $487 today.", evidence)
        assert flags == []

    def test_does_not_flag_when_the_answer_has_no_dollar_figures(self):
        evidence = [{"content": "Some unrelated evidence with no prices at all."}]
        assert webagent._flag_unverified_dollar_figures("I couldn't find a live price.", evidence) == []

    def test_fact_check_answer_appends_the_deterministic_flag_to_the_model_reply(self, fake_ollama_chat):
        fake_ollama_chat.reply = "- MSFT is at $308.67. [Corroborated]"
        evidence = [{"url": "https://finance.yahoo.com/quote/MSFT/", "content": "Find the latest MSFT stock quote."}]

        result = webagent.fact_check_answer(
            "The closing stock price for MSFT was around $308.67.", evidence, user_prompt="stock price of MSFT?",
        )

        assert "[Corroborated]" in result
        assert "[Unverified figure] $308.67 does not appear in any evidence source" in result

    def test_fact_check_answer_returns_just_the_flag_when_the_model_finds_no_claims(self, fake_ollama_chat):
        fake_ollama_chat.reply = "No factual claims to check."
        evidence = [{"url": "https://finance.yahoo.com/quote/MSFT/", "content": "Find the latest MSFT stock quote."}]

        result = webagent.fact_check_answer(
            "The closing stock price for MSFT was around $308.67.", evidence, user_prompt="stock price of MSFT?",
        )

        assert result == "[Unverified figure] $308.67 does not appear in any evidence source and may be fabricated."
