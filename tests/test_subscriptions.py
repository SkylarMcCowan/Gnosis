"""Regression tests for the subscriptions feature's webagent.py wiring:
_matching_subscription/_subscription_bypass/_subscribed_*_lookup, the new
_soccer_evidence_item(resolved_team=...) bypass, add_team_subscription/
add_topic_subscription/add_website_subscription, model_directed_web_research's
subscription-first ordering, and _flag_unsupported_live_lookup_claim's
subscription-aware scope.

See core/subscriptions.py's module docstring for why this exists: skip
inferring "does this need a live lookup, and about what" from raw prompt
text for anything the user already told Gnosis they follow.
"""
import pytest

import webagent
from core import subscriptions


class TestSoccerEvidenceItemResolvedTeamBypass:
    def test_resolved_team_skips_resolve_soccer_team_entirely(self, monkeypatch):
        monkeypatch.setattr(
            webagent, "_resolve_soccer_team",
            lambda name: (_ for _ in ()).throw(AssertionError("must not re-resolve when resolved_team is given")),
        )
        monkeypatch.setattr(
            webagent, "_fetch_soccer_team_matches",
            lambda team_id, league_slug: {
                "last_match": {
                    "date": "2026-08-22T11:30Z", "competition": "English Premier League", "status_description": "Full Time",
                    "home_name": "Hull City", "away_name": "Manchester United", "home_score": "2", "away_score": "0",
                },
                "next_match": None, "live_match": None,
            },
        )

        item = webagent._soccer_evidence_item(
            "Manchester United", resolved_team=("360", "Manchester United", "eng.1"),
        )

        assert item is not None
        assert "Hull City won 2-0 against Manchester United." in item["content"]

    def test_resolved_team_still_returns_none_when_the_fetch_finds_nothing(self, monkeypatch):
        monkeypatch.setattr(webagent, "_fetch_soccer_team_matches", lambda team_id, league_slug: None)
        assert webagent._soccer_evidence_item("X", resolved_team=("1", "X", "eng.1")) is None


class TestMatchingSubscription:
    def test_matches_by_name_case_insensitively(self, isolated_data_dir):
        subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})
        found = webagent._matching_subscription("who does manchester united play next")
        assert found is not None
        assert found["name"] == "Manchester United"

    def test_matches_by_keyword(self, isolated_data_dir):
        subscriptions.add_subscription("topic", "Formula 1", metadata={"keywords": ["F1"]})
        found = webagent._matching_subscription("how did the F1 race go")
        assert found is not None
        assert found["name"] == "Formula 1"

    def test_returns_none_when_nothing_matches(self, isolated_data_dir):
        subscriptions.add_subscription("team", "Manchester United")
        assert webagent._matching_subscription("what's the weather in Tucson?") is None

    def test_returns_none_when_there_are_no_subscriptions(self, isolated_data_dir):
        assert webagent._matching_subscription("anything at all") is None


class TestSubscribedTeamLookup:
    def test_builds_evidence_from_the_cached_team_id_and_league(self, isolated_data_dir, monkeypatch):
        subscription = subscriptions.add_subscription(
            "team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"},
        )
        captured = {}

        def fake_soccer_evidence_item(prompt, team_name=None, resolved_team=None):
            captured["resolved_team"] = resolved_team
            return {"title": "Live soccer results - Manchester United", "content": "..."}

        monkeypatch.setattr(webagent, "_soccer_evidence_item", fake_soccer_evidence_item)

        result = webagent._subscribed_team_lookup(subscription, "who do they play next?")

        assert captured["resolved_team"] == ("360", "Manchester United", "eng.1")
        assert result == [{"title": "Live soccer results - Manchester United", "content": "..."}]

    def test_returns_empty_list_when_the_lookup_finds_nothing(self, isolated_data_dir, monkeypatch):
        subscription = subscriptions.add_subscription(
            "team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"},
        )
        monkeypatch.setattr(webagent, "_soccer_evidence_item", lambda prompt, team_name=None, resolved_team=None: None)
        assert webagent._subscribed_team_lookup(subscription, "who do they play next?") == []

    def test_returns_empty_list_when_metadata_is_missing_the_team_id(self, isolated_data_dir):
        subscription = {"type": "team", "name": "Manchester United", "metadata": {}}
        assert webagent._subscribed_team_lookup(subscription, "who do they play next?") == []


class TestSubscribedTopicLookup:
    def test_runs_a_scoped_web_search_and_normalizes_the_results(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "topic", "name": "Formula 1", "metadata": {}}
        captured = {}

        def fake_execute(name, **kwargs):
            captured["name"], captured["query"] = name, kwargs.get("query")
            return [{"title": "F1 news", "url": "https://example.com/f1", "content": "Race results.", "search_provider": "searxng"}]

        monkeypatch.setattr(webagent.tool_registry, "execute", fake_execute)

        result = webagent._subscribed_topic_lookup(subscription, "what happened this weekend?")

        assert captured["name"] == "web.search"
        assert captured["query"] == "Formula 1 what happened this weekend?"
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/f1"

    def test_returns_empty_list_when_the_search_tool_raises(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "topic", "name": "Formula 1", "metadata": {}}

        def _raise(name, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(webagent.tool_registry, "execute", _raise)
        assert webagent._subscribed_topic_lookup(subscription, "anything") == []


class TestSubscribedWebsiteLookup:
    def test_builds_an_evidence_item_from_the_fetched_page(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "website", "name": "Man Utd Fixtures", "metadata": {"url": "https://www.manutd.com/fixtures"}}
        monkeypatch.setattr(webagent, "fetch_page_content", lambda url: "Manchester United's next match is vs Arsenal.")

        result = webagent._subscribed_website_lookup(subscription, "who do they play next?")

        assert len(result) == 1
        item = result[0]
        assert item["url"] == "https://www.manutd.com/fixtures"
        assert item["title"] == "Man Utd Fixtures"
        assert item["search_provider"] == "subscribed-website"
        assert "Arsenal" in item["content"]

    def test_returns_empty_list_when_fetch_fails(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "website", "name": "Man Utd Fixtures", "metadata": {"url": "https://www.manutd.com/fixtures"}}
        monkeypatch.setattr(webagent, "fetch_page_content", lambda url: None)
        assert webagent._subscribed_website_lookup(subscription, "anything") == []

    def test_returns_empty_list_when_metadata_has_no_url(self, isolated_data_dir):
        subscription = {"type": "website", "name": "Man Utd Fixtures", "metadata": {}}
        assert webagent._subscribed_website_lookup(subscription, "anything") == []


class TestSubscribedWeatherLookup:
    def test_builds_evidence_from_the_saved_location(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "weather", "name": "Tucson, Arizona, United States", "metadata": {"location": "Tucson, Arizona, United States"}}
        captured = {}

        def fake_weather_evidence_item(prompt, location=None):
            captured["location"] = location
            return {"title": "Live weather - Tucson", "content": "..."}

        monkeypatch.setattr(webagent, "_weather_evidence_item", fake_weather_evidence_item)

        result = webagent._subscribed_weather_lookup(subscription, "what's the weather like?")

        assert captured["location"] == "Tucson, Arizona, United States"
        assert result == [{"title": "Live weather - Tucson", "content": "..."}]

    def test_returns_empty_list_when_the_lookup_finds_nothing(self, isolated_data_dir, monkeypatch):
        subscription = {"type": "weather", "name": "Tucson", "metadata": {"location": "Tucson, Arizona, United States"}}
        monkeypatch.setattr(webagent, "_weather_evidence_item", lambda prompt, location=None: None)
        assert webagent._subscribed_weather_lookup(subscription, "what's the weather?") == []

    def test_returns_empty_list_when_metadata_has_no_location(self, isolated_data_dir):
        subscription = {"type": "weather", "name": "Tucson", "metadata": {}}
        assert webagent._subscribed_weather_lookup(subscription, "anything") == []


class TestAddWeatherSubscription:
    def test_resolves_and_persists_the_normalized_place_name(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(
            webagent, "fetch_current_weather",
            lambda location: {"place": "Tucson, Arizona, United States", "temp_f": 100},
        )

        record = webagent.add_weather_subscription("tucson")

        assert record["type"] == "weather"
        assert record["name"] == "Tucson, Arizona, United States"
        assert record["metadata"] == {"location": "Tucson, Arizona, United States"}
        assert subscriptions.list_subscriptions() == [record]

    def test_raises_when_the_location_cannot_be_geocoded(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: None)
        with pytest.raises(ValueError):
            webagent.add_weather_subscription("nowhere at all")
        assert subscriptions.list_subscriptions() == []


class TestSubscriptionBypass:
    def test_returns_empty_list_when_nothing_matches(self, isolated_data_dir):
        assert webagent._subscription_bypass("what's 2+2?") == []

    def test_dispatches_to_the_handler_for_the_subscriptions_type(self, isolated_data_dir, monkeypatch):
        subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})
        monkeypatch.setitem(webagent._SUBSCRIPTION_HANDLERS, "team", lambda subscription, prompt: [{"title": "found it"}])

        result = webagent._subscription_bypass("who does Manchester United play next?")

        assert result == [{"title": "found it"}]


class TestModelDirectedWebResearchSubscriptionOrdering:
    def test_subscription_bypass_is_tried_before_the_regex_bypass(self, isolated_data_dir, monkeypatch):
        webagent.context.deep_think_mode = False
        monkeypatch.setattr(webagent, "_subscription_bypass", lambda prompt: [{"title": "from subscription"}])

        def _fail_if_called(query_text):
            raise AssertionError("the regex bypass must not run once a subscription already produced evidence")

        monkeypatch.setattr(webagent, "_try_live_lookup_bypasses", _fail_if_called)

        evidence = webagent.model_directed_web_research("who does Manchester United play next?")

        assert evidence == [{"title": "from subscription"}]

    def test_falls_through_to_the_regex_bypass_when_no_subscription_matches(self, isolated_data_dir, monkeypatch):
        webagent.context.deep_think_mode = False
        monkeypatch.setattr(webagent, "_subscription_bypass", lambda prompt: [])
        monkeypatch.setattr(webagent, "_try_live_lookup_bypasses", lambda query_text: {"title": "from regex bypass"})

        evidence = webagent.model_directed_web_research("what's the weather in Tucson?")

        assert evidence == [{"title": "from regex bypass"}]

    def test_deep_think_mode_skips_the_subscription_bypass_too(self, isolated_data_dir, monkeypatch):
        webagent.context.deep_think_mode = True

        def _fail_if_called(prompt):
            raise AssertionError("Deep Think must skip the subscription bypass, same as the regex bypass")

        monkeypatch.setattr(webagent, "_subscription_bypass", _fail_if_called)
        monkeypatch.setattr(webagent, "_deep_think_research_plan", lambda prompt: [])
        monkeypatch.setattr(webagent, "_fallback_research_query", lambda prompt, evidence: "fallback query")
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: [])
        monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

        webagent.model_directed_web_research("who does Manchester United play next?")


class TestAddSubscriptionFunctions:
    def test_add_team_subscription_resolves_and_persists(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))

        record = webagent.add_team_subscription("Man United")

        assert record["type"] == "team"
        assert record["name"] == "Manchester United"
        assert record["metadata"] == {"team_id": "360", "league_slug": "eng.1", "sport": "soccer"}
        assert subscriptions.list_subscriptions() == [record]

    def test_add_team_subscription_raises_when_the_team_cannot_be_resolved(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: None)
        with pytest.raises(ValueError):
            webagent.add_team_subscription("Nonexistent FC")
        assert subscriptions.list_subscriptions() == []

    def test_add_topic_subscription_needs_no_resolution(self, isolated_data_dir):
        record = webagent.add_topic_subscription("Formula 1", keywords=["F1"])
        assert record["type"] == "topic"
        assert record["metadata"] == {"keywords": ["F1"]}

    def test_add_website_subscription_verifies_the_url_is_fetchable(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(webagent, "fetch_page_content", lambda url: "page text")

        record = webagent.add_website_subscription("Man Utd Fixtures", "https://www.manutd.com/fixtures")

        assert record["type"] == "website"
        assert record["metadata"] == {"url": "https://www.manutd.com/fixtures", "keywords": []}

    def test_add_website_subscription_raises_when_the_url_cannot_be_fetched(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(webagent, "fetch_page_content", lambda url: None)
        with pytest.raises(ValueError):
            webagent.add_website_subscription("Man Utd Fixtures", "https://www.manutd.com/fixtures")
        assert subscriptions.list_subscriptions() == []


class TestFlagUnsupportedLiveLookupClaimSubscriptionScope:
    def test_flags_a_claim_for_a_subscribed_team_with_zero_evidence(self, isolated_data_dir):
        subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})
        answer = "Manchester United's next scheduled game is against Southampton on September 5, 2026."

        flag = webagent._flag_unsupported_live_lookup_claim(answer, "who does Manchester United play next?")

        assert flag.startswith("[Unverified]")

    def test_does_not_flag_when_the_prompt_matches_no_subscription_and_no_regex_shape(self, isolated_data_dir):
        assert webagent._flag_unsupported_live_lookup_claim("Some answer.", "a question") == ""
