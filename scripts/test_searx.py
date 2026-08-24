#!/usr/bin/env python3
"""Simple SearxNG availability test script.

Run: python scripts/test_searx.py
"""
import os
import requests

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

print('\nDone.')
