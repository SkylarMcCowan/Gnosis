"""Tests for weather_map.py's pure-Python tile math and URL builders - the
part of the zoomable map that doesn't need Qt. SlippyMapWidget itself
(painting, drag/zoom event handling) is exercised indirectly through
tests/test_gui_pages.py's WeatherStationWidget coverage.
"""
import math

import pytest

import weather_map


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


def test_lonlat_to_tile_xy_at_origin_is_the_center_tile():
    x, y = weather_map.lonlat_to_tile_xy(0.0, 0.0, zoom=1)
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(1.0)


def test_tile_xy_to_lonlat_is_the_inverse_of_lonlat_to_tile_xy():
    lon, lat = -110.9747, 32.2226
    for zoom in (2, 7, 12):
        x, y = weather_map.lonlat_to_tile_xy(lon, lat, zoom)
        round_trip_lon, round_trip_lat = weather_map.tile_xy_to_lonlat(x, y, zoom)
        assert round_trip_lon == pytest.approx(lon, abs=1e-6)
        assert round_trip_lat == pytest.approx(lat, abs=1e-6)


def test_lonlat_to_tile_xy_clamps_latitude_to_web_mercator_limits():
    x, y = weather_map.lonlat_to_tile_xy(0.0, 89.9, zoom=3)
    assert math.isfinite(y)


def test_osm_tile_url_format():
    assert weather_map.osm_tile_url(5, 9, 12) == "https://tile.openstreetmap.org/5/9/12.png"


def test_owm_tile_url_format():
    url = weather_map.owm_tile_url("temperature", 5, 9, 12, "MYKEY")
    assert url == "https://tile.openweathermap.org/map/temp_new/5/9/12.png?appid=MYKEY"


def test_rainviewer_tile_url_format():
    url = weather_map.rainviewer_tile_url("https://tilecache.rainviewer.com", "/v2/radar/abc123", 5, 9, 12)
    assert url == "https://tilecache.rainviewer.com/v2/radar/abc123/256/5/9/12/2/1_1.png"


def test_gibs_tile_url_format_puts_row_before_col():
    # GIBS' WMTS-REST path order is z/row/col, the reverse of the z/x/y
    # convention this function's own (x, y) signature uses - confirmed
    # live against the real service (see weather_map.gibs_tile_url).
    url = weather_map.gibs_tile_url("VIIRS_SNPP_CorrectedReflectance_TrueColor", "2026-09-07", 9, 300, 256)
    assert url == (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
        "VIIRS_SNPP_CorrectedReflectance_TrueColor/default/2026-09-07/"
        "GoogleMapsCompatible_Level9/9/256/300.jpg"
    )


def test_fetch_rainviewer_frames_extracts_host_and_frame_lists(monkeypatch):
    payload = {
        "host": "https://tilecache.rainviewer.com",
        "radar": {"past": [{"time": 1000, "path": "/v2/radar/a"}, {"time": 1600, "path": "/v2/radar/b"}]},
        "satellite": {"infrared": []},
    }
    monkeypatch.setattr(weather_map.requests, "get", lambda *a, **k: _FakeResponse(payload))
    result = weather_map.fetch_rainviewer_frames()
    assert result == {
        "host": "https://tilecache.rainviewer.com",
        "radar_frames": [(1000, "/v2/radar/a"), (1600, "/v2/radar/b")],
        "satellite_frames": [],
    }


def test_fetch_rainviewer_frames_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(weather_map.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert weather_map.fetch_rainviewer_frames() is None


class _FakeTextResponse:
    def __init__(self, text, status_ok=True):
        self.text = text
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            import requests
            raise requests.RequestException("boom")


def test_fetch_firms_hotspots_parses_csv_rows(monkeypatch):
    csv_text = (
        "country_id,latitude,longitude,confidence,acq_date,acq_time,frp\n"
        "USA,34.05,-118.24,high,2026-09-08,1200,12.3\n"
        "USA,36.17,-115.14,nominal,2026-09-08,1205,4.1\n"
    )
    monkeypatch.setattr(weather_map.requests, "get", lambda *a, **k: _FakeTextResponse(csv_text))
    hotspots = weather_map.fetch_firms_hotspots("FAKEKEY", (-125, 24, -66, 50))
    assert hotspots == [
        {"lat": 34.05, "lon": -118.24, "confidence": "high", "acq_date": "2026-09-08", "acq_time": "1200", "frp": "12.3"},
        {"lat": 36.17, "lon": -115.14, "confidence": "nominal", "acq_date": "2026-09-08", "acq_time": "1205", "frp": "4.1"},
    ]


def test_fetch_firms_hotspots_returns_none_on_invalid_key(monkeypatch):
    monkeypatch.setattr(weather_map.requests, "get", lambda *a, **k: _FakeTextResponse("Invalid MAP_KEY."))
    assert weather_map.fetch_firms_hotspots("BADKEY", (-125, 24, -66, 50)) is None


def test_fetch_firms_hotspots_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setattr(weather_map.requests, "get", lambda *a, **k: _FakeTextResponse("", status_ok=False))
    assert weather_map.fetch_firms_hotspots("FAKEKEY", (-125, 24, -66, 50)) is None
