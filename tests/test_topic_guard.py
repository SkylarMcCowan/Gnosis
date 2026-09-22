from core.topic_guard import candidate_matches_request, relevance_signals, topic_terms
import webagent


def test_topic_terms_remove_request_scaffolding():
    assert topic_terms("give me a list of 100 books to read before i die") == {"100"}


def test_relevance_signals_explain_topic_overlap():
    signals = relevance_signals("what is the population of America?", "America population estimate")

    assert signals["overlap"] == ["america", "population"]
    assert signals["introduced"] == ["estimate"]
    assert signals["aligned"] is True


def test_unrelated_candidate_is_rejected():
    assert not candidate_matches_request(
        "give me a list of 100 books to read before i die",
        "Biosphere 3 history",
    )


def test_corrected_name_is_not_rejected_as_off_topic():
    assert candidate_matches_request('Alister Crawley', 'Aleister Crowley residence')
    assert candidate_matches_request('Aleister Crowley', 'Alister Crawley residence')
    assert not candidate_matches_request('Golden Dawn', 'Windows help')


def test_broad_request_does_not_fail_closed():
    assert candidate_matches_request("tell me something interesting", "interesting facts")


def test_review_draft_keeps_a_valid_on_topic_answer(fake_ollama_chat):
    fake_ollama_chat.reply = '{"on_topic": true, "format_satisfied": true, "reason": "direct", "revised_answer": "ignored"}'
    draft = "Here are 100 books across fiction, history, and science."

    assert webagent.review_draft_topic("Give me 100 books to read", draft) == draft


def test_review_draft_uses_a_non_empty_revision_for_drift(fake_ollama_chat):
    fake_ollama_chat.reply = '{"on_topic": false, "format_satisfied": false, "reason": "wrong subject", "revised_answer": "Here are 100 books to read."}'

    assert webagent.review_draft_topic("Give me 100 books to read", "Biosphere 3 was an experiment.") == "Here are 100 books to read."


def test_review_draft_preserves_answer_when_reviewer_is_malformed(fake_ollama_chat):
    fake_ollama_chat.reply = "not json"
    draft = "A useful answer."

    assert webagent.review_draft_topic("Explain the topic", draft) == draft


def test_review_draft_preserves_answer_when_ollama_is_unavailable(monkeypatch):
    monkeypatch.setattr(webagent, "ollama", None)
    draft = "A useful answer."

    assert webagent.review_draft_topic("Explain the topic", draft) == draft
