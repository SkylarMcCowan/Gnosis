"""Tests for satellite.py's backend (URL builders + response parsers) - no
Qt involved, same split as test_weather_map.py/test_weather_station.py.
SatelliteWidget's compositing/painting is exercised by launching the app,
not here (QImage/QPainter off-thread compositing isn't worth faking).
"""
from datetime import datetime, timezone

import pytest

import satellite


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


def test_goes_image_url_format():
    assert satellite.goes_image_url("goes_east") == "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/FD/GEOCOLOR/1808x1808.jpg"
    assert satellite.goes_image_url("goes_west", size="678x678") == "https://cdn.star.nesdis.noaa.gov/GOES18/ABI/FD/GEOCOLOR/678x678.jpg"


def test_fetch_goes_image_returns_bytes(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse(b"fake-jpeg-bytes"))
    assert satellite.fetch_goes_image("goes_east") == b"fake-jpeg-bytes"


def test_fetch_goes_image_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse(b"", status_ok=False))
    assert satellite.fetch_goes_image("goes_east") is None


def test_fetch_himawari_latest_info_parses_captured_at(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse({"date": "2026-09-08 23:20:00", "file": "x"}))
    info = satellite.fetch_himawari_latest_info()
    assert info["captured_at"] == datetime(2026, 9, 8, 23, 20, 0, tzinfo=timezone.utc)


def test_fetch_himawari_latest_info_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert satellite.fetch_himawari_latest_info() is None


def test_himawari_tile_url_format():
    captured_at = datetime(2026, 9, 8, 23, 20, 0, tzinfo=timezone.utc)
    url = satellite.himawari_tile_url(captured_at, 1, 2)
    assert url == "https://himawari8-dl.nict.go.jp/himawari8/img/D531106/4d/550/2026/09/08/232000_1_2.png"


def test_fetch_epic_latest_uses_the_last_image_of_the_day(monkeypatch):
    payload = [
        {"identifier": "1", "date": "2026-09-06 00:59:48", "image": "epic_1b_20260906005948"},
        {"identifier": "2", "date": "2026-09-06 22:36:15", "image": "epic_1b_20260906223615"},
    ]
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse(payload))
    info = satellite.fetch_epic_latest()
    assert info == {
        "image_url": "https://epic.gsfc.nasa.gov/archive/natural/2026/09/06/png/epic_1b_20260906223615.png",
        "captured_at": datetime(2026, 9, 6, 22, 36, 15, tzinfo=timezone.utc),
    }


def test_fetch_epic_latest_returns_none_on_empty_list(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse([]))
    assert satellite.fetch_epic_latest() is None


def test_fetch_epic_latest_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse({}, status_ok=False))
    assert satellite.fetch_epic_latest() is None


def test_fetch_epic_image_returns_bytes(monkeypatch):
    monkeypatch.setattr(satellite.requests, "get", lambda *a, **k: _FakeResponse(b"fake-png-bytes"))
    assert satellite.fetch_epic_image("https://example.com/x.png") == b"fake-png-bytes"
