"""Tests for stocks_congress.py's Senate eFD scraper. All network calls are
mocked (stocks_congress.requests.get/post) - this suite must never make a
real HTTP request. Fixtures are shaped after the real CSRF handshake and
JSON/HTML responses verified live against efdsearch.senate.gov while
building this module (including a real filing, Sen. Whitehouse's PTR).
"""
import stocks_congress


class FakeResponse:
    def __init__(self, text="", payload=None, cookies=None, status_code=200):
        self.text = text
        self._payload = payload
        self.cookies = _FakeCookies(cookies or {})
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise stocks_congress.requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class _FakeCookies:
    def __init__(self, values):
        self._values = values

    def get_dict(self):
        return dict(self._values)


HOME_HTML = '<form><input type="hidden" name="csrfmiddlewaretoken" value="abc123"></form>'

FILINGS_PAYLOAD = {
    "data": [
        [
            "Sheldon", "Whitehouse", "Whitehouse, Sheldon (Senator)",
            '<a href="/search/view/ptr/f8d003c0-ca1e-4c39-9d66-632d220180e1/" target="_blank">'
            "Periodic Transaction Report for 09/02/2026</a>",
            "09/02/2026",
        ],
        [
            "RICHARD ", "BLUMENTHAL", "Senator",
            '<a href="/search/view/paper/929216d5-0000-0000-0000-000000000000/" target="_blank">'
            "Periodic Transaction Report for 08/01/2026</a>",
            "08/01/2026",
        ],
    ],
}

TRANSACTIONS_HTML = """
<html><body>
<table id="id_transactions">
<tr><td>#</td><td>Transaction Date</td><td>Owner</td><td>Ticker</td><td>Asset Name</td>
<td>Asset Type</td><td>Type</td><td>Amount</td><td>Comment</td></tr>
<tr>
<td>5</td><td>08/06/2026</td><td>Self</td><td>--</td><td>SDZNY- Sandoz Group AG ADR</td>
<td>Stock</td><td>Sale (Full)</td><td>$1,001 - $15,000</td><td>--</td>
</tr>
<tr>
<td>4</td><td>08/13/2026</td><td>Self</td><td>NVDA</td><td>NVIDIA Corporation - Common Stock</td>
<td>Stock</td><td>Sale (Partial)</td><td>$15,001 - $50,000</td><td>--</td>
</tr>
</table>
</body></html>
"""

LANDING_PAGE_HTML = "<html><body><h1>Reports must be filed electronically</h1></body></html>"


def test_open_session_extracts_csrf_token_and_posts_agreement(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(("get", url))
        return FakeResponse(text=HOME_HTML, cookies={"csrftoken": "cookie-value"})

    def fake_post(url, data=None, cookies=None, headers=None, timeout=None, allow_redirects=None):
        calls.append(("post", url, data))
        return FakeResponse(cookies={"sessionid": "session-value"})

    monkeypatch.setattr(stocks_congress.requests, "get", fake_get)
    monkeypatch.setattr(stocks_congress.requests, "post", fake_post)

    result = stocks_congress.open_session()

    assert result is not None
    cookies, csrf_token = result
    assert csrf_token == "abc123"
    assert cookies == {"csrftoken": "cookie-value", "sessionid": "session-value"}
    assert calls[1][2]["csrfmiddlewaretoken"] == "abc123"
    assert calls[1][2]["prohibition_agreement"] == "1"


def test_open_session_returns_none_when_csrf_token_is_missing(monkeypatch):
    monkeypatch.setattr(stocks_congress.requests, "get", lambda *a, **k: FakeResponse(text="<html>no form here</html>"))
    assert stocks_congress.open_session() is None


def test_open_session_returns_none_on_request_failure(monkeypatch):
    def fake_get(*a, **k):
        raise stocks_congress.requests.RequestException("boom")
    monkeypatch.setattr(stocks_congress.requests, "get", fake_get)
    assert stocks_congress.open_session() is None


def test_list_ptr_filings_parses_electronic_and_paper_rows(monkeypatch):
    monkeypatch.setattr(stocks_congress.requests, "post", lambda *a, **k: FakeResponse(payload=FILINGS_PAYLOAD))

    filings = stocks_congress.list_ptr_filings({"sessionid": "x"}, "abc123")

    assert len(filings) == 2
    assert filings[0]["kind"] == "ptr"
    assert filings[0]["first_name"] == "Sheldon"
    assert filings[0]["last_name"] == "Whitehouse"
    assert filings[0]["detail_url"].endswith("/search/view/ptr/f8d003c0-ca1e-4c39-9d66-632d220180e1/")
    assert filings[1]["kind"] == "paper"


def test_list_ptr_filings_returns_none_on_request_failure(monkeypatch):
    def fake_post(*a, **k):
        raise stocks_congress.requests.RequestException("boom")
    monkeypatch.setattr(stocks_congress.requests, "post", fake_post)
    assert stocks_congress.list_ptr_filings({}, "abc123") is None


def test_fetch_ptr_transactions_parses_a_real_shaped_table(monkeypatch):
    monkeypatch.setattr(stocks_congress.requests, "get", lambda *a, **k: FakeResponse(text=TRANSACTIONS_HTML))

    transactions = stocks_congress.fetch_ptr_transactions(
        {"sessionid": "x"}, "abc123",
        "https://efdsearch.senate.gov/search/view/ptr/f8d003c0-ca1e-4c39-9d66-632d220180e1/",
    )

    assert len(transactions) == 2
    assert transactions[1]["ticker"] == "NVDA"
    assert transactions[1]["transaction_type"] == "Sale (Partial)"
    assert transactions[1]["amount_range"] == "$15,001 - $50,000"


def test_fetch_ptr_transactions_rejects_a_paper_filing_url():
    try:
        stocks_congress.fetch_ptr_transactions({}, "abc123", "https://efdsearch.senate.gov/search/view/paper/xyz/")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fetch_ptr_transactions_reauthenticates_once_on_an_expired_session(monkeypatch):
    responses = iter([FakeResponse(text=LANDING_PAGE_HTML), FakeResponse(text=TRANSACTIONS_HTML)])
    monkeypatch.setattr(stocks_congress.requests, "get", lambda *a, **k: next(responses))
    monkeypatch.setattr(stocks_congress, "open_session", lambda: ({"sessionid": "new"}, "def456"))

    transactions = stocks_congress.fetch_ptr_transactions(
        {"sessionid": "stale"}, "abc123",
        "https://efdsearch.senate.gov/search/view/ptr/f8d003c0-ca1e-4c39-9d66-632d220180e1/",
    )

    assert len(transactions) == 2


def test_fetch_ptr_transactions_returns_none_if_reauth_also_fails(monkeypatch):
    monkeypatch.setattr(stocks_congress.requests, "get", lambda *a, **k: FakeResponse(text=LANDING_PAGE_HTML))
    monkeypatch.setattr(stocks_congress, "open_session", lambda: None)

    result = stocks_congress.fetch_ptr_transactions(
        {"sessionid": "stale"}, "abc123",
        "https://efdsearch.senate.gov/search/view/ptr/f8d003c0-ca1e-4c39-9d66-632d220180e1/",
    )

    assert result is None
