#!/usr/bin/env python3
"""Simple SearxNG + DuckDuckGo availability test script.

Run: python scripts/test_searx.py
"""
import os
import requests
from pathlib import Path

SEARX = os.environ.get('SEARXNG_URL', 'https://search.lozdev.com').rstrip('/')

print(f"Testing SearxNG at: {SEARX}")
try:
    res = requests.get(f"{SEARX}/search", params={'q': 'healthcheck', 'format': 'json'}, timeout=8)
    if res.ok:
        print('SearxNG: OK (returned HTTP 200)')
    else:
        print(f'SearxNG: ERROR (status {res.status_code})')
except Exception as e:
    print(f'SearxNG: FAILED ({e})')

# DuckDuckGo availability (duckduckgo-search)
try:
    from duckduckgo_search import DDGS
    print('duckduckgo-search package: installed')
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text('healthcheck', max_results=1))
            print('DuckDuckGo API: OK')
    except Exception as e:
        print(f'DuckDuckGo API: FAILED ({e})')
except ImportError:
    print('duckduckgo-search package: NOT INSTALLED')

print('\nDone.')
