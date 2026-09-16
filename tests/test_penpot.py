"""Tests for penpot.py's real RPC/changes-building logic - no live Penpot
instance involved, requests.post is faked throughout (same pattern as
tests/test_weather_station.py)."""
import pytest

import penpot


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


@pytest.fixture(autouse=True)
def penpot_env(monkeypatch):
    monkeypatch.setenv("PENPOT_URL", "http://localhost:9001")
    monkeypatch.setenv("PENPOT_ACCESS_TOKEN", "test-token")


def _capture_post(monkeypatch, payload):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(payload)

    monkeypatch.setattr(penpot.requests, "post", fake_post)
    return calls


def test_missing_url_raises_explicit_error(monkeypatch):
    monkeypatch.delenv("PENPOT_URL", raising=False)
    with pytest.raises(penpot.PenpotError, match="PENPOT_URL"):
        penpot.list_projects()


def test_missing_token_raises_explicit_error(monkeypatch):
    monkeypatch.delenv("PENPOT_ACCESS_TOKEN", raising=False)
    with pytest.raises(penpot.PenpotError, match="PENPOT_ACCESS_TOKEN"):
        penpot.list_projects()


def test_request_failure_raises_penpot_error(monkeypatch):
    def fake_post(*a, **k):
        return _FakeResponse({}, status_ok=False)
    monkeypatch.setattr(penpot.requests, "post", fake_post)
    with pytest.raises(penpot.PenpotError, match="get-teams"):
        penpot._default_team_id()


def test_rpc_sends_token_header_and_kebab_case_body(monkeypatch):
    calls = _capture_post(monkeypatch, {"ok": True})
    penpot._rpc("get-projects", {"team_id": "t1"})
    assert calls[0]["url"] == "http://localhost:9001/api/rpc/command/get-projects"
    assert calls[0]["headers"]["Authorization"] == "Token test-token"
    assert calls[0]["json"] == {"team-id": "t1"}


def test_default_team_id_picks_the_flagged_default(monkeypatch):
    _capture_post(monkeypatch, [{"id": "t1", "is-default": False}, {"id": "t2", "is-default": True}])
    assert penpot._default_team_id() == "t2"


def test_default_team_id_falls_back_to_first_team(monkeypatch):
    _capture_post(monkeypatch, [{"id": "t1"}, {"id": "t2"}])
    assert penpot._default_team_id() == "t1"


def test_default_team_id_raises_on_no_teams(monkeypatch):
    _capture_post(monkeypatch, [])
    with pytest.raises(penpot.PenpotError, match="No Penpot teams"):
        penpot._default_team_id()


def test_get_file_summarizes_pages(monkeypatch):
    file_payload = {
        "id": "f1", "name": "Landing page", "revn": 3,
        "data": {
            "pages": ["pg1", "pg2"],
            "pages-index": {
                "pg1": {"name": "Page 1", "objects": {"a": {}, "b": {}}},
                "pg2": {"name": "Page 2", "objects": {}},
            },
        },
    }
    _capture_post(monkeypatch, file_payload)
    result = penpot.get_file("f1")
    assert result == {
        "id": "f1", "name": "Landing page", "revn": 3,
        "pages": [
            {"id": "pg1", "name": "Page 1", "object_count": 2},
            {"id": "pg2", "name": "Page 2", "object_count": 0},
        ],
    }


def test_create_project_rejects_blank_name():
    with pytest.raises(ValueError):
        penpot.create_project("   ")


def test_create_file_rejects_blank_name():
    with pytest.raises(ValueError):
        penpot.create_file("p1", "")


def test_add_board_resolves_first_page_and_root_frame(monkeypatch):
    responses = iter([
        {  # get-file (inside add_board)
            "id": "f1", "revn": 5,
            "data": {"pages": ["pg1"], "pages-index": {"pg1": {"objects": {}}}},
        },
        {"id": "f1", "revn": 6},  # update-file response
    ])
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse(next(responses))

    monkeypatch.setattr(penpot.requests, "post", fake_post)

    result = penpot.add_board("f1", "Home", width=800, height=600, fill_color="#FFFFFF")

    assert result["page_id"] == "pg1"
    assert result["name"] == "Home"
    update_call = calls[1]
    assert update_call["url"].endswith("/update-file")
    body = update_call["json"]
    assert body["revn"] == 5
    change = body["changes"][0]
    assert change["type"] == "add-obj"
    assert change["page-id"] == "pg1"
    assert change["frame-id"] == penpot._ROOT_FRAME_ID
    obj = change["obj"]
    assert obj["type"] == "frame"
    assert obj["width"] == 800 and obj["height"] == 600
    assert obj["fills"] == [{"fill-color": "#FFFFFF", "fill-opacity": 1}]
    assert obj["selrect"]["x2"] == 800


def test_add_board_nests_under_an_existing_root_frame(monkeypatch):
    responses = iter([
        {
            "id": "f1", "revn": 1,
            "data": {
                "pages": ["pg1"],
                "pages-index": {"pg1": {"objects": {"root-1": {"type": "frame"}}}},
            },
        },
        {},
    ])
    monkeypatch.setattr(
        penpot.requests, "post",
        lambda url, json=None, headers=None, timeout=None: _FakeResponse(next(responses)),
    )
    result = penpot.add_board("f1", "Home")
    assert result["id"]


def test_add_shape_rejects_unknown_shape_type():
    with pytest.raises(ValueError):
        penpot.add_shape("f1", "star")


def test_add_shape_builds_text_content_tree(monkeypatch):
    responses = iter([
        {
            "id": "f1", "revn": 2,
            "data": {"pages": ["pg1"], "pages-index": {"pg1": {"objects": {}}}},
        },
        {},
    ])
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResponse(next(responses))

    monkeypatch.setattr(penpot.requests, "post", fake_post)

    result = penpot.add_shape("f1", "text", text="Hello", font_size=24, fill_color="#000000")

    assert result["type"] == "text"
    obj = calls[1]["changes"][0]["obj"]
    assert obj["font-size"] == "24"
    paragraph = obj["content"]["children"][0]["children"][0]
    assert paragraph["children"][0]["text"] == "Hello"
    assert paragraph["children"][0]["fills"] == [{"fill-color": "#000000", "fill-opacity": 1}]


def test_add_shape_nests_inside_a_given_board(monkeypatch):
    responses = iter([
        {
            "id": "f1", "revn": 1,
            "data": {"pages": ["pg1"], "pages-index": {"pg1": {"objects": {}}}},
        },
        {},
    ])
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResponse(next(responses))

    monkeypatch.setattr(penpot.requests, "post", fake_post)

    penpot.add_shape("f1", "rect", board_id="board-1")

    change = calls[1]["changes"][0]
    assert change["frame-id"] == "board-1"
    assert change["obj"]["parent-id"] == "board-1"
