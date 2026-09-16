"""Senate financial-disclosure scraper for the Stocks Tracker pane's
Congress tab - the official electronic disclosure system at
efdsearch.senate.gov, since the usual free/keyless aggregators for this data
("Senate Stock Watcher"/"House Stock Watcher") are confirmed dead (their S3
buckets return 403 Forbidden, project abandoned). House disclosures are
deliberately out of scope: they're overwhelmingly PDF scans, not worth the
scraping complexity for structured data.

The site requires a small session dance before it will serve real search
results: GET the search home page for a CSRF token, POST an agreement to
the site's terms (this is what actually establishes a working session -
skipping it makes every later search redirect back to the landing page),
then POST the search itself. Confirmed live, and confirmed critical: the
search POST must match the exact minimal body below. A differently-shaped
request (missing the CSRF body field, or padded with a full DataTables
`columns[n][...]` parameter set) gets intercepted before reaching the real
backend - Akamai serves a static "Site Under Maintenance" page instead
(distinguishable by `Server: AmazonS3`/no gunicorn header and a stale
`Last-Modified`), not a real error, so this would otherwise look like a
transient outage forever.

Periodic Transaction Report (PTR) filings submitted electronically render
as a real HTML transactions table and are parsed here. Older/paper filings
are PDF scans and are surfaced as unparsed (a link, not silently dropped) -
see MEMORY: "No silent fallbacks".
"""
import re

import requests
from bs4 import BeautifulSoup

_BASE_URL = "https://efdsearch.senate.gov"
_HOME_URL = f"{_BASE_URL}/search/home/"
_SEARCH_URL = f"{_BASE_URL}/search/"
_SEARCH_DATA_URL = f"{_BASE_URL}/search/report/data/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"}
_TIMEOUT = 15

_CSRF_INPUT_PATTERN = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')

# report_types=[11] is "Periodic Transaction Report" - the only report type
# this scraper parses. filer_types=[] (any) covers Senators and candidates
# alike, since either can file a PTR.
_SEARCH_BODY_TEMPLATE = {
    "start": "0",
    "length": "100",
    "report_types": "[11]",
    "filer_types": "[]",
    "submitted_start_date": "01/01/2012 00:00:00",
    "submitted_end_date": "",
    "candidate_state": "",
    "senator_state": "",
    "office_id": "",
    "first_name": "",
    "last_name": "",
}


def open_session():
    """Runs the CSRF-token + terms-of-use handshake once. Returns
    (cookies, csrf_token) to reuse across this refresh cycle's filing-list
    fetch and any lazy per-filing detail fetches. Returns None on failure."""
    try:
        home_response = requests.get(_HOME_URL, headers=_HEADERS, timeout=_TIMEOUT)
        home_response.raise_for_status()
        match = _CSRF_INPUT_PATTERN.search(home_response.text)
        if not match:
            return None
        csrf_token = match.group(1)
        cookies = home_response.cookies.get_dict()

        agree_response = requests.post(
            _HOME_URL,
            data={"csrfmiddlewaretoken": csrf_token, "prohibition_agreement": "1"},
            cookies=cookies, headers={**_HEADERS, "Referer": _HOME_URL},
            timeout=_TIMEOUT, allow_redirects=True,
        )
        agree_response.raise_for_status()
        cookies.update(agree_response.cookies.get_dict())
        return cookies, csrf_token
    except (requests.RequestException, ValueError, TypeError):
        return None


def list_ptr_filings(cookies, csrf_token, start_date="01/01/2012 00:00:00", max_rows=100):
    """One page of Periodic Transaction Report filing metadata, newest
    first as the site returns them. -> list of {"first_name","last_name",
    "office","date_received","detail_url","kind"} where kind is "ptr"
    (electronic, parseable) or "paper" (PDF scan, not parsed). None on
    failure - including the Akamai-maintenance-page case, since that's
    also not real data."""
    try:
        body = dict(_SEARCH_BODY_TEMPLATE)
        body["submitted_start_date"] = start_date
        body["length"] = str(max_rows)
        body["csrfmiddlewaretoken"] = csrf_token
        response = requests.post(
            _SEARCH_DATA_URL, data=body, cookies=cookies,
            headers={**_HEADERS, "Referer": _SEARCH_URL}, timeout=_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        filings = []
        for row in payload["data"]:
            first_name, last_name, office, link_html, date_received = row
            link_soup = BeautifulSoup(link_html, "html.parser")
            anchor = link_soup.find("a")
            if anchor is None or not anchor.get("href"):
                continue
            href = anchor["href"]
            if "/search/view/paper/" in href:
                kind = "paper"
            elif "/search/view/ptr/" in href:
                kind = "ptr"
            else:
                continue
            filings.append({
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "office": office.strip(),
                "date_received": date_received.strip(),
                "detail_url": f"{_BASE_URL}{href}" if href.startswith("/") else href,
                "kind": kind,
            })
        return filings
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def _looks_like_landing_page(html_text):
    """The session-expired/blocked case redirects back to the search
    landing page instead of a filing's transaction table - detected by the
    absence of the transactions table this parser expects, so a stale
    session gets one real re-authentication attempt instead of silently
    returning an empty transaction list."""
    return "id_transactions" not in html_text and "<table" not in html_text.lower()


def fetch_ptr_transactions(cookies, csrf_token, detail_url):
    """Parses one electronically-filed PTR's transaction table. -> list of
    {"transaction_date","owner","ticker","asset_name","asset_type",
    "transaction_type","amount_range","comment"}. Re-authenticates once and
    retries if the session looks expired. None on failure. Raises
    ValueError if called on a "paper" filing's url (a paper filing has no
    HTML table to parse - a caller error, not a network failure)."""
    if "/search/view/ptr/" not in detail_url:
        raise ValueError(f"Not an electronic PTR filing url: {detail_url}")
    try:
        response = requests.get(
            detail_url, cookies=cookies, headers={**_HEADERS, "Referer": _SEARCH_URL}, timeout=_TIMEOUT,
        )
        response.raise_for_status()
        if _looks_like_landing_page(response.text):
            reauth = open_session()
            if reauth is None:
                return None
            cookies, csrf_token = reauth
            response = requests.get(
                detail_url, cookies=cookies, headers={**_HEADERS, "Referer": _SEARCH_URL}, timeout=_TIMEOUT,
            )
            response.raise_for_status()
            if _looks_like_landing_page(response.text):
                return None

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if table is None:
            return None
        transactions = []
        rows = table.find_all("tr")
        for row in rows:
            cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
            if len(cells) < 9:
                continue
            _seq, transaction_date, owner, ticker, asset_name, asset_type, transaction_type, amount_range, comment = cells[:9]
            if not _seq.strip().isdigit():
                continue  # a header row rendered with <td> instead of <th>, not a real transaction
            transactions.append({
                "transaction_date": transaction_date,
                "owner": owner,
                "ticker": ticker,
                "asset_name": asset_name,
                "asset_type": asset_type,
                "transaction_type": transaction_type,
                "amount_range": amount_range,
                "comment": comment,
            })
        return transactions
    except (requests.RequestException, ValueError, TypeError):
        return None
