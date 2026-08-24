"""Regression tests for check_search_services (backing /websearch's status
line, webagent.py:1420-1441) and backfill_web_evidence_metadata (/reindexevidence,
webagent.py:1236-1258). Both are boundary-mocked to avoid a real network call.
"""
import json

import webagent


def test_check_search_services_reports_up_when_reachable(monkeypatch):
    class FakeResponse:
        ok = True

        def json(self):
            return {"results": []}

    monkeypatch.setattr(webagent.requests, "get", lambda *a, **k: FakeResponse())

    status = webagent.check_search_services()

    assert status == {"searxng": True}


def test_check_search_services_reports_down_on_request_failure(monkeypatch):
    def _raise(*a, **k):
        raise webagent.requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr(webagent.requests, "get", _raise)

    status = webagent.check_search_services()

    assert status == {"searxng": False}


def test_backfill_web_evidence_metadata_tags_legacy_records(isolated_data_dir):
    evidence_dir = isolated_data_dir / "knowledge_base" / "web_evidence"
    evidence_dir.mkdir(parents=True)
    record = {
        "id": "abc123",
        "query": "overview effect",
        "url": "https://nasa.gov/overview-effect",
        "title": "The Overview Effect",
        "content": "Astronauts report a shift in perspective.",
        "truthfulness_confidence": 80,
        "recency_confidence": 40,
    }
    (evidence_dir / "abc123.json").write_text(json.dumps(record))

    updated = webagent.backfill_web_evidence_metadata()

    assert updated == 1
    saved = json.loads((evidence_dir / "abc123.json").read_text())
    assert "metadata" in saved
    assert saved["metadata"]["source_type"] == "official"


def test_backfill_web_evidence_metadata_returns_zero_when_no_directory(isolated_data_dir):
    assert webagent.backfill_web_evidence_metadata() == 0
