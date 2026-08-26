"""live.* tools: real-time data a generic web search snippet can't reliably
answer, because the source page renders the actual number client-side with
JS (a live weather reading, a stock quote, a soccer score). Each wraps a
free, keyless API instead of scraping - see webagent.py's
fetch_current_weather/_fetch_stock_quote/_fetch_soccer_team_matches
docstrings for the live evidence that motivated each one.
"""
