"""SEC EDGAR 13F institutional-holdings fetcher for the Stocks Tracker
pane's Notable Investors tab - a curated list of well-known
investors/funds, each mapped to a real SEC filer CIK, whose latest
quarterly 13F-HR holdings are fetched and ranked.

Keyless, but SEC policy requires a descriptive User-Agent identifying the
requester (see sec.gov/os/webmaster-faq#developers) - same idiom
weather_station.py already uses for api.weather.gov.

The chain (submissions JSON -> filing index -> information-table XML) has
two real gotchas confirmed live while building this:

1. The information table's filename is NOT standardized across filers -
   it must be found by content (parsing each `.xml` candidate and checking
   its root tag), not by name.
2. A single filer can report the same holding across several rows (e.g.
   split across sub-manager entities) - holdings must be aggregated by
   CUSIP before ranking, or the same company shows up multiple times.

13F data is inherently ~45-day-lagged (quarterly filings); every result
carries both `report_date` (the holdings' as-of date) and `filing_date` (when
it was actually filed) so the UI can show that lag rather than presenting
stale-by-nature data as if it were current.
"""
import xml.etree.ElementTree as ET

import requests

_USER_AGENT = "GnosisStocksTracker skylar.mccowan@opusinspection.com"
_HEADERS = {"User-Agent": _USER_AGENT}
_TIMEOUT = 15

_INFO_TABLE_ROOT_TAG = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}informationTable"
_INFO_TABLE_ENTRY_TAG = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}infoTable"

# Curated, verified-live CIKs (checked against SEC EDGAR's own company
# search - each has an actually-current 13F-HR on file, not just a
# historical one from a defunct entity).
NOTABLE_INVESTORS = [
    {"name": "Warren Buffett", "fund": "Berkshire Hathaway Inc", "cik": "0001067983"},
    {"name": "Bill Ackman", "fund": "Pershing Square Capital Management, L.P.", "cik": "0001336528"},
    {"name": "Michael Burry", "fund": "Scion Asset Management, LLC", "cik": "0001649339"},
    {"name": "Carl Icahn", "fund": "Icahn Carl C", "cik": "0000921669"},
    {"name": "Ray Dalio", "fund": "Bridgewater Associates, LP", "cik": "0001350694"},
    {"name": "David Tepper", "fund": "Appaloosa LP", "cik": "0001656456"},
    {"name": "George Soros", "fund": "Soros Fund Management LLC", "cik": "0001029160"},
    {"name": "Jim Simons (legacy)", "fund": "Renaissance Technologies LLC", "cik": "0001037389"},
]


def _tag_localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def fetch_latest_13f_meta(cik):
    """-> {"accession_number","filing_date","report_date"} for the newest
    13F-HR (or 13F-HR/A amendment) on file, or None if there isn't one or
    the request fails."""
    try:
        response = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json", headers=_HEADERS, timeout=_TIMEOUT,
        )
        response.raise_for_status()
        recent = response.json()["filings"]["recent"]
        forms = recent["form"]
        for index, form in enumerate(forms):
            if form.startswith("13F-HR"):
                return {
                    "accession_number": recent["accessionNumber"][index],
                    "filing_date": recent["filingDate"][index],
                    "report_date": recent["reportDate"][index],
                }
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


def _filing_index_documents(cik, accession_number):
    accession_no_dashes = accession_number.replace("-", "")
    cik_no_zeros = str(int(cik))
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}/index.json"
    response = requests.get(index_url, headers=_HEADERS, timeout=_TIMEOUT)
    response.raise_for_status()
    items = response.json()["directory"]["item"]
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}"
    return [(item["name"], f"{base_url}/{item['name']}") for item in items if item["name"].lower().endswith(".xml")]


def _find_and_parse_info_table(cik, accession_number):
    """Fetches each candidate .xml document in the filing and returns the
    one whose root element is an informationTable, parsed into raw
    {"name_of_issuer","cusip","value","shares"} rows (not yet aggregated).
    None if no such document is found or any fetch fails."""
    for _name, url in _filing_index_documents(cik, accession_number):
        try:
            doc_response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            doc_response.raise_for_status()
            root = ET.fromstring(doc_response.content)
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
        if root.tag != _INFO_TABLE_ROOT_TAG:
            continue
        rows = []
        for entry in root:
            if _tag_localname(entry.tag) != _tag_localname(_INFO_TABLE_ENTRY_TAG):
                continue
            fields = {_tag_localname(child.tag): child for child in entry}
            try:
                name_of_issuer = fields["nameOfIssuer"].text or ""
                cusip = fields["cusip"].text or ""
                value = float(fields["value"].text)
                shares_node = fields["shrsOrPrnAmt"]
                shares = float(next(c.text for c in shares_node if _tag_localname(c.tag) == "sshPrnamt"))
            except (KeyError, StopIteration, TypeError, ValueError):
                continue
            rows.append({"name_of_issuer": name_of_issuer.strip(), "cusip": cusip.strip(), "value": value, "shares": shares})
        return rows
    return None


def _aggregate_by_cusip(rows):
    aggregated = {}
    for row in rows:
        entry = aggregated.setdefault(row["cusip"], {"name": row["name_of_issuer"], "cusip": row["cusip"], "value": 0.0, "shares": 0.0})
        entry["value"] += row["value"]
        entry["shares"] += row["shares"]
    return list(aggregated.values())


def fetch_holdings_for_investor(cik, top_n=10):
    """End-to-end: latest 13F-HR meta -> filing index -> content-sniffed
    information table -> aggregated, ranked holdings. -> {"filing_date",
    "report_date","holdings":[{"name","cusip","value","shares",
    "pct_of_portfolio"}, ...top_n...],"total_value": <sum across ALL
    holdings, not just top_n>}. None if any stage fails - never a partial
    or fabricated result."""
    meta = fetch_latest_13f_meta(cik)
    if meta is None:
        return None
    try:
        rows = _find_and_parse_info_table(cik, meta["accession_number"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    if not rows:
        return None
    aggregated = _aggregate_by_cusip(rows)
    total_value = sum(entry["value"] for entry in aggregated)
    aggregated.sort(key=lambda entry: entry["value"], reverse=True)
    holdings = []
    for entry in aggregated[:top_n]:
        holdings.append({
            "name": entry["name"],
            "cusip": entry["cusip"],
            "value": entry["value"],
            "shares": entry["shares"],
            "pct_of_portfolio": (entry["value"] / total_value * 100) if total_value else 0.0,
        })
    return {
        "filing_date": meta["filing_date"],
        "report_date": meta["report_date"],
        "holdings": holdings,
        "total_value": total_value,
    }
