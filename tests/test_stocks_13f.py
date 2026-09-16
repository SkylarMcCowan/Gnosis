"""Tests for stocks_13f.py's SEC EDGAR 13F fetcher. All network calls are
mocked (stocks_13f.requests.get) - this suite must never make a real HTTP
request. Fixtures are trimmed from real payloads verified live against SEC
EDGAR while building this module (Berkshire Hathaway CIK 0001067983,
Pershing Square CIK 0001336528).
"""
import stocks_13f


class FakeResponse:
    def __init__(self, payload=None, content=None, status_code=200):
        self._payload = payload
        self._content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise stocks_13f.requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload

    @property
    def content(self):
        return self._content


def _fake_get(sequence):
    calls = iter(sequence)

    def fake(url, headers=None, timeout=None):
        return next(calls)
    return fake


SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "form": ["4", "13F-HR", "13F-NT"],
            "accessionNumber": ["0000000000-26-000001", "0001193125-26-352200", "0000000000-26-000002"],
            "filingDate": ["2026-08-20", "2026-08-14", "2026-05-15"],
            "reportDate": ["2026-08-20", "2026-06-30", "2026-03-31"],
        }
    }
}

INDEX_PAYLOAD = {
    "directory": {
        "item": [
            {"name": "primary_doc.xml"},
            {"name": "56757.xml"},
        ]
    }
}

COVER_PAGE_XML = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <headerData/>
</edgarSubmission>"""

# Regression fixture for the real finding: a single filer can report the
# same holding split across several sub-manager rows (Berkshire had 6 rows
# for Ally Financial via its insurance subsidiaries) - must be aggregated
# by cusip, not left as separate rows.
INFO_TABLE_XML = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <cusip>037833100</cusip>
    <value>65950296923</value>
    <shrsOrPrnAmt><sshPrnamt>227917808</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ALLY FINL INC</nameOfIssuer>
    <cusip>02005N100</cusip>
    <value>1000000</value>
    <shrsOrPrnAmt><sshPrnamt>10000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ALLY FINL INC</nameOfIssuer>
    <cusip>02005N100</cusip>
    <value>2000000</value>
    <shrsOrPrnAmt><sshPrnamt>20000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_fetch_latest_13f_meta_finds_the_newest_13f_hr(monkeypatch):
    monkeypatch.setattr(stocks_13f.requests, "get", _fake_get([FakeResponse(SUBMISSIONS_PAYLOAD)]))
    meta = stocks_13f.fetch_latest_13f_meta("0001067983")
    assert meta == {
        "accession_number": "0001193125-26-352200",
        "filing_date": "2026-08-14",
        "report_date": "2026-06-30",
    }


def test_fetch_latest_13f_meta_returns_none_when_no_13f_hr_present(monkeypatch):
    payload = {"filings": {"recent": {
        "form": ["4", "13F-NT"], "accessionNumber": ["a", "b"], "filingDate": ["x", "y"], "reportDate": ["x", "y"],
    }}}
    monkeypatch.setattr(stocks_13f.requests, "get", _fake_get([FakeResponse(payload)]))
    assert stocks_13f.fetch_latest_13f_meta("0001067983") is None


def test_fetch_latest_13f_meta_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setattr(stocks_13f.requests, "get", _fake_get([FakeResponse({}, status_code=500)]))
    assert stocks_13f.fetch_latest_13f_meta("0001067983") is None


def test_find_and_parse_info_table_is_found_by_content_not_filename(monkeypatch):
    """Regression for the real, confirmed finding that the information
    table's filename varies by filer (Berkshire: "56757.xml", Pershing
    Square: "infotable.xml") - it must be identified by its XML root tag,
    not by name. This fixture's index lists the cover page first
    (primary_doc.xml, wrong root tag) and the real table second, under an
    arbitrary numeric name."""
    monkeypatch.setattr(
        stocks_13f.requests, "get",
        _fake_get([
            FakeResponse(INDEX_PAYLOAD),
            FakeResponse(content=COVER_PAGE_XML.replace(b"informationtable", b"thirteenffiler").replace(b"informationTable", b"edgarSubmission")),
            FakeResponse(content=INFO_TABLE_XML),
        ]),
    )
    rows = stocks_13f._find_and_parse_info_table("0001067983", "0001193125-26-352200")
    assert rows is not None
    assert len(rows) == 3


def test_aggregate_by_cusip_sums_multiple_rows_for_the_same_holding():
    rows = [
        {"name_of_issuer": "APPLE INC", "cusip": "037833100", "value": 65950296923.0, "shares": 227917808.0},
        {"name_of_issuer": "ALLY FINL INC", "cusip": "02005N100", "value": 1000000.0, "shares": 10000.0},
        {"name_of_issuer": "ALLY FINL INC", "cusip": "02005N100", "value": 2000000.0, "shares": 20000.0},
    ]
    aggregated = {entry["cusip"]: entry for entry in stocks_13f._aggregate_by_cusip(rows)}
    assert aggregated["02005N100"]["value"] == 3000000.0
    assert aggregated["02005N100"]["shares"] == 30000.0
    assert len(aggregated) == 2


def test_fetch_holdings_for_investor_end_to_end(monkeypatch):
    monkeypatch.setattr(
        stocks_13f.requests, "get",
        _fake_get([
            FakeResponse(SUBMISSIONS_PAYLOAD),
            FakeResponse(INDEX_PAYLOAD),
            FakeResponse(content=COVER_PAGE_XML.replace(b"informationtable", b"thirteenffiler").replace(b"informationTable", b"edgarSubmission")),
            FakeResponse(content=INFO_TABLE_XML),
        ]),
    )
    result = stocks_13f.fetch_holdings_for_investor("0001067983", top_n=10)
    assert result["report_date"] == "2026-06-30"
    assert result["filing_date"] == "2026-08-14"
    assert len(result["holdings"]) == 2
    apple = next(h for h in result["holdings"] if h["name"] == "APPLE INC")
    assert apple["pct_of_portfolio"] > 90


def test_fetch_holdings_for_investor_returns_none_if_meta_fetch_fails(monkeypatch):
    monkeypatch.setattr(stocks_13f.requests, "get", _fake_get([FakeResponse({}, status_code=500)]))
    assert stocks_13f.fetch_holdings_for_investor("0001067983") is None


def test_fetch_holdings_for_investor_returns_none_if_no_info_table_found(monkeypatch):
    monkeypatch.setattr(
        stocks_13f.requests, "get",
        _fake_get([
            FakeResponse(SUBMISSIONS_PAYLOAD),
            FakeResponse(INDEX_PAYLOAD),
            FakeResponse(content=COVER_PAGE_XML.replace(b"informationtable", b"thirteenffiler").replace(b"informationTable", b"edgarSubmission")),
            FakeResponse(content=COVER_PAGE_XML.replace(b"informationtable", b"thirteenffiler").replace(b"informationTable", b"edgarSubmission")),
        ]),
    )
    assert stocks_13f.fetch_holdings_for_investor("0001067983") is None
