import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

CACHE_FILE = os.path.join(os.path.dirname(__file__), "news_cache.json")
MAX_HEADLINES_PER_SOURCE = 4
MAX_ARTICLE_CHARS = 1200
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

NEWS_SOURCES = [
    {"name": "BBC News", "url": "https://www.bbc.com/news"},
    {"name": "CNN", "url": "https://www.cnn.com"},
    {"name": "Reuters", "url": "https://www.reuters.com"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/international"},
    {"name": "NPR", "url": "https://www.npr.org"},
    {"name": "AP News", "url": "https://apnews.com"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com"},
    {"name": "Axios", "url": "https://www.axios.com"},
    {"name": "Politico", "url": "https://www.politico.com"},
]

DOMAIN_HEADLINE_SELECTORS = {
    "bbc.com": ["a.gs-c-promo-heading", "h3.gs-c-promo-heading__title"],
    "cnn.com": ["h3.cd__headline a", "span.cd__headline-text"],
    "reuters.com": ["article.story a.story-title", "div.story-content a", "h3.story-title a", "article > a"],
    "theguardian.com": ["a.js-headline-text", "h3.fc-item__title a"],
    "npr.org": ["article.has-image h3.title a", "h3.title a", "div.item-info a"],
    "apnews.com": ["h3.CardHeadline a", "article a", "a.Component-headline"],
    "aljazeera.com": ["a.u-clickable-card__link", "h3.post-title a", "a.featured-article__title-link"],
    "axios.com": ["a.Anchor-link", "a.Card-headline"],
    "politico.com": ["a.teaser__link", "h3.teaser__headline a", "section.story-preview a"],
}

BLACKLIST_PATTERNS = [
    re.compile(r"read more", re.I),
    re.compile(r"watch live", re.I),
    re.compile(r"sign up", re.I),
    re.compile(r"subscribe", re.I),
    re.compile(r"more stories", re.I),
]

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None
    HAS_TRAFILATURA = False


def _normalize_url(href, base_url):
    if not href or href.startswith("javascript:") or href.startswith("mailto:"):
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("#"):
        return None
    parsed = urlparse(href)
    if not parsed.scheme:
        href = urljoin(base_url, href)
    return href


def _safe_request(url):
    try:
        response = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return None


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {"timestamp": None, "items": []}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {"timestamp": None, "items": []}


def _save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass


def _headline_is_valid(title, url):
    if not title or len(title) < 30 or len(title) > 180:
        return False
    if any(pattern.search(title) for pattern in BLACKLIST_PATTERNS):
        return False
    if url and urlparse(url).fragment and urlparse(url).path == "":
        return False
    return True


def _extract_headlines(html, source_url):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(source_url).netloc.replace("www.", "")
    selectors = DOMAIN_HEADLINE_SELECTORS.get(domain, [])
    headlines = []
    seen_titles = set()

    def add_candidate(element):
        if element is None:
            return
        text = element.get_text(strip=True)
        href = element.get("href") or element.get("data-href")
        full_url = _normalize_url(href, source_url)
        if _headline_is_valid(text, full_url) and text not in seen_titles and full_url:
            seen_titles.add(text)
            headlines.append({"title": text, "url": full_url})

    for selector in selectors:
        for element in soup.select(selector):
            add_candidate(element)
            if len(headlines) >= MAX_HEADLINES_PER_SOURCE * 2:
                break
        if len(headlines) >= MAX_HEADLINES_PER_SOURCE * 2:
            break

    if len(headlines) < MAX_HEADLINES_PER_SOURCE:
        for element in soup.select("a"):
            add_candidate(element)
            if len(headlines) >= MAX_HEADLINES_PER_SOURCE * 2:
                break

    unique = []
    for item in headlines:
        if item["title"] not in [u["title"] for u in unique]:
            unique.append(item)
        if len(unique) >= MAX_HEADLINES_PER_SOURCE:
            break
    return unique


def _extract_article_text(html, source_url):
    if not html:
        return None
    if HAS_TRAFILATURA:
        article_text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if article_text and len(article_text.strip()) > 100:
            return article_text.strip()

    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    if article:
        article_text = " ".join(p.get_text(strip=True) for p in article.find_all("p"))
    else:
        main_section = soup.find("main") or soup
        article_text = " ".join(
            p.get_text(strip=True) for p in main_section.find_all("p") if p.get_text(strip=True)
        )
    if article_text:
        return article_text.strip()

    text = soup.get_text(separator=" ")
    return " ".join(text.split()).strip()


def _summarize_text(text, max_sentences=4):
    if not text:
        return None
    sentences = re.split(r"(?<=[.\!?])\s+", text)
    summary = " ".join(sentences[:max_sentences]).strip()
    return summary if summary else text[:MAX_ARTICLE_CHARS]


def _format_article_detail(article_url, title=None):
    html = _safe_request(article_url)
    if html is None:
        print(f"Unable to fetch article details from {article_url}")
        return

    article_text = _extract_article_text(html, article_url)
    if not article_text:
        print(f"Could not extract article content from {article_url}")
        return

    summary = _summarize_text(article_text, max_sentences=5)
    print(f"\nArticle details: {article_url}\n")
    if title:
        print(f"Title: {title}\n")
    print(f"Summary:\n{summary}\n")
    if len(article_text) > len(summary):
        remaining = article_text.replace(summary, "", 1).strip()
        if remaining:
            snippet = remaining[:MAX_ARTICLE_CHARS]
            print(f"Excerpt:\n{snippet}\n")
    print("Use '/news <number>' or '/news <url>' to inspect another article.")


def _find_cached_item(args, cache):
    if not args:
        return None
    args = args.strip()
    if args.isdigit():
        index = int(args) - 1
        if 0 <= index < len(cache.get("items", [])):
            return cache["items"][index]
    if args.startswith("http"):
        for item in cache.get("items", []):
            if item["url"] == args:
                return item
        return {"url": args, "title": None}

    normalized = args.lower()
    return [
        item
        for item in cache.get("items", [])
        if item.get("title") and normalized in item["title"].lower()
        or normalized in item["source"].lower()
    ]


def _search_headlines(query, cache_items):
    normalized = query.lower()
    return [
        item
        for item in cache_items
        if normalized in item["title"].lower()
        or normalized in item["source"].lower()
        or normalized in item["source_url"].lower()
    ]


def _print_match_list(matches):
    print(f"Found {len(matches)} matching headlines:")
    for index, item in enumerate(matches, start=1):
        print(f"  {index}. {item['title']}")
        print(f"     {item['url']}")


def _summarize_matches(matches, max_articles=3):
    print("\nSummaries for matched articles:")
    for item in matches[:max_articles]:
        print(f"\n---\n{item['title']}")
        print(f"Source: {item['source']}")
        html = _safe_request(item['url'])
        article_text = _extract_article_text(html, item['url']) if html else None
        summary = _summarize_text(article_text or "", max_sentences=4)
        if summary:
            print(summary)
        else:
            print("  Could not summarize this article.")


def _offer_followup_suggestions(query=None):
    suggestions = [
        "Ask me to compare these developments with the last major event in the same region.",
        "Ask for a timeline of the key events involved.",
        "Ask how this story may affect global politics or markets.",
    ]
    if query:
        suggestions.insert(0, f"Ask for a deeper explanation of why '{query}' matters right now.")
    print("\nHow can I help you continue?")
    for idx, suggestion in enumerate(suggestions, start=1):
        print(f"  {idx}. {suggestion}")


def _refresh_headlines():
    latest_items = []
    for source in NEWS_SOURCES:
        html = _safe_request(source["url"])
        headlines = _extract_headlines(html, source["url"])
        if not headlines:
            print(f"{source['name']} ({source['url']}): no headlines found or source format changed.")
            continue

        print(f"{source['name']} ({source['url']}):")
        for headline in headlines[:MAX_HEADLINES_PER_SOURCE]:
            latest_items.append(
                {
                    "source": source["name"],
                    "source_url": source["url"],
                    "title": headline["title"],
                    "url": headline["url"],
                    "scraped_at": datetime.utcnow().isoformat() + "Z",
                }
            )
            print(f"  {len(latest_items)}. {headline['title']}")
            print(f"     {headline['url']}")
        print()

    if latest_items:
        _save_cache({"timestamp": datetime.utcnow().isoformat() + "Z", "items": latest_items})
    return latest_items


def _prompt_user(prompt_text):
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def news_command(args=None):
    print(f"Welcome to the news stand. Fetching the latest headlines for {datetime.now().strftime('%Y-%m-%d')}...\n")
    latest_items = _refresh_headlines()
    cache = _load_cache()

    if args is not None and args.strip():
        resolved = _find_cached_item(args, cache)
        if isinstance(resolved, dict) and resolved.get("url"):
            _format_article_detail(resolved["url"], title=resolved.get("title"))
            return
        if isinstance(resolved, list) and len(resolved) == 1:
            _format_article_detail(resolved[0]["url"], title=resolved[0].get("title"))
            return
        if isinstance(resolved, list) and len(resolved) > 1:
            _print_match_list(resolved)
            selection = _prompt_user("Enter the number you'd like details for, or press Enter to summarize the first matches: ")
            if selection.isdigit():
                choice = int(selection) - 1
                if 0 <= choice < len(resolved):
                    _format_article_detail(resolved[choice]["url"], title=resolved[choice].get("title"))
                    return
            _summarize_matches(resolved)
            _offer_followup_suggestions(args)
            return
        print("Could not resolve that headline. Showing the latest headlines and asking what you want to explore.\n")

    topic_query = args.strip() if args else _prompt_user(
        "What headline number, URL, or topic would you like to explore? \n> "
    )
    if not topic_query:
        print("No topic selected. Use /news again when you are ready.")
        return

    selection = _find_cached_item(topic_query, cache)
    if isinstance(selection, dict) and selection.get("url"):
        _format_article_detail(selection["url"], title=selection.get("title"))
        return

    matches = _search_headlines(topic_query, cache.get("items", []))
    if not matches:
        print(f"No headlines matched '{topic_query}'. Here are the latest headlines again:")
        _print_match_list(cache.get("items", [])[:MAX_HEADLINES_PER_SOURCE])
        return

    _print_match_list(matches)
    if len(matches) == 1:
        _summarize_matches(matches, max_articles=1)
        _offer_followup_suggestions(topic_query)
        return

    next_choice = _prompt_user(
        "Enter a number to inspect that article, or press Enter to summarize the top matches: "
    )
    if next_choice.isdigit():
        idx = int(next_choice) - 1
        if 0 <= idx < len(matches):
            _format_article_detail(matches[idx]["url"], title=matches[idx].get("title"))
            return

    _summarize_matches(matches)
    _offer_followup_suggestions(topic_query)
