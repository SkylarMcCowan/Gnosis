"""Regression tests for get_relevant_user_context/_profile_field_is_relevant
(webagent.py, Phase 4) - the fix for get_user_context() always concatenating
the user's full profile (every interest, preference, note) into every
prompt regardless of topic, forcing unrelated context ("software
development," "meditation") into off-topic replies. See TODO.md Phase 4.
"""
import webagent


def _profile(**overrides):
    base = {
        "name": "User", "location": "", "persona": "",
        "preferences": [], "interests": [], "recent_explorations": [], "notes": "",
    }
    base.update(overrides)
    return base


def test_field_is_relevant_when_a_significant_word_overlaps():
    assert webagent._profile_field_is_relevant("meditation", "tell me about meditation techniques") is True


def test_field_is_not_relevant_with_no_word_overlap():
    assert webagent._profile_field_is_relevant("meditation", "what is 2 plus 2?") is False


def test_field_relevance_ignores_short_words():
    """"the" overlapping with a profile field shouldn't count as relevant -
    only words longer than 3 characters are considered significant."""
    assert webagent._profile_field_is_relevant("the sea", "what is the capital of France?") is False


def test_identity_fields_are_always_included(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        name="Skylar", location="Seattle", persona="cheery",
    ))
    result = webagent.get_relevant_user_context("what is 2 plus 2?")
    assert "User's name: Skylar" in result
    assert "Location: Seattle" in result
    assert "Persona: cheery" in result


def test_off_topic_interest_is_excluded(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation", "software development"],
    ))
    result = webagent.get_relevant_user_context("what is 2 plus 2?")
    assert "meditation" not in result
    assert "software development" not in result


def test_on_topic_interest_is_included(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation", "software development"],
    ))
    result = webagent.get_relevant_user_context("can you recommend a meditation routine?")
    assert "Interests: meditation" in result
    assert "software development" not in result


def test_on_topic_preference_and_note_are_included(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        preferences=["concise answers"],
        notes="Working through a Python refactor.",
    ))
    result = webagent.get_relevant_user_context("can you review my python code?")
    assert "Preferences: concise answers" not in result  # "concise answers" shares no word with the prompt
    assert "Additional notes: Working through a Python refactor." in result


def test_returns_no_profile_information_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation"], notes="Learning Spanish.",
    ))
    result = webagent.get_relevant_user_context("what is 2 plus 2?")
    assert result == "No user profile information available"


def test_chat_response_uses_relevant_context_not_the_full_profile(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = False
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation"],
    ))

    webagent.chat_response("what is 2 plus 2?")

    system_messages = " ".join(
        m["content"] for m in webagent.context.assistant_convo if m["role"] == "system"
    )
    assert "meditation" not in system_messages


def test_handle_unmatched_prompt_uses_relevant_context_not_the_full_profile(isolated_data_dir, fake_ollama_chat, monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation"],
    ))
    monkeypatch.setattr(webagent, "stream_response", lambda: "a real answer")

    webagent._handle_unmatched_prompt("what is 2 plus 2?")

    system_messages = " ".join(
        m["content"] for m in webagent.context.assistant_convo if m["role"] == "system"
    )
    assert "meditation" not in system_messages


def test_enhance_conversation_with_search_uses_relevant_context(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: _profile(
        interests=["meditation"],
    ))
    enhanced = webagent.enhance_conversation_with_search("what is 2 plus 2?", [])
    assert "meditation" not in enhanced

    enhanced_on_topic = webagent.enhance_conversation_with_search("tell me about meditation", [])
    assert "meditation" in enhanced_on_topic
