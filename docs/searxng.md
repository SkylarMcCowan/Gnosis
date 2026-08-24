# SearxNG integration

Overview
--------
The assistant now attempts web searches against a SearxNG instance before falling back to DuckDuckGo or the offline intelligence fallback.

- Order: SearxNG (preferred) → DuckDuckGo (if installed) → offline `search_fallback()`.
- Default SearxNG URL: `https://search.lozdev.com`.

Configuration
-------------
Set a custom SearxNG instance by exporting the `SEARXNG_URL` environment variable:

```bash
export SEARXNG_URL="https://search.lozdev.com"
```

Or for a single command: 

```bash
SEARXNG_URL="https://search.lozdev.com" ./venv/bin/python webagent.py
```

Quick test
----------
Verify the SearxNG JSON endpoint is reachable from your machine:

```bash
curl -s "${SEARXNG_URL:-https://search.lozdev.com}/search?q=python&format=json" | jq .
```

Usage
-----
- Start `webagent.py` (or `webagent_gui.py`) as you normally do — web search is on by default, and the model decides per message whether a search is warranted.
- Use `/websearch` to turn it off (e.g. to force answers from the model's own knowledge only) and back on again.
- The agent will try SearxNG first and fall back to other sources if no usable results are returned.

Troubleshooting
---------------
- If searches return no results: confirm `SEARXNG_URL` is correct and reachable from the host running the agent.
- If your SearxNG instance requires authentication or a nonstandard endpoint, update the `SEARXNG_URL` to include the proper host and scheme.
- If `curl` returns valid JSON but the agent still gets no results, check for network restrictions (firewall, proxy). The code uses `requests` with a 12s timeout.

Notes
-----
- The integration is intentionally simple: it fetches the JSON `results` and attempts light content extraction. You can extend `search_searx()` in `webagent.py` to add site-specific parsing, custom headers, or pagination.
- For privacy/security, prefer running a local or internal SearxNG instance.
