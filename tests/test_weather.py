"""Regression tests for the live-weather short-circuit
(fetch_current_weather/_weather_evidence_item, wired into
model_directed_web_research) - a real, reported bug: weather answers were
"total hit or miss," including a wrong temperature for Camdenton, MO.

Root cause, confirmed live before writing this fix: generic web search
snippets for weather sites (AccuWeather etc.) are hourly-forecast tables
with several different temperatures for different hours and no explicit
"current"/"now" label, so the model synthesizing an answer had no
principled way to tell which number was actually current. The fix detects
a weather-shaped query and substitutes a single, unambiguous live reading
from Open-Meteo's free, keyless geocoding + forecast APIs instead of (not
in addition to) the noisy generic search evidence.

All network calls here are mocked (webagent.requests.get) - this suite
must never make a real HTTP request. Live verification against the real
Open-Meteo API and the real reported Camdenton, MO case was done manually,
not as part of this automated suite.
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


GEOCODE_PAYLOAD = {
    "results": [{
        "name": "Camdenton", "admin1": "Missouri", "country": "United States",
        "latitude": 38.00809, "longitude": -92.74463,
    }]
}
FORECAST_PAYLOAD = {
    "current": {
        "time": "2026-08-24T15:30",
        "temperature_2m": 89.7,
        "apparent_temperature": 94.2,
        "relative_humidity_2m": 43,
        "wind_speed_10m": 6.1,
        "weather_code": 1,
    }
}


def _fake_get(sequence):
    calls = iter(sequence)

    def fake(url, params=None, timeout=None):
        return next(calls)
    return fake


def test_looks_like_weather_query_matches_common_phrasings():
    assert webagent._looks_like_weather_query("what is the weather in Camdenton, MO right now?")
    assert webagent._looks_like_weather_query("how hot is it in Phoenix today")
    assert webagent._looks_like_weather_query("is it raining in Seattle")
    assert not webagent._looks_like_weather_query("who wrote Illusions by Richard Bach")


def test_weather_location_query_strips_lead_and_trailing_filler():
    assert webagent._weather_location_query("what is the weather in Camdenton, MO right now?") == "Camdenton, MO"
    assert webagent._weather_location_query("weather in Camdenton, MO") == "Camdenton, MO"
    assert webagent._weather_location_query("how hot is it in Phoenix today") == "Phoenix"
    assert webagent._weather_location_query("is it raining in Seattle right now") == "Seattle"


def test_fetch_current_weather_parses_a_real_shaped_response(monkeypatch):
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([FakeResponse(GEOCODE_PAYLOAD), FakeResponse(FORECAST_PAYLOAD)]),
    )
    weather = webagent.fetch_current_weather("Camdenton, MO")
    assert weather["place"] == "Camdenton, Missouri, United States"
    assert weather["temp_f"] == 89.7
    assert weather["description"] == "mainly clear"
    assert weather["observed_at"] == "2026-08-24T15:30"


def test_fetch_current_weather_returns_none_when_geocoding_finds_nothing(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({"results": []})]))
    assert webagent.fetch_current_weather("Nowhereville, XX") is None


def test_fetch_current_weather_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({}, status_code=500)]))
    assert webagent.fetch_current_weather("Camdenton, MO") is None


def test_fetch_current_weather_returns_none_on_unexpected_response_shape(monkeypatch):
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([FakeResponse(GEOCODE_PAYLOAD), FakeResponse({"current": {}})]),
    )
    assert webagent.fetch_current_weather("Camdenton, MO") is None


def test_weather_evidence_item_is_none_for_a_non_weather_query():
    assert webagent._weather_evidence_item("who wrote Illusions by Richard Bach") is None


def test_weather_evidence_item_is_none_when_the_live_lookup_fails(monkeypatch):
    monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: None)
    assert webagent._weather_evidence_item("weather in Camdenton, MO") is None


def test_weather_evidence_item_shape_when_the_live_lookup_succeeds(monkeypatch):
    monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: {
        "place": "Camdenton, Missouri, United States", "temp_f": 89.7, "feels_like_f": 94.2,
        "humidity": 43, "wind_mph": 6.1, "description": "mainly clear", "observed_at": "2026-08-24T15:30",
    })
    item = webagent._weather_evidence_item("weather in Camdenton, MO")
    assert item["url"] == "https://open-meteo.com/"
    assert "89.7" in item["content"]
    assert "not a multi-hour forecast table" in item["content"]
    assert item["truthfulness_confidence"] > 0
    assert item["recency_confidence"] == 100
    assert item["corroborating_domains"] == []


def test_model_directed_web_research_short_circuits_to_live_weather(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: {
        "place": "Camdenton, Missouri, United States", "temp_f": 89.7, "feels_like_f": 94.2,
        "humidity": 43, "wind_mph": 6.1, "description": "mainly clear", "observed_at": "2026-08-24T15:30",
    })

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not fall through to a generic web search for a weather query")

    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", _fail_if_called)

    evidence = webagent.model_directed_web_research("what is the weather in Camdenton, MO right now?")

    assert len(evidence) == 1
    assert "89.7" in evidence[0]["content"]


def test_model_directed_web_research_does_not_short_circuit_in_deep_think_mode(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = True
    try:
        monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: {
            "place": "Camdenton, Missouri, United States", "temp_f": 89.7, "feels_like_f": 94.2,
            "humidity": 43, "wind_mph": 6.1, "description": "mainly clear", "observed_at": "2026-08-24T15:30",
        })
        monkeypatch.setattr(webagent, "_deep_think_research_plan", lambda prompt: ["weather in Camdenton, MO"])
        monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
        monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

        evidence = webagent.model_directed_web_research("what is the weather in Camdenton, MO right now?")

        assert not any("open-meteo" in item.get("search_provider", "") for item in evidence)
    finally:
        webagent.context.deep_think_mode = False


def test_model_directed_web_research_falls_back_to_search_when_weather_lookup_fails(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: None)
    monkeypatch.setattr(webagent, "_select_tool_actions", lambda prompt: [])
    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
    monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

    evidence = webagent.model_directed_web_research("what is the weather in Camdenton, MO right now?")

    assert evidence == []
