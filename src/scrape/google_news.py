from __future__ import annotations

import logging
import urllib.parse

from .rss import Article, fetch_rss

log = logging.getLogger(__name__)


def fetch_google_news(query: str, niche: str, max_age_hours: int) -> list[Article]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    articles = fetch_rss(url, niche, max_age_hours)
    # Google News uses its own source names; prepend the query for clarity
    for a in articles:
        a.source = f"Google News: {query}"
    return articles
