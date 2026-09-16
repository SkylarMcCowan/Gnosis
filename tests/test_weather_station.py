"""Tests for weather_station.py's backend (geocoding/NWS fetch functions and
the radio-station bookmark store) - no Qt involved, same split as
test_worklog.py. core.config._root_override is redirected to a scratch dir
by the autouse isolated_data_dir fixture in conftest.py, so radio station
storage never touches the project's real weather_station/ directory.
"""
import pytest

import weather_station
import webagent


class _FakeResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            import requests
            raise requests.RequestException("boom")

    def json(self):
        return self._payload

    @property
    def content(self):
        return self._payload


def test_home_address_reads_the_profile_field(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {"home_address": "Tucson, AZ"})
    assert weather_station.home_address() == "Tucson, AZ"


def test_home_address_is_none_when_unset(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {"home_address": ""})
    assert weather_station.home_address() is None


def test_home_address_does_not_fall_back_to_location(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {"location": "Tucson, AZ", "home_address": ""})
    assert weather_station.home_address() is None


def test_geocode_returns_lat_lon_and_place(monkeypatch):
    payload = {"results": [{"latitude": 32.22, "longitude": -110.97, "name": "Tucson", "admin1": "Arizona", "country": "United States"}]}
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    result = weather_station.geocode("Tucson, AZ")
    assert result == {"lat": 32.22, "lon": -110.97, "place": "Tucson, Arizona, United States"}


def test_geocode_returns_none_on_no_match(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({"results": []}))
    assert weather_station.geocode("nowhere at all") is None


def test_geocode_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_station.geocode("Tucson, AZ") is None


def test_fetch_point_metadata_extracts_forecast_urls_and_radar_station(monkeypatch):
    payload = {"properties": {
        "forecast": "https://api.weather.gov/gridpoints/TWC/91,49/forecast",
        "forecastHourly": "https://api.weather.gov/gridpoints/TWC/91,49/forecast/hourly",
        "radarStation": "KEMX",
        "relativeLocation": {"properties": {"city": "Tucson", "state": "AZ"}},
    }}
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    result = weather_station.fetch_point_metadata(32.22, -110.97)
    assert result == {
        "forecast_url": "https://api.weather.gov/gridpoints/TWC/91,49/forecast",
        "hourly_url": "https://api.weather.gov/gridpoints/TWC/91,49/forecast/hourly",
        "radar_station": "KEMX",
        "city": "Tucson",
        "state": "AZ",
    }


def test_fetch_point_metadata_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_station.fetch_point_metadata(0, 0) is None


def test_fetch_point_metadata_returns_out_of_coverage_on_404(monkeypatch):
    import requests

    class _FakeHTTPErrorResponse:
        status_code = 404

        def raise_for_status(self):
            error = requests.HTTPError("404 Not Found")
            error.response = self
            raise error

    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeHTTPErrorResponse())
    assert weather_station.fetch_point_metadata(51.5, -0.12) == {"out_of_coverage": True}


def test_fetch_active_alerts_tags_fire_related_events(monkeypatch):
    payload = {"features": [
        {"properties": {"event": "Red Flag Warning", "severity": "Severe", "areaDesc": "County A"}},
        {"properties": {"event": "Winter Storm Warning", "severity": "Moderate", "areaDesc": "County B"}},
    ]}
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    alerts = weather_station.fetch_active_alerts(32.22, -110.97)
    assert [a["is_fire"] for a in alerts] == [True, False]


def test_fetch_active_alerts_returns_empty_list_when_none_active(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({"features": []}))
    assert weather_station.fetch_active_alerts(32.22, -110.97) == []


def test_fetch_active_alerts_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_station.fetch_active_alerts(0, 0) is None


def test_degrees_to_compass_maps_cardinal_and_ordinal_points():
    assert weather_station._degrees_to_compass(0) == "N"
    assert weather_station._degrees_to_compass(45) == "NE"
    assert weather_station._degrees_to_compass(180) == "S"
    assert weather_station._degrees_to_compass(359) == "N"


def test_fetch_open_meteo_forecast_shapes_periods_like_nws(monkeypatch):
    payload = {"daily": {
        "time": ["2026-09-08", "2026-09-09"],
        "weather_code": [0, 61],
        "temperature_2m_max": [75.4, 68.2],
        "wind_speed_10m_max": [8.6, 12.1],
        "wind_direction_10m_dominant": [90, 270],
    }}
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    periods = weather_station.fetch_open_meteo_forecast(51.5, -0.12)
    assert periods[0]["name"] == "Today"
    assert periods[0]["temperature"] == 75
    assert periods[0]["temperatureUnit"] == "F"
    assert periods[0]["windDirection"] == "E"
    assert periods[1]["windDirection"] == "W"


def test_fetch_open_meteo_forecast_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_station.fetch_open_meteo_forecast(51.5, -0.12) is None


def test_fetch_gdacs_events_extracts_fields_and_sorts_by_alert_level(monkeypatch):
    payload = {"features": [
        {
            "geometry": {"coordinates": [116.0, 28.0]},
            "properties": {
                "eventtype": "FL", "name": "Flood in China", "country": "China",
                "alertlevel": "Green", "description": "Flood", "fromdate": "2026-09-01T00:00:00",
                "url": {"report": "https://www.gdacs.org/report.aspx?a"},
            },
        },
        {
            "geometry": {"coordinates": [139.0, 35.0]},
            "properties": {
                "eventtype": "EQ", "name": "Earthquake near Tokyo", "country": "Japan",
                "alertlevel": "Red", "description": "Earthquake", "fromdate": "2026-09-05T00:00:00",
                "url": {"report": "https://www.gdacs.org/report.aspx?b"},
            },
        },
    ]}
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    events = weather_station.fetch_gdacs_events("2026-08-01", "2026-09-08")
    assert [e["event_type"] for e in events] == ["EQ", "FL"]
    assert events[0] == {
        "event_type": "EQ", "name": "Earthquake near Tokyo", "country": "Japan",
        "alert_level": "Red", "description": "Earthquake", "from_date": "2026-09-05T00:00:00",
        "lat": 35.0, "lon": 139.0, "url": "https://www.gdacs.org/report.aspx?b",
    }


def test_fetch_gdacs_events_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_station.fetch_gdacs_events("2026-08-01", "2026-09-08") is None


def test_search_radio_stations_keeps_only_stations_with_a_stream_url(monkeypatch):
    payload = [
        {"name": "Fernley, NV (NOAA Weather Radio WWG20)", "url_resolved": "https://example.com/wwg20", "country": "USA", "state": "Nevada", "tags": "", "bitrate": 32},
        {"name": "No Stream", "url_resolved": "", "url": "", "country": "USA"},
    ]
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse(payload))
    results = weather_station.search_radio_stations("NOAA Weather Radio")
    assert len(results) == 1
    assert results[0]["name"] == "Fernley, NV (NOAA Weather Radio WWG20)"
    assert results[0]["stream_url"] == "https://example.com/wwg20"


def test_search_radio_stations_returns_none_on_empty_query():
    assert weather_station.search_radio_stations("") is None
    assert weather_station.search_radio_stations("   ") is None


def test_search_radio_stations_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setattr(weather_station.requests, "get", lambda *a, **k: _FakeResponse([], status_ok=False))
    assert weather_station.search_radio_stations("weather") is None


def test_firms_map_key_is_none_when_unset():
    assert weather_station.firms_map_key() is None


def test_set_and_read_firms_map_key():
    weather_station.set_firms_map_key("abc123")
    assert weather_station.firms_map_key() == "abc123"


def test_clearing_firms_map_key_restores_none():
    weather_station.set_firms_map_key("abc123")
    weather_station.set_firms_map_key("")
    assert weather_station.firms_map_key() is None


def test_openweathermap_api_key_is_none_when_unset():
    assert weather_station.openweathermap_api_key() is None


def test_set_and_read_openweathermap_api_key():
    weather_station.set_openweathermap_api_key("abc123")
    assert weather_station.openweathermap_api_key() == "abc123"


def test_clearing_openweathermap_api_key_restores_none():
    weather_station.set_openweathermap_api_key("abc123")
    weather_station.set_openweathermap_api_key("")
    assert weather_station.openweathermap_api_key() is None


def test_radio_station_store_starts_empty_without_creating_a_directory(tmp_path):
    assert weather_station.list_radio_stations() == []
    assert not (tmp_path / "weather_station").exists()


def test_add_and_list_radio_station():
    record = weather_station.add_radio_station("NOAA Relay", "https://example.com/stream.mp3")
    assert record["name"] == "NOAA Relay"
    assert record["stream_url"] == "https://example.com/stream.mp3"
    assert weather_station.list_radio_stations() == [record]


def test_add_radio_station_requires_name_and_url():
    with pytest.raises(ValueError):
        weather_station.add_radio_station("", "https://example.com/stream.mp3")
    with pytest.raises(ValueError):
        weather_station.add_radio_station("NOAA Relay", "")


def test_remove_radio_station():
    record = weather_station.add_radio_station("NOAA Relay", "https://example.com/stream.mp3")
    assert weather_station.remove_radio_station(record["id"]) is True
    assert weather_station.list_radio_stations() == []
    assert weather_station.remove_radio_station(record["id"]) is False


def test_add_radio_station_rejects_a_duplicate_stream_url():
    weather_station.add_radio_station("NOAA Relay", "https://example.com/stream.mp3")
    with pytest.raises(ValueError):
        weather_station.add_radio_station("Same Relay, Different Name", "https://example.com/stream.mp3")
    assert len(weather_station.list_radio_stations()) == 1
