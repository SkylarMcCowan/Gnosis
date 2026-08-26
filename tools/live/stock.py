"""live.stock_quote: a live stock/share price for a company or ticker,
wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class LiveStockQuoteTool(Tool):
    name = "live.stock_quote"
    description = (
        "Get a live stock/share price for a public company: current price, previous close, "
        "day's high/low, exchange, and currency, as of right now. Use for any question about "
        "a current/today's stock or share price."
    )
    parameters = {"company_or_ticker": "string - a company name (e.g. \"Microsoft\") or ticker symbol (e.g. \"MSFT\")"}
    permission = Permission.SAFE

    def __init__(self, lookup_fn):
        self._lookup_fn = lookup_fn

    def execute(self, company_or_ticker):
        return self._lookup_fn(company_or_ticker)
