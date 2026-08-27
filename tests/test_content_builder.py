"""Tests for content_builder.py's pure-Python storage/prompt-building layer
(LinkedIn/Blog Builder pane) - no Qt involved, same split as worklog.py's
tests. core.config._root_override is redirected to a scratch dir by the
autouse isolated_data_dir fixture in conftest.py, so these never touch the
project's real content_builder/ directory.
"""
import pytest

import content_builder as cb


def test_load_data_on_missing_file_returns_defaults_without_creating_directory(tmp_path):
    data = cb.load_data()
    assert data["business_profile"] == cb.DEFAULT_BUSINESS_PROFILE
    assert data["target_audience"] == cb.DEFAULT_AUDIENCE
    assert data["default_cta"] == cb.DEFAULT_CTA
    assert data["avoid_phrases"] == cb.DEFAULT_AVOID_PHRASES
    assert data["style_examples"] == ""
    assert data["history"] == []
    assert not (tmp_path / "content_builder").exists()


def test_save_data_then_load_round_trips():
    data = cb.load_data()
    data["business_profile"] = "Custom profile."
    data["target_audience"] = "Freelance designers."
    cb.save_data(data)

    reloaded = cb.load_data()
    assert reloaded["business_profile"] == "Custom profile."
    assert reloaded["target_audience"] == "Freelance designers."


def test_load_data_backfills_missing_fields_on_older_saved_files():
    # simulate a file saved before target_audience/default_cta/etc existed
    cb.save_data({"business_profile": "Old profile.", "history": []})
    data = cb.load_data()
    assert data["business_profile"] == "Old profile."
    assert data["target_audience"] == cb.DEFAULT_AUDIENCE
    assert data["default_cta"] == cb.DEFAULT_CTA
    assert data["avoid_phrases"] == cb.DEFAULT_AVOID_PHRASES
    assert data["style_examples"] == ""


def _base_kwargs(**overrides):
    kwargs = dict(
        business_profile="LOZDEV builds websites.",
        post_type="linkedin",
        topic="managed hosting",
        tone="Professional",
    )
    kwargs.update(overrides)
    return kwargs


def test_build_messages_includes_business_profile_topic_and_tone():
    messages = cb.build_messages(**_base_kwargs())
    system, user = messages[0]["content"], messages[1]["content"]
    assert "LOZDEV builds websites." in system
    assert "Professional" in system
    assert "Topic: managed hosting" in user


def test_build_messages_omits_optional_sections_when_blank():
    messages = cb.build_messages(**_base_kwargs())
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Target audience:" not in system
    assert "Work this call to action" not in system
    assert "Never use these overused phrases" not in system
    assert "Match the voice" not in system
    assert "Target keyword/phrase:" not in system
    assert "Additional notes" not in user
    assert "write something meaningfully different" not in user


def test_build_messages_includes_audience_and_cta_when_provided():
    messages = cb.build_messages(**_base_kwargs(audience="Local retailers", cta="Call us today"))
    system = messages[0]["content"]
    assert "Target audience: Local retailers" in system
    assert "Call us today" in system


def test_build_messages_includes_angle_and_hook_instructions():
    messages = cb.build_messages(**_base_kwargs(angle="Common mistake", hook_style="Question"))
    system = messages[0]["content"]
    assert cb.CONTENT_ANGLES["Common mistake"] in system
    assert cb.HOOK_STYLES["Question"] in system


def test_build_messages_neutral_angle_and_hook_add_nothing():
    messages = cb.build_messages(**_base_kwargs(angle="Let the topic decide", hook_style="Let the model choose"))
    system = messages[0]["content"]
    assert cb.CONTENT_ANGLES["Educational tip"] not in system


def test_build_messages_avoid_phrases_are_cleaned_and_joined():
    messages = cb.build_messages(**_base_kwargs(avoid_phrases="unlock\nsynergy, seamless\n\n"))
    system = messages[0]["content"]
    assert "unlock, synergy, seamless" in system


def test_build_messages_style_examples_included_verbatim():
    messages = cb.build_messages(**_base_kwargs(style_examples="Here's a post I loved writing."))
    system = messages[0]["content"]
    assert "Here's a post I loved writing." in system
    assert "Match the voice" in system


def test_build_messages_seo_keyword_triggers_seo_instructions_for_post_type():
    linkedin_messages = cb.build_messages(**_base_kwargs(post_type="linkedin", seo_keyword="site hosting"))
    blog_messages = cb.build_messages(**_base_kwargs(post_type="blog", seo_keyword="site hosting"))
    assert cb.SEO_INSTRUCTIONS["linkedin"] in linkedin_messages[0]["content"]
    assert cb.SEO_INSTRUCTIONS["blog"] in blog_messages[0]["content"]
    assert "Target keyword/phrase: site hosting" in linkedin_messages[0]["content"]


def test_build_messages_avoid_repeating_appears_in_user_message():
    messages = cb.build_messages(**_base_kwargs(avoid_repeating="Yesterday's draft text."))
    user = messages[1]["content"]
    assert "write something meaningfully different" in user
    assert "Yesterday's draft text." in user


def test_build_polish_messages_targets_the_current_draft():
    messages = cb.build_polish_messages("LOZDEV builds websites.", "linkedin", "Current draft text.", "leverage\nsynergy")
    assert messages[1]["content"] == "Current draft text."
    system = messages[0]["content"]
    assert "editor" in system.lower()
    assert "Never use: leverage, synergy" in system


def test_add_history_entry_then_delete():
    entry = cb.add_history_entry("linkedin", "topic", "Professional", "content here")
    assert cb.load_data()["history"][0]["id"] == entry["id"]
    cb.delete_history_entry(entry["id"])
    assert cb.load_data()["history"] == []


def test_list_available_models_falls_back_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr("core.models.ollama", None)
    models = cb.list_available_models()
    assert models == list(dict.fromkeys(cb.MODELS.values()))


def test_list_available_models_falls_back_when_ollama_list_raises(monkeypatch):
    class BoomOllama:
        def list(self):
            raise RuntimeError("daemon unreachable")

    monkeypatch.setattr("core.models.ollama", BoomOllama())
    models = cb.list_available_models()
    assert models == list(dict.fromkeys(cb.MODELS.values()))


def test_list_available_models_parses_the_daemon_response(monkeypatch):
    class FakeOllama:
        def list(self):
            return {"models": [{"model": "llama3.1:8b"}, {"model": "yi:6b"}]}

    monkeypatch.setattr("core.models.ollama", FakeOllama())
    assert cb.list_available_models() == ["llama3.1:8b", "yi:6b"]
