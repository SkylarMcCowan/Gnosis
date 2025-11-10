import requests
from bs4 import BeautifulSoup
from datetime import datetime

NEWS_SOURCES = [
    "https://www.bbc.com/",
    "www.theguardian.com",
    "https://www.theguardian.com/science",
    "https://www.cnn.com",
    "https://www.nbc.com",
    "https://www.apnews.com",
    "https://www.aljazeera.com",
    "https://www.npr.org",
    "https://www.scotusblog.com/category/capital-cases/",
]

def news_command(args=None):
    """
    Fetch and display news headlines from multiple sources.
    """
    print(f"Fetching the latest news headlines for {datetime.now().strftime('%Y-%m-%d')}...\n")
    for url in NEWS_SOURCES:
        print(f"Source: {url}")
        try:
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.text, "html.parser")
            # TODO: Customize the selector for each site
            headlines = [h.get_text(strip=True) for h in soup.select("h2") if h.get_text(strip=True)]
            if headlines:
                for headline in headlines[:5]:  # Show up to 5 headlines per source
                    print("-", headline)
            else:
                print("  [No headlines found or selector needs update]")
        except Exception as e:
            print("  [Error fetching headlines]")
        print()