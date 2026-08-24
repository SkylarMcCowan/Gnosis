"""Regression tests for the live-stock-quote short-circuit
(_fetch_stock_quote/_stock_evidence_item, wired into
model_directed_web_research) - a real, reported bug: asked for Microsoft's
current stock price, the assistant confidently stated "$308.67" and
attributed it to Yahoo Finance.

Root cause, confirmed live before writing this fix: every evidence item a
real SearxNG search saved for "current stock price of Microsoft" was a
page's static meta description (Google/Yahoo/stockanalysis all render the
actual price client-side with JS), so none of them contained a single
digit. Two more results were pure noise (web.whatsapp.com, a fintech app
called Current) that matched only because the query contains the word
"current". With zero real numbers in evidence, the model filled the gap by
inventing one and citing a source that never stated it. The fix detects a
stock-price-shaped query and substitutes a single, unambiguous live quote
from Yahoo Finance's keyless chart/search endpoints instead of (not in
addition to) the noisy generic search evidence - the same shape of fix
_weather_evidence_item already applies to weather.

All network calls here are mocked (webagent.requests.get) - this suite must
never make a real HTTP request. Live verification against the real Yahoo
Finance endpoints was done manually, not as part of this automated suite.
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


SEARCH_PAYLOAD = {
    "quotes": [{"symbol": "MSFT", "quoteType": "EQUITY", "shortname": "Microsoft Corporation"}],
}
CHART_PAYLOAD = {
    "chart": {"result": [{"meta": {
        "symbol": "MSFT", "currency": "USD", "regularMarketPrice": 487.31,
        "chartPreviousClose": 483.24, "regularMarketDayHigh": 490.605, "regularMarketDayLow": 481.86,
        "fullExchangeName": "NasdaqGS", "regularMarketTime": 1787601601,
    }}]},
}


def _fake_get(sequence):
    calls = iter(sequence)

    def fake(url, params=None, headers=None, timeout=None):
        return next(calls)
    return fake


def test_looks_like_stock_query_matches_common_phrasings():
    assert webagent._looks_like_stock_query("whats the current stock price of Microsoft?")
    assert webagent._looks_like_stock_query("how much is Tesla stock trading at")
    assert webagent._looks_like_stock_query("current stock price of Microsoft Corporation (MSFT) on NASDAQ")
    assert webagent._looks_like_stock_query("what's the current price of $MSFT")
    assert not webagent._looks_like_stock_query("who wrote Illusions by Richard Bach")


def test_looks_like_stock_query_matches_bare_price_phrasing_without_the_word_stock():
    """Real bug: "what is the price of TESLA?" and "what is the current price
    for MSFT?" have neither "stock"/"share" nor a ticker symbol/cashtag, so
    the original keyword-only detector never matched them at all and they
    fell straight through to the noisy generic search path that fabricates
    prices."""
    assert webagent._looks_like_stock_query("what is the price of TESLA?")
    assert webagent._looks_like_stock_query("what is the current price for MSFT?")


def test_stock_query_subject_strips_lead_and_trailing_filler():
    assert webagent._stock_query_subject("whats the current stock price of Microsoft?") == ("Microsoft", False)
    assert webagent._stock_query_subject("how much is Tesla stock trading at") == ("Tesla", False)
    assert webagent._stock_query_subject("what is the price of TESLA?") == ("TESLA", False)
    assert webagent._stock_query_subject("what is the current price for MSFT?") == ("MSFT", False)
    assert webagent._stock_query_subject("Microsoft Corp stock price") == ("Microsoft Corp", False)


def test_stock_query_subject_strips_leading_question_words_before_a_subject_first_price_phrase():
    """Real, reported bug: "what is MSFT stock price?" resolved to the
    ticker query "what is MSFT" instead of "MSFT" - the lead-phrase list
    only covers "[question words] + price-phrase + of/for + SUBJECT"
    ("what is the stock price of MSFT"), not the equally common
    "[question words] + SUBJECT + price-phrase" shape, so the leading
    "what is " was never stripped when no "of"/"for" followed."""
    assert webagent._stock_query_subject("what is MSFT stock price?") == ("MSFT", False)
    assert webagent._stock_query_subject("MSFT stock price?") == ("MSFT", False)
    assert webagent._stock_query_subject("how much is MSFT stock worth") == ("MSFT", False)


def test_stock_query_subject_prefers_an_explicit_ticker():
    subject, is_ticker = webagent._stock_query_subject("current stock price of Microsoft Corporation (MSFT) on NASDAQ")
    assert subject == "MSFT"
    assert is_ticker is True

    subject, is_ticker = webagent._stock_query_subject("what's the current price of $MSFT")
    assert subject == "MSFT"
    assert is_ticker is True


def test_resolve_stock_symbol_parses_a_real_shaped_response(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse(SEARCH_PAYLOAD)]))
    assert webagent._resolve_stock_symbol("Microsoft") == ("MSFT", "Microsoft Corporation")


def test_resolve_stock_symbol_returns_none_when_nothing_matches(monkeypatch):
    """Yahoo's search endpoint occasionally returns an empty match for a
    query that succeeds moments later (confirmed live - see
    _resolve_stock_symbol's retry docstring), so a real "no match" case
    retries once before giving up; both attempts here return the same
    empty result."""
    monkeypatch.setattr(webagent.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({"quotes": []})] * 2))
    assert webagent._resolve_stock_symbol("Nonexistent Company XYZ") is None


def test_fetch_stock_quote_parses_a_real_shaped_response(monkeypatch):
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse(CHART_PAYLOAD)]))
    quote = webagent._fetch_stock_quote("MSFT")
    assert quote["price"] == 487.31
    assert quote["currency"] == "USD"
    assert quote["exchange"] == "NasdaqGS"


def test_fetch_stock_quote_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(webagent.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(webagent.requests, "get", _fake_get([FakeResponse({}, status_code=500)] * 2))
    assert webagent._fetch_stock_quote("MSFT") is None


def test_fetch_stock_quote_returns_none_on_unexpected_response_shape(monkeypatch):
    monkeypatch.setattr(webagent.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([FakeResponse({"chart": {"result": [{"meta": {}}]}})] * 2),
    )
    assert webagent._fetch_stock_quote("MSFT") is None


def test_resolve_stock_symbol_retries_once_after_a_transient_empty_result(monkeypatch):
    """Real, confirmed-live flakiness: a search for the exact ticker "MSFT"
    returned zero quotes once, then succeeded on the very next attempt with
    no code change. One retry should absorb that instead of falling back to
    generic search over a transient hiccup."""
    monkeypatch.setattr(webagent.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        webagent.requests, "get",
        _fake_get([FakeResponse({"quotes": []}), FakeResponse(SEARCH_PAYLOAD)]),
    )
    assert webagent._resolve_stock_symbol("MSFT") == ("MSFT", "Microsoft Corporation")


def test_stock_evidence_item_is_none_for_a_non_stock_query():
    assert webagent._stock_evidence_item("who wrote Illusions by Richard Bach") is None


def test_stock_evidence_item_is_none_when_the_live_lookup_fails(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_stock_symbol", lambda name: ("MSFT", "Microsoft Corporation"))
    monkeypatch.setattr(webagent, "_fetch_stock_quote", lambda symbol: None)
    assert webagent._stock_evidence_item("whats the current stock price of Microsoft?") is None


def test_stock_evidence_item_shape_when_the_live_lookup_succeeds(monkeypatch):
    monkeypatch.setattr(webagent, "_resolve_stock_symbol", lambda name: ("MSFT", "Microsoft Corporation"))
    monkeypatch.setattr(webagent, "_fetch_stock_quote", lambda symbol: {
        "symbol": "MSFT", "price": 487.31, "currency": "USD", "previous_close": 483.24,
        "day_high": 490.605, "day_low": 481.86, "exchange": "NasdaqGS",
        "observed_at": "2026-08-24T20:00:01+00:00",
    })
    item = webagent._stock_evidence_item("whats the current stock price of Microsoft?")
    assert item["url"] == "https://finance.yahoo.com/quote/MSFT"
    assert "487.31" in item["content"]
    assert item["truthfulness_confidence"] > 0
    assert item["recency_confidence"] == 100
    assert item["corroborating_domains"] == []


def test_model_directed_web_research_short_circuits_to_live_stock_quote(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "_resolve_stock_symbol", lambda name: ("MSFT", "Microsoft Corporation"))
    monkeypatch.setattr(webagent, "_fetch_stock_quote", lambda symbol: {
        "symbol": "MSFT", "price": 487.31, "currency": "USD", "previous_close": 483.24,
        "day_high": 490.605, "day_low": 481.86, "exchange": "NasdaqGS",
        "observed_at": "2026-08-24T20:00:01+00:00",
    })

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not fall through to a generic web search for a stock-price query")

    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", _fail_if_called)

    evidence = webagent.model_directed_web_research("whats the current stock price of Microsoft?")

    assert len(evidence) == 1
    assert "487.31" in evidence[0]["content"]


def test_model_directed_web_research_falls_back_to_search_when_stock_lookup_fails(isolated_data_dir, monkeypatch):
    webagent.context.deep_think_mode = False
    monkeypatch.setattr(webagent, "_resolve_stock_symbol", lambda name: None)
    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
    monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

    evidence = webagent.model_directed_web_research("whats the current stock price of Microsoft?")

    assert evidence == []
