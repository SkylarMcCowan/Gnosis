"""Regression tests for the live-soccer-result short-circuit
(_fetch_soccer_team_matches/_soccer_evidence_item, wired into
model_directed_web_research) - the same fix as _weather_evidence_item and
_stock_evidence_item for the same underlying problem: a live score page
(ESPN, BBC Sport, etc.) renders the actual score client-side with JS, so a
plain scrape of it has no score in it at all, and a small local model fills
that gap by inventing one. Built for a Premier League/UEFA fan following
Manchester United - confirmed live against ESPN's real, keyless API before
writing this test suite.

All network calls here are mocked (webagent.requests.get) - this suite must
never make a real HTTP request. Live verification against the real ESPN
endpoints (team search, team schedule) was done manually, not as part of
this automated suite.
"""
import webagent


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise webagent.requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


TEAM_SEARCH_PAYLOAD = {
    "results": [
        {
            "type": "team",
            "contents": [
                {
                    "type": "team", "sport": "soccer", "displayName": "Manchester United",
                    "uid": "s:600~t:360", "defaultLeagueSlug": "eng.1",
                },
                {
                    "type": "team", "sport": "soccer", "displayName": "Manchester United",
                    "uid": "s:600~t:20061", "defaultLeagueSlug": "eng.w.1",
                },
            ],
        },
    ],
}


def _competitor(name, home_away, score=None):
    entry = {"team": {"displayName": name}, "homeAway": home_away}
    if score is not None:
        entry["score"] = score
    return entry


def _event(date, state, description, home, away):
    return {
        "date": date,
        "league": {"name": "English Premier League"},
        "competitions": [{
            "status": {"type": {"state": state, "description": description}},
            "competitors": [home, away],
        }],
    }


COMPLETED_MATCH_EVENT = _event(
    "2026-08-22T11:30Z", "post", "Full Time",
    _competitor("Hull City", "home", {"displayValue": "2"}),
    _competitor("Manchester United", "away", {"displayValue": "0"}),
)
UPCOMING_MATCH_EVENT = _event(
    "2026-08-28T19:00Z", "pre", "Scheduled",
    _competitor("Manchester United", "home", 0),
    _competitor("Arsenal", "away", 0),
)


def _fake_get(sequence):
    calls = iter(sequence)

    def fake(url, params=None, timeout=None):
        return next(calls)
    return fake


def test_looks_like_soccer_query_matches_common_phrasings():
    assert webagent._looks_like_soccer_query("how did Man United do today?")
    assert webagent._looks_like_soccer_query("did Man United win?")
    assert webagent._looks_like_soccer_query("did Manchester United beat Arsenal?")
    assert webagent._looks_like_soccer_query("what was the score of the Man United game?")
    assert webagent._looks_like_soccer_query("when is Man United's next match?")
    assert webagent._looks_like_soccer_query("Man United score")
    assert webagent._looks_like_soccer_query("Man United result")
    assert not webagent._looks_like_soccer_query("who wrote Illusions by Richard Bach")
    assert not webagent._looks_like_soccer_query("what's the weather in mobile alabama?")


def test_soccer_query_subject_handles_both_word_orders_and_sentence_shapes():
    assert webagent._soccer_query_subject("how did Man United do today?") == "Man United"
    assert webagent._soccer_query_subject("did Man United win?") == "Man United"
    assert webagent._soccer_query_subject("did Manchester United beat Arsenal?") == "Manchester United"
    assert webagent._soccer_query_subject("what was the score of the Man United game?") == "Man United"
    assert webagent._soccer_query_subject("what's the score of Man United") == "Man United"
    assert webagent._soccer_query_subject("when is Man United's next match?") == "Man United"
    assert webagent._soccer_query_subject("when does Man United play next?") == "Man United"
    assert webagent._soccer_query_subject("Man United score") == "Man United"
    assert webagent._soccer_query_subject("Man United result") == "Man United"


def test_looks_like_soccer_query_and_subject_handle_fixture_phrasing():
    """Real, live-reported bug: "what was the last fixture for Man United?"
    matched none of the existing patterns (not "how was", not "what
    happened", not "when is") and fell through with zero evidence at all -
    the model answered with a fully invented opponent, score, date, and
    starting lineup. A second, closely related test guards against the fix
    itself over-matching and swallowing a sentence _SOCCER_SCORE_OF_PATTERN
    should handle (a real regression caught while fixing this)."""
    assert webagent._looks_like_soccer_query("what was the last fixture for Man United?")
    assert webagent._soccer_query_subject("what was the last fixture for Man United?") == "Man United"
    assert webagent._soccer_query_subject("what is Man United's next fixture?") == "Man United"
    assert webagent._soccer_query_subject("what was Man United's last fixture?") == "Man United"
    assert webagent._soccer_query_subject("what were the fixtures for Man United?") == "Man United"
    # Must not regress the "score of" shape by over-matching in the new,
    # more permissive possessive pattern.
    assert webagent._soccer_query_subject("what was the score of the Man United game?") == "Man United"


def test_looks_like_soccer_query_and_subject_handle_who_do_they_play_phrasing():
    """Real, live-reported bug: "who does mancester united play next" (a
    natural way to ask for the OPPONENT rather than a date) matched none of
    the existing patterns - not even the "when ..." ones, since it has no
    "when" at all - and fell through to the model-driven selector with no
    free bypass available. The small model then both failed to parse its
    own JSON and, on retry, wrongly refused the query as "outside scope",
    leaving zero evidence; the chat step answered with a fully invented
    opponent and date (Southampton, September 5, 2026)."""
    assert webagent._looks_like_soccer_query("who does Man United play next?")
    assert webagent._soccer_query_subject("who does Man United play next?") == "Man United"
    assert webagent._soccer_query_subject("who do Man United play next?") == "Man United"
    assert webagent._soccer_query_subject("who is Man United playing next?") == "Man United"
    assert webagent._soccer_query_subject("who are Man United playing?") == "Man United"


def test_soccer_query_subject_strips_a_leading_last_next_recent_modifier():
    """Real, live-reported bug: "how was the last man united match?" put
    "last" BEFORE the team name (the common English word order), but the
    pattern only stripped "last"/"next"/"recent" when it appeared AFTER the
    subject ("man united's last match"). The lazy capture group swallowed
    "the last" as if it were part of the team name, ESPN's team search
    found nothing for "the last man united", and the query silently fell
    through to zero evidence - producing a fully fabricated match from a
    different year with invented players and a wrong score."""
    assert webagent._soccer_query_subject("how was the last man united match?") == "man united"
    assert webagent._soccer_query_subject("what happened in the last man united match") == "man united"
    assert webagent._soccer_query_subject("what was the last man united fixture?") == "man united"
    # The "subject before the modifier" shape must still work too.
    assert webagent._soccer_query_subject("how was man utd last match?") == "man utd"


def test_resolve_soccer_team_parses_a_real_shaped_response_and_prefers_the_mens_team(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse(TEAM_SEARCH_PAYLOAD)]))
    assert webagent._resolve_soccer_team("Man United") == ("360", "Manchester United", "eng.1")


def test_resolve_soccer_team_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({"results": []})]))
    assert webagent._resolve_soccer_team("Nonexistent FC") is None


def test_fetch_soccer_team_matches_parses_a_completed_match(monkeypatch):
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([
            FakeResponse({"events": [COMPLETED_MATCH_EVENT]}), FakeResponse({"events": []}), FakeResponse({"events": []}),
            # No next_match came out of the schedule loop, so
            # _fetch_next_scheduled_match falls back to the team-summary
            # endpoint for each league slug - none of them have a
            # nextEvent either, so next_match stays genuinely None.
            FakeResponse({"team": {}}), FakeResponse({"team": {}}), FakeResponse({"team": {}}),
        ]),
    )
    matches = webagent._fetch_soccer_team_matches("360", "eng.1")
    assert matches["last_match"]["home_name"] == "Hull City"
    assert matches["last_match"]["home_score"] == "2"
    assert matches["last_match"]["away_score"] == "0"
    assert matches["next_match"] is None


def test_fetch_soccer_team_matches_does_not_show_a_score_for_an_unplayed_fixture(monkeypatch):
    """Real ESPN quirk: an unplayed ('pre') fixture's competitor sometimes
    carries a bare 0 as "score", which would read as a real 0-0 result if
    shown - it must be suppressed until the match has actually started."""
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([FakeResponse({"events": [UPCOMING_MATCH_EVENT]}), FakeResponse({"events": []}), FakeResponse({"events": []})]),
    )
    matches = webagent._fetch_soccer_team_matches("360", "eng.1")
    assert matches["next_match"]["home_name"] == "Manchester United"
    assert matches["next_match"]["home_score"] is None
    assert matches["next_match"]["away_score"] is None
    assert matches["last_match"] is None


def test_fetch_soccer_team_matches_checks_uefa_competitions_too(monkeypatch):
    """A team resolved through its domestic league (eng.1) can still have a
    Champions/Europa League fixture - the schedule fetch must check those
    competitions too, not just the team's home league."""
    uefa_event = _event(
        "2026-09-17T19:00Z", "post", "Full Time",
        _competitor("Manchester United", "home", {"displayValue": "3"}),
        _competitor("Bayern Munich", "away", {"displayValue": "1"}),
    )
    uefa_event["league"] = {"name": "UEFA Champions League"}
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([
            FakeResponse({"events": [COMPLETED_MATCH_EVENT]}),  # eng.1
            FakeResponse({"events": [uefa_event]}),              # uefa.champions
            FakeResponse({"events": []}),                        # uefa.europa
            # No next_match came out of the schedule loop (both events are
            # "post"), so _fetch_next_scheduled_match falls back to the
            # team-summary endpoint for each league slug.
            FakeResponse({"team": {}}), FakeResponse({"team": {}}), FakeResponse({"team": {}}),
        ]),
    )
    matches = webagent._fetch_soccer_team_matches("360", "eng.1")
    assert matches["last_match"]["competition"] == "UEFA Champions League"
    assert matches["last_match"]["away_name"] == "Bayern Munich"


def test_fetch_soccer_team_matches_returns_none_when_every_league_call_fails(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({}, status_code=500)] * 3))
    assert webagent._fetch_soccer_team_matches("360", "eng.1") is None


def test_fetch_soccer_team_matches_falls_back_to_team_summary_for_the_next_fixture(monkeypatch):
    """Regression test for a real, reported bug found live: ESPN's own
    schedule endpoint (.../teams/{id}/schedule) returned exactly one event
    for Manchester United - the most recent PAST match - and zero future
    fixtures, even though a real next fixture (Ipswich Town, 2026-08-30)
    was already on ESPN's calendar and visible via a second endpoint
    (.../teams/{id}, its `nextEvent` field). Without this fallback,
    next_match came back None, the evidence correctly (for the data it
    had) said "UNKNOWN", and the small model was left free to invent an
    opponent and date instead of the real ones."""
    next_event = _event(
        "2026-08-30T15:30Z", "pre", "Scheduled",
        _competitor("Manchester United", "home", 0),
        _competitor("Ipswich Town", "away", 0),
    )
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([
            FakeResponse({"events": [COMPLETED_MATCH_EVENT]}), FakeResponse({"events": []}), FakeResponse({"events": []}),
            FakeResponse({"team": {"nextEvent": [next_event]}}),
        ]),
    )
    matches = webagent._fetch_soccer_team_matches("360", "eng.1")
    assert matches["last_match"]["home_name"] == "Hull City"
    assert matches["next_match"]["home_name"] == "Manchester United"
    assert matches["next_match"]["away_name"] == "Ipswich Town"
    assert matches["next_match"]["date"] == "2026-08-30T15:30Z"


def test_soccer_evidence_item_is_none_for_a_non_soccer_query():
    assert webagent._soccer_evidence_item("who wrote Illusions by Richard Bach") is None


def test_soccer_evidence_item_states_the_gap_when_the_team_cannot_be_resolved(monkeypatch):
    """Silently returning None here used to let the message fall through
    to a generic web search with zero team-specific grounding, and the
    model filled that gap by fabricating a fixture outright. It must
    instead return an explicit evidence item that tells the model not to
    guess."""
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: None)
    item = webagent._soccer_evidence_item("Man United score")
    assert item is not None
    assert item["search_provider"] == "soccer-unresolved"
    assert "do not guess" in item["content"].lower()


def test_soccer_evidence_item_is_none_when_there_are_no_matches_at_all(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
    monkeypatch.setattr(
        webagent, "_fetch_soccer_team_matches",
        lambda team_id, league_slug: {"last_match": None, "next_match": None, "live_match": None},
    )
    assert webagent._soccer_evidence_item("Man United score") is None


def test_soccer_evidence_item_shape_with_a_last_result_and_a_next_match(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
    monkeypatch.setattr(
        webagent, "_fetch_soccer_team_matches",
        lambda team_id, league_slug: {
            "last_match": {
                "date": "2026-08-22T11:30Z", "competition": "English Premier League", "status_description": "Full Time",
                "home_name": "Hull City", "away_name": "Manchester United", "home_score": "2", "away_score": "0",
            },
            "next_match": {
                "date": "2026-08-28T19:00Z", "competition": "English Premier League", "status_description": "Scheduled",
                "home_name": "Manchester United", "away_name": "Arsenal", "home_score": None, "away_score": None,
            },
            "live_match": None,
        },
    )
    item = webagent._soccer_evidence_item("Man United score")
    assert item["url"] == "https://www.espn.com/soccer/team/_/id/360"
    assert "Last result: Hull City 2-0 Manchester United" in item["content"]
    assert "Next match: Manchester United" in item["content"]
    assert "Arsenal" in item["content"]
    assert item["truthfulness_confidence"] > 0
    assert item["recency_confidence"] == 100
    assert item["corroborating_domains"] == []


def test_soccer_outcome_sentence_states_the_winner_explicitly():
    """Real, live-reported bug: given the raw scoreline "Hull City 2-0
    Manchester United", the small answering model told the user Manchester
    United had WON 2-0 - inverting both the winner and the home/away
    scores. A bare "home NN-NN away" line leaves that inference to the
    model; an explicit won/lost/drew sentence removes it."""
    assert webagent._soccer_outcome_sentence("Hull City", "Manchester United", "2", "0") == "Hull City won 2-0 against Manchester United."
    assert webagent._soccer_outcome_sentence("Man United", "Arsenal", "0", "3") == "Arsenal won 3-0 against Man United."
    assert webagent._soccer_outcome_sentence("Man United", "Arsenal", "1", "1") == "Man United and Arsenal drew 1-1."
    assert webagent._soccer_outcome_sentence("Man United", "Arsenal", None, None) is None


def test_soccer_evidence_item_states_the_last_result_outcome_explicitly(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
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
    item = webagent._soccer_evidence_item("Man United score")
    assert "Hull City won 2-0 against Manchester United." in item["content"]


def test_soccer_evidence_item_states_explicitly_when_there_is_no_next_match(monkeypatch):
    """Real, reported bug: when there's no upcoming fixture, the old
    content just silently said nothing about "next" at all. Asked "who do
    they play next?" with only a "Last result" line to work from, the
    model relabeled that past match as the upcoming one instead of saying
    it didn't know. An explicit "no data" line is a fact the model can
    honestly report instead of a gap it has to paper over."""
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
    monkeypatch.setattr(
        webagent, "_fetch_soccer_team_matches",
        lambda team_id, league_slug: {
            "last_match": {
                "date": "2026-08-22T11:30Z", "competition": "English Premier League", "status_description": "Full Time",
                "home_name": "Hull City", "away_name": "Manchester United", "home_score": "2", "away_score": "0",
            },
            "next_match": None,
            "live_match": None,
        },
    )
    item = webagent._soccer_evidence_item("who do they play next?", team_name="Manchester United")
    assert "Last result: Hull City 2-0 Manchester United" in item["content"]
    assert "Next match: UNKNOWN" in item["content"]
    assert "PAST match" in item["content"]


def test_model_directed_web_research_short_circuits_to_live_soccer_result(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
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

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not fall through to a generic web search for a soccer-result query")

    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", _fail_if_called)

    evidence = webagent.model_directed_web_research("Man United score")

    assert len(evidence) == 1
    assert "Hull City 2-0 Manchester United" in evidence[0]["content"]


def test_model_directed_web_research_states_the_gap_when_team_cannot_be_resolved(isolated_data_dir, monkeypatch):
    """A team-shaped query that fails to resolve must stop here with an
    explicit "don't guess" evidence item, not fall through to a generic,
    ungrounded web search - see
    test_soccer_evidence_item_states_the_gap_when_the_team_cannot_be_resolved
    for the failure this prevents."""
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: None)
    monkeypatch.setattr(webagent, "_select_tool_actions", lambda prompt: [])
    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
    monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

    evidence = webagent.model_directed_web_research("Man United score")

    assert len(evidence) == 1
    assert evidence[0]["search_provider"] == "soccer-unresolved"


class TestMultiToolFollowUpResolution:
    """Regression tests for the real, reported bug: a follow-up like "so the
    hull match was aug 22nd 2026" carries no subject of its own (no team
    name, no "score"/"result"/"fixture" wording), so _looks_like_soccer_query
    never matches it directly. Without any grounding at all, the model
    fabricated an entire fake narrative (wrong opponent, wrong score, an
    invented player).

    Fixed, eventually, by replacing regex-based detection as the primary
    mechanism entirely: natural language has far more phrasings than any
    hand-written pattern set can keep up with (four separate regex bugs
    were found and fixed in this exact area first). _select_tool_actions is
    a model-driven, multi-tool selector that sees recent conversation
    history, so it can resolve a subject-less follow-up the way a person
    reading the conversation would - see model_directed_web_research and
    _select_tool_actions's docstrings.
    """

    def _seed_conversation_with_a_soccer_question(self):
        webagent.context.assistant_convo = [
            webagent.sys_msgs.assistant_msg,
            {"role": "user", "content": "what was the last fixture for Man United?"},
            {"role": "assistant", "content": "Manchester United lost to Hull City 2-0."},
        ]

    def test_select_tool_actions_resolves_a_followup_using_conversation_context(self, isolated_data_dir, fake_ollama_chat):
        self._seed_conversation_with_a_soccer_question()
        fake_ollama_chat.reply = '{"tools": [{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}]}'

        actions = webagent._select_tool_actions("so the hull match was aug 22nd 2026")

        assert actions == [{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}]
        sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
        assert "Manchester United" in sent_prompt  # conversation history reached the planner

    def test_model_directed_web_research_uses_multi_tool_selection_for_a_followup(self, isolated_data_dir, monkeypatch):
        self._seed_conversation_with_a_soccer_question()
        monkeypatch.setattr(
            webagent, "_select_tool_actions",
            lambda prompt: [{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}],
        )
        monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
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
        monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

        evidence = webagent.model_directed_web_research("so the hull match was aug 22nd 2026")

        assert len(evidence) == 1
        assert "Hull City 2-0 Manchester United" in evidence[0]["content"]

    def test_model_directed_web_research_falls_back_to_the_refinement_loop_when_nothing_is_selected(self, isolated_data_dir, monkeypatch):
        self._seed_conversation_with_a_soccer_question()
        monkeypatch.setattr(webagent, "_select_tool_actions", lambda prompt: [])
        monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
        monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

        evidence = webagent.model_directed_web_research("so the hull match was aug 22nd 2026")

        assert evidence == []


class TestMatchDatetimeLocalization:
    """Regression tests for the real, reported bug: a match's UTC ISO
    timestamp from ESPN (e.g. "2026-08-29T18:00Z") was passed straight
    through into the evidence text unconverted, leaving a small local model
    to do the UTC-to-local timezone arithmetic itself - exactly the kind of
    thing that gets silently guessed at instead of computed. Converting it
    once, deterministically, in code removes that guess entirely."""

    def _write_profile(self, isolated_data_dir, timezone_value):
        (isolated_data_dir / "user_details.log").write_text(f"timezone: {timezone_value}\n")

    def test_user_timezone_is_none_with_no_profile_configured(self, isolated_data_dir):
        assert webagent._user_timezone() is None

    def test_user_timezone_resolves_the_profile_abbreviation(self, isolated_data_dir):
        self._write_profile(isolated_data_dir, "MST (Mountain Standard Time)")
        assert str(webagent._user_timezone()) == "America/Phoenix"

    def test_user_timezone_is_none_for_an_unrecognized_value(self, isolated_data_dir):
        """No guessing beyond an exact, listed match - an unrecognized zone
        must come back None, not silently coerced to some default zone."""
        self._write_profile(isolated_data_dir, "somewhere over the rainbow")
        assert webagent._user_timezone() is None

    def test_format_match_datetime_converts_to_the_configured_zone(self, isolated_data_dir):
        self._write_profile(isolated_data_dir, "MST (Mountain Standard Time)")
        assert webagent._format_match_datetime("2026-08-29T18:00Z") == "2026-08-29 11:00 MST"

    def test_format_match_datetime_labels_utc_explicitly_when_no_zone_is_configured(self, isolated_data_dir):
        assert webagent._format_match_datetime("2026-08-29T18:00Z") == "2026-08-29 18:00 UTC"

    def test_soccer_evidence_item_uses_the_configured_local_time(self, isolated_data_dir, monkeypatch):
        self._write_profile(isolated_data_dir, "MST (Mountain Standard Time)")
        monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
        monkeypatch.setattr(
            webagent, "_fetch_soccer_team_matches",
            lambda team_id, league_slug: {
                "last_match": None,
                "next_match": {
                    "date": "2026-08-29T18:00Z", "competition": "English Premier League", "status_description": "Scheduled",
                    "home_name": "Manchester United", "away_name": "Arsenal", "home_score": None, "away_score": None,
                },
                "live_match": None,
            },
        )
        item = webagent._soccer_evidence_item("Man United score")
        assert "2026-08-29 11:00 MST" in item["content"]
        assert "2026-08-29T18:00Z" not in item["content"]


class TestSoccerStandingsGap:
    """Regression test for the real, reported bug: "where do they stand in
    the premier league?" matched no soccer-query detector at all, reached
    the model with zero evidence, and got answered with a fully invented
    league position, point total, and goal record. Gnosis has no live
    standings data source (_fetch_soccer_team_matches only ever pulls a
    team's own schedule) - the fix states that gap explicitly instead of
    pretending to have data this code doesn't fetch."""

    def test_looks_like_soccer_standings_query_matches_common_phrasings(self):
        assert webagent._looks_like_soccer_standings_query("where do they stand in the premier league")
        assert webagent._looks_like_soccer_standings_query("what's the premier league table look like")
        assert not webagent._looks_like_soccer_standings_query("what was the score of the match")

    def test_soccer_standings_evidence_item_states_the_gap(self):
        item = webagent._soccer_standings_evidence_item("where do they stand in the premier league")
        assert item is not None
        assert item["search_provider"] == "soccer-standings-unavailable"
        assert "do not guess" in item["content"].lower()

    def test_try_live_lookup_bypasses_returns_the_standings_gap_evidence(self, isolated_data_dir):
        item = webagent._try_live_lookup_bypasses("where do they stand in the premier league")
        assert item is not None
        assert item["search_provider"] == "soccer-standings-unavailable"


class TestEvidenceSummarizationDoesNotEatTheUnknownInstruction:
    """Regression test for the real, reported bug this whole session traced
    back to: a saved fact-check record showed the ESPN evidence correctly
    said "no scheduled next match" (explicitly marked UNKNOWN), yet the
    displayed answer confidently invented a specific date and opponent
    anyway. The evidence text was right; the model just never saw the part
    that mattered.

    Root cause: enhance_conversation_with_search's standard-mode
    summarize_text(..., max_sentences=2) blindly keeps only the first two
    sentences of every evidence item's content. _soccer_evidence_item's
    "Next match: UNKNOWN ... you must say this information is not
    currently available" text is always sentence 3+ (after the team name
    and the last-result sentence), so it was silently cut before the model
    ever saw it - the model wasn't ignoring an instruction, it was never
    shown one. Fixed by exempting short, curated, single-source evidence
    (ESPN, weather, stock, and the explicit-gap items above) from sentence
    trimming - unlike generic multi-source web search snippets, that
    content is deliberately short already and often carries a "you must
    say X" instruction that can't be safely cut."""

    UNKNOWN_NEXT_MATCH_CONTENT = (
        "Manchester United. Last result: no recent match found in the available data. "
        "Next match: UNKNOWN - no upcoming fixture is scheduled in the available data. If asked what "
        "team plays next or when the next match is, you must say this information is not currently "
        "available. The 'Last result' above is a PAST match that has already happened - it is NOT the "
        "next match, even though it is the only match listed."
    )

    def _espn_evidence(self):
        return [{
            "content": self.UNKNOWN_NEXT_MATCH_CONTENT,
            "url": "https://www.espn.com/soccer/team/_/id/360",
            "search_provider": "espn",
            "truthfulness_confidence": 90,
            "recency_confidence": 100,
            "corroborating_domains": [],
        }]

    def test_standard_mode_prompt_keeps_the_full_unknown_instruction(self):
        prompt = webagent.enhance_conversation_with_search(
            "when does manchester united play next?", self._espn_evidence(), deep=False,
        )
        assert "you must say this information is not currently available" in prompt

    def test_deep_mode_prompt_also_keeps_the_full_unknown_instruction(self):
        prompt = webagent.enhance_conversation_with_search(
            "when does manchester united play next?", self._espn_evidence(), deep=True,
        )
        assert "you must say this information is not currently available" in prompt

    def test_generic_web_search_evidence_is_still_trimmed(self):
        """The fix is scoped to curated live-lookup providers - an ordinary
        multi-sentence scraped web page must still be trimmed in standard
        mode, or noisy generic search results would flood a small model's
        context exactly as evidence_limit/summary_sentences were built to
        prevent."""
        noisy_evidence = [{
            "content": "Sentence one. Sentence two. Sentence three. Sentence four.",
            "url": "https://example.com/article",
            "search_provider": "searx",
            "truthfulness_confidence": 60,
            "recency_confidence": 60,
            "corroborating_domains": [],
        }]
        prompt = webagent.enhance_conversation_with_search("some query", noisy_evidence, deep=False)
        assert "Sentence three" not in prompt
        assert "Sentence one. Sentence two." in prompt
