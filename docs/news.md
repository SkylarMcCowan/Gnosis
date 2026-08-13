# `/news` Command

This document explains the `/news` command exposed by this project.

Location
- The implementation lives in `news.py` at the repository root.

Usage
- Run interactively from the assistant or call the module directly:

```bash
python news.py
```

Behavior
- The command fetches (or reads cached) news items and formats them for display. There is a caching layer that stores results in `news_cache.json` to reduce network calls.
- The CLI helper `news_command()` is importable and used by higher-level agents to fetch headlines programmatically.

Configuration
- Network and API dependencies are optional — if live fetching is disabled or network is unavailable, the command falls back to the local `news_cache.json` file.

Troubleshooting
- If you get errors related to missing dependencies, install project requirements:

```bash
pip install -r requirements.txt
```

- To refresh the cache, remove `news_cache.json` and re-run the command; the script will re-fetch when possible.

Notes
- The behavior is intentionally simple; if you want subscription-based sources, filters, or RSS support, I can extend `news.py` to include them and add tests.
